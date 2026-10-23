"""M11 入库侧：扫描 → 校验 → 解析 → 切分 → 入库。

幂等：checksum 相同直接跳过；同标题同类型有新内容则归档旧版、版本号 +1。
事务：文档与块写在同一个事务里，任一步失败整体回滚（原件对象不回滚，可复用）。
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction

from apps.common import storage
from apps.knowledge.chunking import build_chunks
from apps.knowledge.models import Document, JobStatus, PublishStatus
from apps.knowledge.parsing import SUPPORTED_SUFFIXES, parse_bytes
from apps.knowledge.repositories import WriteRepository

TITLE_PREFIX = re.compile(r"^\d+\s*[-_.、．]\s*")
DATE_CN = re.compile(r"自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日起")
DATE_ISO = re.compile(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})")
MIN_CHARS = 50

StageHook = Callable[[str], None] | None


@dataclass
class IngestStats:
    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    chunks: int = 0
    details: list[str] = field(default_factory=list)

    def brief(self) -> str:
        return (
            f"total={self.total} ok={self.succeeded} "
            f"skipped={self.skipped} failed={self.failed} chunks={self.chunks}"
        )


def scan(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in SUPPORTED_SUFFIXES else []
    files = [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return files


def checksum_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guess_title(path: Path) -> str:
    stem = TITLE_PREFIX.sub("", path.stem).strip()
    return (stem or path.stem).replace("_", " ")[:200]


def guess_doc_type(root: Path, path: Path) -> str:
    """目录名即类型（corpus/guide/xxx.pdf）；取不到回退 guide。"""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return "guide"
    return rel.parts[0] if len(rel.parts) > 1 else "guide"


def extract_effective_from(text: str) -> date | None:
    """从正文找"自 2024 年 9 月 1 日起"或 2024-09-01 形态的生效日期。"""
    for pattern in (DATE_CN, DATE_ISO):
        m = pattern.search(text)
        if not m:
            continue
        try:
            y, mo, d = (int(g) for g in m.groups())
            return date(y, mo, d)
        except ValueError:
            continue
    return None


def _first_text(data: bytes, path: Path) -> str:
    try:
        parsed = parse_bytes(data, path.suffix)
    except Exception:
        return ""
    return parsed.pages[0].text if parsed.pages else ""


def process_file(
    path: Path,
    *,
    doc_type: str,
    dept: str,
    publish: bool,
    repo: WriteRepository,
    rel_path: str = "",
    on_stage: StageHook = None,
) -> tuple[str, Document | None, str, int]:
    """处理单个文件，返回 (job_status, document, message, chunk 数)。"""
    data = path.read_bytes()
    checksum = checksum_of(data)

    existed = repo.find_by_checksum(checksum)
    if existed:
        return JobStatus.SKIPPED, existed, f"checksum 已存在（doc#{existed.pk}）", 0

    if on_stage:
        on_stage("parse")
    parsed = parse_bytes(data, path.suffix)
    if parsed.char_count < MIN_CHARS:
        return JobStatus.FAILED, None, "no extractable text", 0

    ext = path.suffix.lower()
    object_key = storage.put_raw(checksum, ext, doc_type, data)

    title = guess_title(path)
    version = repo.latest_version(title, doc_type) + 1
    effective_from = extract_effective_from(parsed.pages[0].text if parsed.pages else "")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    if on_stage:
        on_stage("chunk")
    rows = build_chunks(
        parsed,
        size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
    )
    if not rows:
        return JobStatus.FAILED, None, "no chunks produced", 0

    if on_stage:
        on_stage("persist")
    with transaction.atomic():
        repo.archive_existing(title, doc_type)
        doc = repo.create_document(
            title=title,
            doc_type=doc_type,
            dept=dept,
            source_path=rel_path or str(path),
            object_key=object_key,
            checksum=checksum,
            mime=mime,
            size=len(data),
            page_count=parsed.page_count,
            status=PublishStatus.DRAFT,
            version=version,
            effective_from=effective_from,
        )
        storage.put_parsed(doc.pk, version, parsed.to_dict())
        repo.bulk_chunks(doc, rows, publish=publish)
        if publish:
            repo.publish(doc)

    return JobStatus.SUCCEEDED, doc, f"{len(rows)} chunks", len(rows)


def ingest_path(
    root: Path,
    *,
    doc_type: str | None = None,
    dept: str = "",
    publish: bool = False,
    repo: WriteRepository | None = None,
    on_stage: StageHook = None,
) -> IngestStats:
    """目录或单文件导入（同步执行）。"""
    repo = repo or WriteRepository()
    stats = IngestStats()
    files = scan(root)
    stats.total = len(files)

    for path in files:
        rel = str(path.relative_to(root)) if root.is_dir() else path.name
        dtype = doc_type or guess_doc_type(root, path)
        try:
            status, _doc, msg, n = process_file(
                path,
                doc_type=dtype,
                dept=dept,
                publish=publish,
                repo=repo,
                rel_path=rel,
                on_stage=on_stage,
            )
        except Exception as exc:  # 单文件失败不影响整批
            stats.failed += 1
            stats.details.append(f"FAIL {rel}: {type(exc).__name__}: {exc}")
            continue

        if status == JobStatus.SUCCEEDED:
            stats.succeeded += 1
            stats.chunks += n
            stats.details.append(f"OK   {rel} → {msg}")
        elif status == JobStatus.SKIPPED:
            stats.skipped += 1
            stats.details.append(f"SKIP {rel}: {msg}")
        else:
            stats.failed += 1
            stats.details.append(f"FAIL {rel}: {msg}")

    return stats


def dry_run(root: Path, repo: WriteRepository | None = None) -> IngestStats:
    """只统计，不写库、不上传。"""
    repo = repo or WriteRepository()
    stats = IngestStats()
    files = scan(root)
    stats.total = len(files)

    for path in files:
        rel = str(path.relative_to(root)) if root.is_dir() else path.name
        try:
            data = path.read_bytes()
        except OSError as exc:
            stats.failed += 1
            stats.details.append(f"FAIL {rel}: {exc}")
            continue
        if repo.find_by_checksum(checksum_of(data)):
            stats.skipped += 1
            stats.details.append(f"SKIP {rel}: checksum 已存在")
            continue
        try:
            text = _first_text(data, path)
        except Exception as exc:
            stats.failed += 1
            stats.details.append(f"FAIL {rel}: {type(exc).__name__}: {exc}")
            continue
        if len(text) < MIN_CHARS:
            stats.failed += 1
            stats.details.append(f"FAIL {rel}: 抽取不到正文")
            continue
        stats.succeeded += 1
        stats.details.append(f"WOULD {rel}")

    return stats
