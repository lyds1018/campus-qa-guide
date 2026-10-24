"""降级演练：按场景注入故障，跑同一批样本，输出"坏一半时还像不像话"的矩阵。

报告落 `EVAL_REPORT_DIR`，与批量回归的报告同目录、同命名规则。

用法：
    uv run python manage.py p7_drill --limit 5
    uv run python manage.py p7_drill --limit 3 --json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.eval import drill, runner
from apps.eval.models import EvalRun
from apps.gateway.sync import run


class Command(BaseCommand):
    help = "降级演练：五个故障场景 × 前 N 条样本，写 eval_runs(kind=drill)"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=5, help="每个场景跑几条（默认 5）")
        parser.add_argument("--file", default="", help="黄金集路径")
        parser.add_argument("--label", default="", help="本次演练标签")
        parser.add_argument("--json", action="store_true", help="输出 JSON")
        parser.add_argument("--no-report", action="store_true", help="不写 markdown 报告")

    def handle(self, *args, **opts):
        rows = runner.load_rows(Path(opts["file"]) if opts["file"] else None)
        if not rows:
            self.stderr.write("黄金集为空")
            return
        limit = max(1, min(opts["limit"], len(rows)))
        started_at = timezone.now()
        started = time.monotonic()

        def progress(scenario, item) -> None:
            if opts["json"]:
                return
            self.stdout.write(
                f"[{scenario.name}] 作答 {item['answered']}/{item['samples']} "
                f"兜底 {item['fallback']} 失败 {item['bad']} P50 {item['latency_p50_ms']}ms"
            )

        result = run(drill.run_drill(rows, limit=limit, progress=progress))
        duration_ms = int((time.monotonic() - started) * 1000)
        cost = runner.cost_since(started_at)
        samples = sum(item["samples"] for item in result["scenarios"])
        label = opts["label"] or "演练"

        report_path = ""
        if not opts["no_report"]:
            text = drill.markdown_report(
                result, label=label, cost=cost, duration_ms=duration_ms
            )
            report_path = str(runner.write_report(text, label=label))

        record = EvalRun.objects.create(
            kind=EvalRun.Kind.DRILL,
            label=opts["label"],
            samples=samples,
            metrics=result,
            report_path=report_path,
            cost=cost,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=timezone.now(),
        )

        if opts["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "run_id": record.pk,
                        "cost": str(cost),
                        "duration_ms": duration_ms,
                        "report": report_path,
                        **result,
                    },
                    ensure_ascii=False,
                )
            )
            return

        self.stdout.write("")
        widths = [14, 30, 6, 6, 10, 6, 10, 8]
        for row in drill.matrix_rows(result):
            cells = []
            for i, cell in enumerate(row):
                width = widths[i] if i < len(widths) else 10
                cells.append(_pad(cell, width))
            self.stdout.write("  ".join(cells))
        self.stdout.write(
            self.style.SUCCESS(
                f"演练完成：{samples} 次调用，{duration_ms / 1000:.1f}s，¥{cost:.4f}，"
                f"记录 drill#{record.pk}"
            )
        )
        if report_path:
            self.stdout.write(self.style.SUCCESS(f"报告：{report_path}"))


def _pad(text: str, width: int) -> str:
    """中文字符按两个宽度算，表格才对得齐。"""
    length = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - length)

