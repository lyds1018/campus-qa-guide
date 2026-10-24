"""把用户反馈沉淀成黄金集样本。

原则：**只提议，不自动收**。默认只打印候选行（可粘进 JSONL），`--apply` 才追加，
且按问句去重、写回 `feedback.reviewed=True`，避免同一条被反复收进来。

为什么不做"点一次没用就进黄金集"：用户点"没用"的原因有一半是误点或预期不符，
直接进集会污染回归基线。
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.eval import runner
from apps.eval.models import Feedback


class Command(BaseCommand):
    help = "从用户反馈生成黄金集候选（默认只打印，--apply 才写文件）"

    def add_arguments(self, parser):
        parser.add_argument("--rating", default="down", choices=["down", "up", "all"])
        parser.add_argument(
            "--file", default="", help="追加目标，默认 apps/qa/fixtures/golden.jsonl"
        )
        parser.add_argument("--apply", action="store_true", help="真正写入并标记已收")
        parser.add_argument("--include-reviewed", action="store_true")

    def handle(self, *args, **opts):
        qs = Feedback.objects.all()
        if opts["rating"] != "all":
            qs = qs.filter(rating=opts["rating"])
        if not opts["include_reviewed"]:
            qs = qs.filter(reviewed=False)
        rows = list(qs.order_by("id"))

        target = Path(opts["file"]) if opts["file"] else runner.GOLDEN
        existing = {row["q"] for row in runner.load_rows(target)}

        lines: list[str] = []
        picked: list[Feedback] = []
        for row in rows:
            question = (row.question or "").strip()
            if not question or question in existing:
                continue
            expect = row.expect
            if expect == Feedback.Expect.UNSURE:
                # 没标"应可答/应拒答"时按原因猜：答非所问 → 应拒答，其余 → 应可答
                expect = "refuse" if row.reason == Feedback.Reason.OFF_TOPIC else "answer"
            item = {"q": question, "expect": expect, "intent": "", "must": [], "from": "feedback"}
            lines.append(json.dumps(item, ensure_ascii=False))
            existing.add(question)
            picked.append(row)

        if not lines:
            self.stdout.write("没有可收的候选（可能都已在黄金集里）")
            return

        self.stdout.write(f"候选 {len(lines)} 条：")
        for line in lines:
            self.stdout.write("  " + line)

        if not opts["apply"]:
            self.stdout.write(
                self.style.WARNING("未写入。确认无误后加 --apply 追加到 " + str(target))
            )
            return

        with target.open("a", encoding="utf-8") as handle:
            handle.write("\n")
            for line in lines:
                handle.write(line + "\n")
        for row in picked:
            row.reviewed = True
        Feedback.objects.bulk_update(picked, ["reviewed"])
        self.stdout.write(
            self.style.SUCCESS(
                f"已追加 {len(lines)} 条到 {target}，并标记 feedback.reviewed"
            )
        )
