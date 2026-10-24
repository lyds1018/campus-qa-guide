"""批量回归：跑黄金集，写 `eval_runs`，生成 markdown 报告。

用法：
    uv run python manage.py p7_eval --label 基线
    uv run python manage.py p7_eval --limit 10 --no-report
    uv run python manage.py p7_eval --file apps/qa/fixtures/golden.jsonl --json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.eval import runner
from apps.eval.models import EvalRun
from apps.gateway.sync import run


class Command(BaseCommand):
    help = "批量回归：黄金集跑批 + 指标 + 报告（写 eval_runs）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", default="", help="黄金集路径，默认 apps/qa/fixtures/golden.jsonl"
        )
        parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
        parser.add_argument("--label", default="", help="这次回归的名字，例如 基线 / 换重排模型")
        parser.add_argument("--audience", default="unknown", help="提问人身份")
        parser.add_argument("--json", action="store_true", help="只输出 JSON 摘要")
        parser.add_argument("--no-report", action="store_true", help="不写 markdown 报告")

    def handle(self, *args, **opts):
        rows = runner.load_rows(Path(opts["file"]) if opts["file"] else None)
        if opts["limit"]:
            rows = rows[: opts["limit"]]
        if not rows:
            self.stderr.write("黄金集为空")
            return

        started_at = timezone.now()
        started = time.monotonic()

        def progress(index: int, total: int, sample) -> None:
            if opts["json"]:
                return
            mark = "✓" if sample.answerable_ok and not sample.missing else "✗"
            self.stdout.write(
                f"[{index}/{total}] {mark} {sample.q}"
                f"（{sample.latency_ms}ms{'，拒答' if not sample.answerable else ''}）"
            )

        samples = run(runner.run_samples(rows, audience=opts["audience"], progress=progress))
        summary = runner.summarize(samples)
        duration_ms = int((time.monotonic() - started) * 1000)
        cost = runner.cost_since(started_at)

        report_path = ""
        if not opts["no_report"]:
            text = runner.markdown_report(
                summary=summary,
                samples=samples,
                label=opts["label"],
                cost=cost,
                cost_note="（跑批窗口内的 ai_calls 合计）",
            )
            report_path = str(runner.write_report(text, label=opts["label"] or "eval"))

        record = EvalRun.objects.create(
            kind=EvalRun.Kind.EVAL,
            label=opts["label"],
            samples=len(samples),
            metrics={**summary, "targets": runner.targets_of(summary)},
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
                        "summary": summary,
                        "cost": str(cost),
                        "duration_ms": duration_ms,
                        "report": report_path,
                        "samples": [s.as_dict() for s in samples],
                    },
                    ensure_ascii=False,
                )
            )
            return

        self.stdout.write("")
        self.stdout.write(
            f"样本 {summary['samples']}  作答 {summary['answered']}  拒答 {summary['refused']}"
        )
        self.stdout.write(
            f"hit@3 {summary['hit_at_3']:.0%}  must {summary['must_ok']:.0%}  "
            f"可答判对 {summary['answer_ok']:.0%}  拒答判对 {summary['refuse_ok']:.0%}"
        )
        self.stdout.write(
            f"引用覆盖 {summary['citation_rate']:.0%}  校验通过 {summary['verified_rate']:.0%}  "
            f"意图 {summary['intent_acc']:.0%}"
        )
        self.stdout.write(
            f"P50 {summary['latency_p50_ms']}ms  P95 {summary['latency_p95_ms']}ms  "
            f"耗时 {duration_ms / 1000:.1f}s  ¥{cost:.4f}"
        )
        for key, item in runner.targets_of(summary).items():
            if not item["ok"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"未达标 {key}={item['value']:.2f} < {item['target']:.2f}"
                    )
                )
        if report_path:
            self.stdout.write(self.style.SUCCESS(f"报告：{report_path}"))
        self.stdout.write(f"记录：eval_runs#{record.pk}")
