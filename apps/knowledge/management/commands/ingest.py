"""导入语料：目录或单文件。

默认走队列（worker 消费），--sync 直接执行，--dry-run 只统计。
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.knowledge import queue
from apps.knowledge.ingest import dry_run, guess_doc_type, ingest_path, scan
from apps.knowledge.models import IngestJob, JobStatus


class Command(BaseCommand):
    help = "导入校园语料（目录或单文件）"

    def add_arguments(self, parser):
        parser.add_argument("path", help="语料目录或单个文件")
        parser.add_argument("--doc-type", choices=["guide", "policy", "faq", "notice"])
        parser.add_argument("--dept", default="", help="归口部门")
        parser.add_argument("--publish", action="store_true", help="直接置为已发布")
        parser.add_argument("--sync", action="store_true", help="同步执行，不进队列")
        parser.add_argument("--dry-run", action="store_true", help="只统计，不写库不上传")
        parser.add_argument("--verbose", action="store_true", help="逐文件输出")

    def handle(self, *args, **options):
        root = Path(options["path"]).resolve()
        if not root.exists():
            raise CommandError(f"路径不存在：{root}")

        if options["dry_run"]:
            stats = dry_run(root)
            self._report(stats, options["verbose"])
            return

        if options["sync"]:
            stats = ingest_path(
                root,
                doc_type=options["doc_type"],
                dept=options["dept"],
                publish=options["publish"],
            )
            self._report(stats, options["verbose"])
            return

        files = scan(root)
        if not files:
            raise CommandError(f"未找到可导入文件：{root}")

        queued = 0
        for path in files:
            dtype = options["doc_type"] or guess_doc_type(root, path)
            job = IngestJob.objects.create(
                source_path=str(path),
                doc_type=dtype,
                dept=options["dept"],
                publish=options["publish"],
                status=JobStatus.PENDING,
            )
            queue.push(job.pk)
            queued += 1

        self.stdout.write(
            self.style.SUCCESS(f"已入队 {queued} 个任务（队列深度 {queue.depth()}），"
                               f"另开终端执行：uv run python manage.py worker")
        )

    def _report(self, stats, verbose: bool) -> None:
        if verbose:
            for line in stats.details:
                self.stdout.write(line)
        self.stdout.write(stats.brief())
        if stats.failed:
            self.stdout.write(self.style.WARNING(f"{stats.failed} 个文件失败"))
