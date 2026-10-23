"""向量回填（P2）。

默认只补 embedding IS NULL 的已发布块；--force 才会全量重算——
换嵌入模型必须先 --force，否则新旧模型的向量会混在同一个索引里。
"""

from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand, CommandError

from apps.gateway import meter
from apps.gateway.base import DimensionMismatch, NotConfigured
from apps.gateway.gateway import gateway
from apps.gateway.sync import run
from apps.knowledge.models import Chunk, PublishStatus


def _fetch(after_id: int, batch: int, force: bool) -> list[Chunk]:
    qs = Chunk.objects.filter(status=PublishStatus.PUBLISHED, pk__gt=after_id)
    if not force:
        qs = qs.filter(embedding__isnull=True)
    return list(qs.order_by("pk").only("id", "content")[:batch])


def _save(rows: list[Chunk], vectors: list[list[float]]) -> int:
    for row, vec in zip(rows, vectors, strict=False):
        row.embedding = vec
    return Chunk.objects.bulk_update(rows, ["embedding"], batch_size=200)


class Command(BaseCommand):
    help = "回填 chunk 向量（默认只补空值）"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=64)
        parser.add_argument("--force", action="store_true", help="全量重算（换模型后用）")
        parser.add_argument("--dry-run", action="store_true", help="只统计，不调用模型")
        parser.add_argument("--limit", type=int, default=0, help="最多处理多少块，0 为不限")

    def handle(self, *args, **options):
        force = options["force"]
        batch = max(1, min(options["batch_size"], 256))
        limit = max(0, options["limit"])

        base = Chunk.objects.filter(status=PublishStatus.PUBLISHED)
        total = base.count()
        pending = base.filter(embedding__isnull=True).count()
        target = total if force else pending

        self.stdout.write(
            f"published 块 {total} 条，待回填 {pending} 条"
            f"{'，--force 全量重算' if force else ''}"
        )
        if target == 0:
            self.stdout.write(self.style.SUCCESS("没有需要处理的块"))
            return
        if options["dry_run"]:
            self.stdout.write(f"dry-run：将处理 {min(target, limit) if limit else target} 条")
            return

        try:
            done = run(self._run(batch, force, limit))
        except NotConfigured as exc:
            raise CommandError(f"{exc}；补齐 GW_EMBED_* 后再跑") from exc
        except DimensionMismatch as exc:
            raise CommandError(f"维度不匹配：{exc}") from exc
        finally:
            # 批量任务结束时必须主动落库：缓冲不足 50 条时不会自动 flush，进程一退就丢了
            meter.flush_sync()

        self.stdout.write(self.style.SUCCESS(f"完成，写入 {done} 条向量"))
        if not force:
            left = base.filter(embedding__isnull=True).count()
            if left:
                self.stdout.write(self.style.WARNING(f"仍有 {left} 条空向量，重跑本命令即可续上"))

    async def _run(self, batch: int, force: bool, limit: int) -> int:
        after = 0
        done = 0
        while True:
            size = min(batch, limit - done) if limit else batch
            if size <= 0:
                break
            rows = await asyncio.to_thread(_fetch, after, size, force)
            if not rows:
                break

            texts = [row.content for row in rows]
            try:
                vectors = await gateway.embed(texts, kind="doc")  # 维度校验在网关内
            except NotConfigured:
                raise
            except Exception as exc:
                raise CommandError(
                    f"块 id>{after} 这一批失败：{type(exc).__name__}: {exc}；"
                    "已提交的批次不会回滚，重跑只处理剩下的空值"
                ) from exc

            await asyncio.to_thread(_save, rows, vectors)
            after = rows[-1].pk
            done += len(rows)
            self.stdout.write(f"  已写入 {done} 条（当前块 id={after}）")
        return done
