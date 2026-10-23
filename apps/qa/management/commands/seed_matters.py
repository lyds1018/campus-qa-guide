"""从已发布的办事指南语料生成事项与流程基线数据。

P6 才有事项维护界面，P3 的 M7 需要事项/流程才能验证，所以先按语料结构生成一版：
一份 guide 文档 = 一个事项 = 一条 Matter + 若干 Flow。code 由标题哈希得到，重复执行不会翻倍。

材料清单不入 flows：Matter 没有材料字段，Flow.materials 是"该步骤需要的材料"，
把整份清单塞进某一步只会把数据弄脏。材料仍以块小节为准（M7 的抽取路径）。
"""

from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.knowledge.models import Document, PublishStatus
from apps.knowledge.repositories import ReadRepository, WriteRepository
from apps.qa import matters


def matter_code(title: str) -> str:
    return "G" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:10].upper()


class Command(BaseCommand):
    help = "按已发布的 guide 语料生成 Matter / Flow 基线（可重复执行）"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
        parser.add_argument("--doc-type", default="guide", help="默认 guide")

    def handle(self, *args, **opts):
        repo = ReadRepository()
        writer = WriteRepository()
        docs = list(
            Document.objects.filter(
                status=PublishStatus.PUBLISHED, doc_type=opts["doc_type"]
            ).order_by("title")
        )
        if not docs:
            self.stderr.write("没有已发布的 guide 文档，先跑 ingest --publish")
            return

        total_steps = 0
        for doc in docs:
            chunks = list(repo.chunks_of(doc.pk))
            steps: list[str] = []
            for chunk in chunks:
                path = (chunk.meta or {}).get("section_path") or []
                section = path[-1] if path else ""
                for heading, body in matters.split_sections(chunk.content):
                    if matters.kind_of(heading or section) != "step":
                        continue
                    for item in matters.items_from(body, heading, ordered=True):
                        if item not in steps:
                            steps.append(item)

            summary = ""
            if chunks:
                summary = _plain_text(chunks[0].content)[:180]

            if opts["dry_run"]:
                self.stdout.write(f"[dry] {doc.title} steps={len(steps)}")
                for i, s in enumerate(steps[:5], 1):
                    self.stdout.write(f"   {i}. {s[:60]}")
                continue

            with transaction.atomic():
                matter = writer.upsert_matter(
                    matter_code(doc.title),
                    name=doc.title,
                    dept=doc.dept,
                    category="guide",
                    summary=summary,
                    status=PublishStatus.PUBLISHED,
                    version=1,
                    effective_from=doc.effective_from,
                )
                writer.replace_flows(
                    matter,
                    [
                        {
                            "step_no": i,
                            "title": text[:120],
                            "description": "",
                            "materials": [],
                            "channel": "both",
                        }
                        for i, text in enumerate(steps[:20], 1)
                    ],
                )
            total_steps += len(steps)

        if not opts["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(f"事项 {len(docs)} 个，流程步骤 {total_steps} 条")
            )


def _plain_text(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())
