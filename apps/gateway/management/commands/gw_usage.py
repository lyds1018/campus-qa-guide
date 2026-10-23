"""台账汇总：按日 × 任务看调用数、token、成本、缓存命中与延迟分位。"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.gateway import meter


class Command(BaseCommand):
    help = "汇总 ai_calls 台账（日 / 任务）"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7, help="回看天数，默认 7")
        parser.add_argument("--json", action="store_true", help="输出 JSON，便于贴进评测报告")

    def handle(self, *args, **options):
        rows = meter.usage(days=options["days"])
        pending = meter.pending()

        if options["json"]:
            self.stdout.write(json.dumps(rows, ensure_ascii=False, indent=2))
            return

        if not rows:
            self.stdout.write("台账为空。先跑 gw_probe 或一次问答，再回来看。")
            return

        self.stdout.write(
            f"{'日期':<12}{'任务':<11}{'调用':>6}{'token':>9}{'成本':>10}"
            f"{'缓存':>6}{'P50':>8}{'P95':>8}"
        )
        self.stdout.write("-" * 70)
        total_cost = total_calls = total_tokens = 0
        for row in rows:
            total_cost += row["cost"]
            total_calls += row["calls"]
            total_tokens += row["tokens"]
            self.stdout.write(
                f"{row['day']:<12}{row['task']:<11}{row['calls']:>6}{row['tokens']:>9}"
                f"{row['cost']:>10.4f}{row['cache_hits']:>6}"
                f"{row['p50_ms']:>8.0f}{row['p95_ms']:>8.0f}"
            )
        self.stdout.write("-" * 70)
        self.stdout.write(
            f"{'合计':<23}{total_calls:>6}{total_tokens:>9}{total_cost:>10.4f}"
        )
        if pending:
            self.stdout.write(
                self.style.WARNING(f"缓冲区还有 {pending} 条未落库（不足 50 条且未满 5 秒）")
            )
