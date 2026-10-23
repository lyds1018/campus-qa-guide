"""任务消费者：常驻进程，BRPOP 取 ingest_jobs 并执行。

启动时先把超时未结束的 running 重置为 pending，再把 PG 里 pending 的任务补投队列
（队列丢消息时可自愈）。--once 处理完当前队列即退出，供测试与一次性导入用。
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.knowledge import queue


class Command(BaseCommand):
    help = "消费入库任务队列"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="处理完当前队列即退出")
        parser.add_argument("--timeout", type=int, default=5, help="BRPOP 阻塞秒数")

    def handle(self, *args, **options):
        once = options["once"]
        timeout = 1 if once else options["timeout"]

        stale = queue.reset_stale()
        if stale:
            self.stdout.write(f"重置僵尸任务 {stale} 条")
        # 仅在队列为空时才从 PG 重建，避免正常流程重复投递
        if queue.depth() == 0:
            requeued = queue.requeue_pending()
            if requeued:
                self.stdout.write(f"补投 pending 任务 {requeued} 条")

        self.stdout.write(
            f"worker 启动，队列 {settings.INGEST_QUEUE}，模式 {'once' if once else '常驻'}"
        )

        done = 0
        while True:
            job_id = queue.pop(timeout=timeout)
            if job_id is None:
                if once:
                    break
                continue
            status = queue.process_job(job_id)
            done += 1
            self.stdout.write(f"job#{job_id} → {status}")

        self.stdout.write(self.style.SUCCESS(f"处理完成 {done} 条"))
