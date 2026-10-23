"""向量回填占位。

P1 只建列与索引，不产出向量；P2 的 M12 落地后在此实现：
按批取 embedding IS NULL 的 published 块 → 调 embedding 任务 → 批量 update。
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.knowledge.models import Chunk, PublishStatus


class Command(BaseCommand):
    help = "回填 chunk 向量（P2 实现，当前只统计待回填数量）"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=64)

    def handle(self, *args, **options):
        pending = Chunk.objects.filter(
            status=PublishStatus.PUBLISHED, embedding__isnull=True
        ).count()
        total = Chunk.objects.filter(status=PublishStatus.PUBLISHED).count()
        self.stdout.write(f"published 块 {total} 条，待回填 {pending} 条")
        if pending:
            self.stdout.write(
                self.style.WARNING(
                    "P1 不产出向量：P2 的 M12 完成后在此接 embedding 调用并写回。"
                )
            )
