"""M6 检索：双路召回 → RRF 融合 → 重排 → 门槛判定。

三处口径先定死：

- 双路各自独立取 top-k，融合只做排名，不做分数加权求和。向量余弦与 ts_rank
  量纲不同，加权求和要先归一，而归一参数换个模型就得重标，不可维护。
- 全文用 OR 组合（`to_tsquery('simple', 'a | b')`）。问句里 8 个词通常不会同时
  出现在同一块，AND 会把召回打成 0。
- 重排不可用时直接用归一化融合分判定可答，不换阈值口径。
"""

from __future__ import annotations

import asyncio
import time

from django.conf import settings

from apps.gateway.base import GatewayError
from apps.gateway.gateway import gateway
from apps.knowledge.repositories import ReadRepository
from apps.qa import lexicon
from apps.qa.types import Evidence, RetrievalResult

# 与 0002_indexes 的表达式索引保持字面量一致，参数只留给 tsquery
TS_WHERE = "to_tsvector('simple', chunks.search_text) @@ to_tsquery('simple', %s)"
TS_RANK = (
    "ts_rank(to_tsvector('simple', chunks.search_text), to_tsquery('simple', %s))"
)


def _fts_ids(base, query: str, k: int) -> list[int]:
    terms = lexicon.lexemes(query)
    if not terms:
        return []
    tsquery = " | ".join(f"'{t}'" for t in terms)
    qs = base.extra(
        where=[TS_WHERE],
        params=[tsquery],
        select={"fts_rank": TS_RANK},
        select_params=[tsquery],
    ).order_by("-fts_rank")
    return [int(row[0]) for row in qs.values_list("id", "fts_rank")[:k]]


def _vector_hits(base, vec: list[float], k: int) -> list[tuple[int, float]]:
    """返回 (chunk_id, 余弦相似度)。相似度是绝对量，只用来判"够不够近"，不参与融合。"""
    from pgvector.django import CosineDistance

    qs = (
        base.filter(embedding__isnull=False)
        .annotate(dist=CosineDistance("embedding", vec))
        .order_by("dist")
        .values_list("id", "dist")
    )
    return [(int(row[0]), 1.0 - float(row[1])) for row in qs[:k]]


def fuse(
    vector_ids: list[int], fts_ids: list[int], k: int | None = None
) -> dict[int, float]:
    """RRF：score = Σ 1/(k+rank)。两路都命中且靠前的块自然浮上来。

    返回的是归一化到 [0,1] 的分：除以"两路都取第一"的理论最大值。
    单路可用时基准改成单路最大值，否则 embedding 一挂，全库都过不了门槛。
    """
    k = k or settings.QA_RRF_K
    raw: dict[int, float] = {}
    for rank, cid in enumerate(vector_ids, 1):
        raw[cid] = raw.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, cid in enumerate(fts_ids, 1):
        raw[cid] = raw.get(cid, 0.0) + 1.0 / (k + rank)

    lists = int(bool(vector_ids)) + int(bool(fts_ids))
    if not raw or not lists:
        return {}
    base_score = lists * (1.0 / (k + 1))
    return {cid: min(1.0, s / base_score) for cid, s in raw.items()}


def _recall(
    query: str, vec: list[float] | None, doc_types: list[str] | None
) -> tuple[list[dict], int, int]:
    """同步召回（Django ORM 是同步的，由调用方切线程）。"""
    repo = ReadRepository()
    base = repo.active_chunks(doc_types)
    vec_hits = _vector_hits(base, vec, settings.QA_TOP_K_VECTOR) if vec else []
    fts_ids = _fts_ids(base, query, settings.QA_TOP_K_FTS)
    vector_ids = [cid for cid, _ in vec_hits]
    sims = dict(vec_hits)
    scores = fuse(vector_ids, fts_ids)

    keep = sorted(scores, key=lambda cid: scores[cid], reverse=True)[: settings.QA_FUSE_KEEP]
    if not keep:
        return [], len(vector_ids), len(fts_ids)

    rows = {
        c.id: c
        for c in repo.active_chunks(doc_types).select_related("document").filter(id__in=keep)
    }
    rv = {cid: i for i, cid in enumerate(vector_ids, 1)}
    rf = {cid: i for i, cid in enumerate(fts_ids, 1)}
    terms = set(lexicon.lexemes(query))

    cands: list[dict] = []
    for cid in keep:
        chunk = rows.get(cid)
        if chunk is None:          # 取回期间被归档，跳过
            continue
        source = "both" if cid in rv and cid in rf else ("vector" if cid in rv else "fts")
        meta = chunk.meta or {}
        path = meta.get("section_path") or []
        cands.append(
            {
                "chunk_id": cid,
                "document_id": chunk.document_id,
                "title": chunk.document.title,
                "doc_type": chunk.document.doc_type,
                "dept": chunk.document.dept,
                "section": path[-1] if path else "",
                "page": int(meta.get("page") or 1),
                "content": chunk.content,
                "fusion": scores[cid],
                "sim": sims.get(cid, 0.0),
                "overlap": len(terms & set((chunk.search_text or "").split())),
                "source": source,
                "rank_vector": rv.get(cid),
                "rank_fts": rf.get(cid),
                "effective_from": (
                    chunk.document.effective_from.isoformat()
                    if chunk.document.effective_from
                    else ""
                ),
            }
        )
    return cands, len(vector_ids), len(fts_ids)


