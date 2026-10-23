"""离线批量评测：黄金集跑批，出四个指标。

它是 P7 批量回归的最小版本：数据格式（JSONL）、指标口径与 P7 一致，
P7 只往上加样本量与看板，不换字段。
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.gateway.sync import run
from apps.qa.pipeline import qa

DEFAULT_SET = Path(__file__).resolve().parents[2] / "fixtures" / "golden.jsonl"


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            rows.append(json.loads(line))
    return rows


class Command(BaseCommand):
    help = "用黄金集回归：命中率、拒答准确率、must 命中、引用覆盖率"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT_SET))
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--audience", default="unknown")
        parser.add_argument("--show-fail", action="store_true", help="打印未通过的样本")
        parser.add_argument("--json", action="store_true", help="输出 JSON，便于下游脚本消费")

    def handle(self, *args, **opts):
        rows = load_rows(Path(opts["file"]))
        if opts["limit"]:
            rows = rows[: opts["limit"]]

        results = run(self._run_all(rows, opts["audience"]))
        report = self._score(rows, results)

        if opts["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self._print(report, opts["show_fail"])

    async def _run_all(self, rows: list[dict], audience: str) -> list:
        out = []
        for row in rows:
            started = time.monotonic()
            answer = await qa.answer(row["q"], audience=audience)
            out.append((answer, int((time.monotonic() - started) * 1000)))
        return out

    def _score(self, rows: list[dict], results: list) -> dict:
        hits = must_ok = cite = verified = checked = 0
        answered = refused = 0
        wrong_refuse = wrong_answer = 0
        latencies: list[int] = []
        fails: list[dict] = []

        for row, (answer, latency) in zip(rows, results, strict=False):
            expect = row.get("expect", "answer")
            latencies.append(latency)
            ok_refused = (not answer.answerable) and expect == "refuse"
            ok_answered = answer.answerable and expect in ("answer", "smalltalk")
            if answer.answerable:
                answered += 1
            else:
                refused += 1
            if expect == "refuse" and not ok_refused:
                wrong_answer += 1
            if expect != "refuse" and not ok_answered:
                wrong_refuse += 1

            doc_hit = None
            if row.get("doc"):
                doc_hit = any(row["doc"] in e.title for e in answer.evidence[:3])
                hits += int(bool(doc_hit))
            missing = [m for m in row.get("must", []) if m not in answer.text]
            must_ok += int(not missing)
            if answer.checks:               # 寒暄与直接拒答不进这条分支，也不该进分母
                checked += 1
                cite += answer.checks.citation_coverage
                verified += int(answer.checks.ok)

            unverified = bool(answer.checks and not answer.checks.ok)
            if (
                (expect == "refuse") != (not answer.answerable)
                or missing
                or doc_hit is False
                or unverified
            ):
                fails.append(
                    {
                        "q": row["q"],
                        "expect": expect,
                        "answerable": answer.answerable,
                        "refusal_reason": answer.refusal_reason,
                        "doc_hit": doc_hit,
                        "missing": missing,
                        "issues": [i.code for i in answer.checks.blocking] if answer.checks else [],
                        "text": answer.text[:160],
                    }
                )

        n = len(rows) or 1
        refuse_rows = [r for r in rows if r.get("expect") == "refuse"]
        answer_rows = [r for r in rows if r.get("expect") != "refuse"]
        doc_rows = [r for r in rows if r.get("doc")]
        return {
            "samples": len(rows),
            "answer_ok": round(1 - wrong_refuse / (len(answer_rows) or 1), 3),
            "refuse_ok": round(1 - wrong_answer / (len(refuse_rows) or 1), 3),
            "hit_at_3": round(hits / (len(doc_rows) or 1), 3),
            "must_ok": round(must_ok / n, 3),
            "answered": answered,
            "refused": refused,
            "citation_rate": round(cite / (checked or 1), 3),
            "verified_rate": round(verified / (checked or 1), 3),
            "latency_p50_ms": int(statistics.median(latencies)) if latencies else 0,
            "latency_p95_ms": int(
                sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
            )
            if latencies
            else 0,
            "fails": fails,
        }

    def _print(self, report: dict, show_fail: bool) -> None:
        self.stdout.write(
            f"样本 {report['samples']}  可答 {report['answered']}  拒答 {report['refused']}"
        )
        self.stdout.write(
            f"hit@3 {report['hit_at_3']:.0%}  must {report['must_ok']:.0%}  "
            f"可答判对 {report['answer_ok']:.0%}  拒答判对 {report['refuse_ok']:.0%}"
        )
        self.stdout.write(
            f"引用覆盖 {report['citation_rate']:.0%}  校验通过 {report['verified_rate']:.0%}  "
            f"P50 {report['latency_p50_ms']}ms  P95 {report['latency_p95_ms']}ms"
        )
        if show_fail and report["fails"]:
            self.stdout.write("--- 未通过 ---")
            for f in report["fails"]:
                self.stdout.write(
                    f"✗ {f['q']}  expect={f['expect']} answerable={f['answerable']} "
                    f"doc={f['doc_hit']} missing={f['missing']} issues={f['issues']}"
                )
                self.stdout.write(f"   {f['text']}")
