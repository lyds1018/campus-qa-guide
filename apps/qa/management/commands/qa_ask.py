"""命令行单问：一次跑完 M5–M9，把中间结果打出来。

用途是排障与验收，不进产品路径。
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.gateway.sync import run
from apps.qa.pipeline import qa


class Command(BaseCommand):
    help = "问一句，打印理解 / 检索 / 生成 / 校验的全链路诊断"

    def add_arguments(self, parser):
        parser.add_argument("question", nargs="+", help="问题原文，多个词自动拼成一句")
        parser.add_argument("--audience", default="unknown", help="提问人身份，如 undergrad")
        parser.add_argument(
            "--doc-type", action="append", default=None, help="限定文档类型，可重复"
        )
        parser.add_argument("--stream", action="store_true", help="走流式路径")
        parser.add_argument("--json", action="store_true", help="输出完整 JSON")

    def handle(self, *args, **opts):
        question = " ".join(opts["question"])
        if opts["stream"]:
            self._stream(question, opts)
            return

        answer = run(
            qa.answer(
                question, audience=opts["audience"], doc_types=opts["doc_type"]
            )
        )
        if opts["json"]:
            import json

            self.stdout.write(json.dumps(answer.as_dict(), ensure_ascii=False, indent=2))
            return

        u = answer.understanding
        self.stdout.write(f"问句：{question}")
        if u:
            self.stdout.write(
                f"理解：intent={u.intent.value} src={u.source} 改写={u.rewritten}"
            )
        if answer.matter:
            self.stdout.write(
                f"事项：{answer.matter.name}（{answer.matter.source}）"
            )
        self.stdout.write("证据：")
        for e in answer.evidence:
            self.stdout.write(
                f"  [{e.ref}] {e.score:.3f} {e.source:6s} {e.label}"
            )
        if answer.conflicts:
            self.stdout.write(f"冲突：{answer.conflicts}")
        self.stdout.write(f"可答：{answer.answerable}  拒答原因={answer.refusal_reason}")
        self.stdout.write("--- 回答 ---")
        self.stdout.write(answer.text)
        if answer.checklist:
            self.stdout.write("--- 清单 ---")
            for item in answer.checklist:
                self.stdout.write(f"  {item.ordinal}. [{item.kind}] {item.text}")
        if answer.checks:
            c = answer.checks
            self.stdout.write(
                f"--- 校验 --- ok={c.ok} 引用覆盖={c.citation_coverage:.0%} "
                f"refs={c.refs} 未核实数值={c.unverified_numbers}"
            )
            for issue in c.issues:
                self.stdout.write(f"  ! {issue.code}: {issue.detail}")
        for notice in answer.notices:
            self.stdout.write(f"  提示：{notice}")
        self.stdout.write(
            f"耗时 {answer.latency_ms}ms  trace={answer.trace_id}  meta={answer.meta}"
        )

    def _stream(self, question: str, opts) -> None:
        async def _consume() -> None:
            async for event in qa.answer_stream(
                question, audience=opts["audience"], doc_types=opts["doc_type"]
            ):
                if event.type == "stage":
                    self.stdout.write(f"[{event.stage}]")
                elif event.type == "delta":
                    self.stdout.write(event.text, ending="")
                elif event.type == "error":
                    self.stdout.write(f"\n!! {event.detail}")
                elif event.type == "final" and event.answer is not None:
                    a = event.answer
                    self.stdout.write(
                        f"\n--- 结束 --- 可答={a.answerable} 耗时={a.latency_ms}ms "
                        f"引用={[c.ref for c in a.citations]}"
                    )

        run(_consume())