def _assemble(cands: list[dict], scores: list[float]) -> list[Evidence]:
    """按分数排序、截断到字符预算、编号。分数同分时保持融合顺序。"""
    order = sorted(range(len(cands)), key=lambda i: scores[i], reverse=True)
    out: list[Evidence] = []
    used = 0
    for i in order:
        cand = cands[i]
        size = len(cand["content"])
        if out and used + size > settings.QA_MAX_EVIDENCE_CHARS:
            break
        used += size
        out.append(
            Evidence(
                ref=len(out) + 1,
                chunk_id=cand["chunk_id"],
                document_id=cand["document_id"],
                title=cand["title"],
                doc_type=cand["doc_type"],
                dept=cand["dept"],
                section=cand["section"],
                page=cand["page"],
                content=cand["content"],
                score=scores[i],
                fusion=cand["fusion"],
                similarity=cand["sim"],
                overlap=cand["overlap"],
                source=cand["source"],
                rank_vector=cand["rank_vector"],
                rank_fts=cand["rank_fts"],
                effective_from=cand["effective_from"],
            )
        )
        if len(out) >= settings.QA_EVIDENCE_TOP:
            break
    return out


async def retrieve(
    query: str,
    *,
    doc_types: list[str] | None = None,
    top_k: int | None = None,
) -> RetrievalResult:
    """M6 入口。embedding 不可用时退纯全文；重排不可用时用融合分。"""
    started = time.monotonic()
    result = RetrievalResult(query=query)
    if not query.strip():
        result.reason = "empty_query"
        return result

    vec: list[float] | None = None
    try:
        vectors = await gateway.embed([query], kind="query")
        vec = vectors[0] if vectors else None
    except GatewayError as exc:
        result.notes.append(f"embed:{type(exc).__name__}")

    cands, n_vec, n_fts = await asyncio.to_thread(_recall, query, vec, doc_types)
    result.vector_hits = n_vec
    result.fts_hits = n_fts

    want = top_k or settings.QA_EVIDENCE_TOP

    ranked: list[Evidence] = []
    if cands:
        ranked_raw = await gateway.rerank(
            query, [c["content"] for c in cands], top_k=min(want, len(cands))
        )
        if ranked_raw:
            by_index = {r.index: r.score for r in ranked_raw if 0 <= r.index < len(cands)}
            idx = sorted(by_index, key=lambda i: by_index[i], reverse=True)
            floor = settings.QA_MIN_RERANK_SCORE * 0.5   # 门槛的一半，留一点上下文
            pick = [i for i in idx if by_index[i] >= floor][:want]
            ranked = _assemble([cands[i] for i in pick], [by_index[i] for i in pick])
            result.reranked = True
        else:
            ranked = _assemble(cands, [c["fusion"] for c in cands])[:want]
    result.evidence = ranked
    result.top_score = ranked[0].score if ranked else 0.0
    result.top_sim = ranked[0].similarity if ranked else 0.0
    result.top_overlap = ranked[0].overlap if ranked else 0

    if not ranked:
        result.reason = "no_evidence"
    elif result.reranked:
        # 重排分是绝对相关度，直接卡门槛
        result.answerable = result.top_score >= settings.QA_MIN_RERANK_SCORE
        result.reason = None if result.answerable else "low_confidence"
    else:
        # 没有重排时融合分只表达排名，不能当相关度用：
        # 库里只要有一块带向量，任何问句都能拿到"排名第一"，融合分必然是 1.0。
        # 所以这里必须回到绝对量——余弦相似度或命中词数。
        result.answerable = (
            result.top_sim >= settings.QA_MIN_VECTOR_SIM
            or result.top_overlap >= settings.QA_MIN_FTS_OVERLAP
        )
        result.reason = None if result.answerable else "low_confidence"

    result.notes.append(
        f"recall:vec={n_vec},fts={n_fts},keep={len(cands)},"
        f"rerank={'on' if result.reranked else 'off'},{int((time.monotonic() - started) * 1000)}ms"
    )
    return result
