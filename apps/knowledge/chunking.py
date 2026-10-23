"""切分与分词。

规则（与 P1 文档 §6.2 一致）：
- 标题只更新 section_path，并与后续正文合并成一个段，不单独成块；
- 长段按句末标点切开，单句超长再硬切；
- 相邻块取整句尾部重叠，找不到句界就不重叠，宁短不脏；
- 低于最短长度的块并入前一块。

search_text 存 jieba 搜索结果，查询侧必须用同一分词器。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import jieba

from apps.knowledge.parsing.base import ParsedDoc

jieba.setLogLevel(logging.WARNING)

SENT_END = "。！？；!?;"
_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])")


@dataclass
class Segment:
    text: str
    page: int
    section_path: list[str] = field(default_factory=list)


def tokenize(text: str) -> str:
    """jieba 搜索引擎模式分词，空格拼接，供 to_tsvector 使用。"""
    return " ".join(t for t in jieba.cut_for_search(text) if t.strip())


def _pack_sentences(text: str, size: int) -> list[str]:
    """把长段按句子打包成不超过 size 的片段。"""
    out: list[str] = []
    cur = ""
    for sent in _SENT_SPLIT.split(text):
        if not sent:
            continue
        while len(sent) > size:
            out.append(sent[:size])
            sent = sent[size:]
        if cur and len(cur) + len(sent) > size:
            out.append(cur)
            cur = sent
        else:
            cur += sent
    if cur:
        out.append(cur)
    return out


def _segments(parsed: ParsedDoc, size: int) -> list[Segment]:
    segs: list[Segment] = []
    path: list[str] = []
    pending: list[str] = []
    for page_no, block in parsed.iter_blocks():
        text = block.text.strip()
        if not text:
            continue
        if block.level > 0:
            path = path[: block.level - 1] + [text]
            pending.append(text)
            continue
        body = "\n".join([*pending, text]) if pending else text
        pending = []
        for part in _pack_sentences(body, size):
            segs.append(Segment(text=part, page=page_no, section_path=list(path)))
    if pending:  # 文末只有标题，也要留下
        segs.append(Segment(text="\n".join(pending), page=1, section_path=list(path)))
    return segs


def _tail_overlap(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    tail = text[-overlap:]
    for i, ch in enumerate(tail):
        if ch in SENT_END:
            return tail[i + 1 :].lstrip()
    return ""


def build_chunks(
    parsed: ParsedDoc,
    size: int = 500,
    overlap: int = 80,
    min_len: int = 120,
) -> list[dict]:
    """返回 [{ordinal, content, search_text, meta}, ...]。"""
    segs = _segments(parsed, size)
    blocks: list[Segment] = []
    buf = ""
    buf_path: list[str] = []
    buf_page = 1

    for seg in segs:
        if not buf:
            buf_path = list(seg.section_path)
            buf_page = seg.page
            buf = seg.text
            continue
        if len(buf) + len(seg.text) + 1 > size:
            blocks.append(Segment(text=buf, page=buf_page, section_path=buf_path))
            tail = _tail_overlap(buf, overlap)
            buf = f"{tail}\n{seg.text}" if tail else seg.text
            buf_path = list(seg.section_path)
            buf_page = seg.page
        else:
            buf = f"{buf}\n{seg.text}"
    if buf.strip():
        blocks.append(Segment(text=buf, page=buf_page, section_path=buf_path))

    merged: list[Segment] = []
    for blk in blocks:
        if merged and len(blk.text) < min_len:
            prev = merged[-1]
            merged[-1] = Segment(
                text=f"{prev.text}\n{blk.text}",
                page=prev.page,
                section_path=prev.section_path,
            )
        else:
            merged.append(blk)

    return [
        {
            "ordinal": i,
            "content": blk.text.strip(),
            "search_text": tokenize(blk.text),
            "meta": {
                "section_path": blk.section_path,
                "page": blk.page,
                "char_len": len(blk.text.strip()),
            },
        }
        for i, blk in enumerate(merged)
        if blk.text.strip()
    ]
