"""回归打分、命令落库、黄金集沉淀与降级演练。"""

import asyncio
import json
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.eval import drill, runner
from apps.eval.models import EvalRun, Feedback
from apps.qa.pipeline import qa
from apps.qa.types import Answer, Citation, Evidence


def make_answer(
    question: str,
    *,
    text: str = "到教务处学籍科办理[1]。",
    title: str = "学生证补办",
    answerable: bool = True,
    degraded: bool = False,
) -> Answer:
    evidence = Evidence(
        ref=1,
        chunk_id=1,
        document_id=1,
        title=title,
        doc_type="guide",
        dept="教务处",
        section="四、办理流程",
        page=1,
        content="到教务处学籍科提交申请。",
        score=0.9,
        fusion=1.0,
        source="both",
    )
    citations = (
        [Citation(ref=1, chunk_id=1, document_id=1, title=title, section="四、办理流程")]
        if answerable
        else []
    )
    return Answer(
        question=question,
        intent="matter",
        answerable=answerable,
        text=text,
        citations=citations,
        evidence=[evidence] if answerable else [],
        degraded=degraded,
        latency_ms=12,
    )


def test_check_marks_doc_hit_and_missing():
    row = {
        "q": "学生证丢了怎么补办",
        "expect": "answer",
        "doc": "学生证",
        "must": ["学籍科", "不存在"],
    }
    sample = runner._check(row, make_answer(row["q"]))

    assert sample.doc_hit is True
    assert sample.missing == ["不存在"]
    assert sample.answerable_ok is True
    assert sample.citations == 1


def test_check_refusal_counts_as_missing_keywords():
    """拒答里出现关键词不算答对：必须按未命中计。"""
    row = {"q": "游泳馆几点开门", "expect": "refuse", "must": ["游泳馆"]}
    answer = make_answer(
        row["q"], text="没有找到依据，请联系体育馆确认游泳馆信息", answerable=False
    )
    sample = runner._check(row, answer)

    assert sample.answerable_ok is True
    assert sample.missing == ["游泳馆"]


def test_summarize_rates_and_zero_denominators():
    rows = [
        {"q": "a", "expect": "answer", "doc": "学生证", "must": []},
        {"q": "b", "expect": "refuse"},
    ]
    samples = [
        runner._check(rows[0], make_answer("a")),
        runner._check(rows[1], make_answer("b", answerable=False)),
    ]
    summary = runner.summarize(samples)

    assert summary["samples"] == 2
    assert summary["answer_ok"] == 1.0
    assert summary["refuse_ok"] == 1.0
    assert summary["n_refuse"] == 1
    # 分母为 0 的指标不参与达标判定（小样本试跑不该报红）
    assert "refuse_ok" not in runner.targets_of({**summary, "n_refuse": 0})


@pytest.mark.django_db(transaction=True)
def test_run_samples_uses_pipeline(monkeypatch):
    """跑批走的是 P3 的 answer()，指标要能直接从 Answer 上读出来。"""
    calls: list[str] = []

    async def fake(question, **kwargs):
        calls.append(question)
        return make_answer(question, degraded=True)

    monkeypatch.setattr(qa, "answer", fake)
    rows = [
        {"q": "学生证丢了怎么补办", "expect": "answer", "doc": "学生证补办", "must": ["学籍科"]}
    ]
    samples = asyncio.run(runner.run_samples(rows))

    assert calls == ["学生证丢了怎么补办"]
    assert samples[0].doc_hit is True
    assert samples[0].degraded is True
    assert samples[0].latency_ms >= 12


@pytest.mark.django_db(transaction=True)
def test_p7_eval_command_persists_run(monkeypatch, tmp_path, settings):
    settings.EVAL_REPORT_DIR = str(tmp_path / "reports")

    async def fake_run(rows, *, audience="unknown", progress=None):
        out = []
        for index, row in enumerate(rows, 1):
            sample = runner._check(row, make_answer(row["q"]))
            out.append(sample)
            if progress:
                progress(index, len(rows), sample)
        return out

    monkeypatch.setattr(runner, "run_samples", fake_run)
    monkeypatch.setattr(runner, "cost_since", lambda started_at: Decimal("0.0100"))

    call_command("p7_eval", "--limit", "3", "--label", "单测", verbosity=0)

    record = EvalRun.objects.latest("id")
    assert record.kind == EvalRun.Kind.EVAL
    assert record.samples == 3
    assert record.metrics["answer_ok"] == 1.0
    assert record.cost == Decimal("0.010000")

    reports = list((tmp_path / "reports").glob("*.md"))
    assert reports and "评测报告" in reports[0].read_text(encoding="utf-8")


@pytest.mark.django_db
def test_golden_command_dry_run_then_apply(monkeypatch, tmp_path):
    target = tmp_path / "golden.jsonl"
    target.write_text('{"q": "已存在的问题", "expect": "answer"}\n', encoding="utf-8")
    monkeypatch.setattr(runner, "GOLDEN", target)
    Feedback.objects.create(
        user_key="u", question="图书馆研讨间怎么预约", rating="down", reason="off_topic"
    )
    Feedback.objects.create(user_key="u", question="已存在的问题", rating="down")

    call_command("p7_golden", verbosity=0)
    assert "图书馆研讨间怎么预约" not in target.read_text(encoding="utf-8")   # 默认不写

    call_command("p7_golden", "--apply", verbosity=0)
    lines = [line for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2                                    # 原有 1 条 + 新增 1 条（去重生效）
    added = json.loads(lines[-1])
    assert added["q"] == "图书馆研讨间怎么预约"
    assert added["expect"] == "refuse"                        # 答非所问 → 应拒答
    assert Feedback.objects.get(question="图书馆研讨间怎么预约").reviewed is True


@pytest.mark.django_db(transaction=True)
def test_drill_restores_switches_and_reports(monkeypatch, settings):
    """演练必须关缓存、开注入，跑完两个开关都要还原，否则线上会被"演习"污染。"""

    async def fake_run(rows, *, audience="unknown", progress=None):
        return [runner._check(row, make_answer(row["q"])) for row in rows]

    applied: list[tuple] = []

    monkeypatch.setattr(drill.runner, "run_samples", fake_run)
    monkeypatch.setattr(drill, "_apply", lambda faults: applied.append(faults))
    monkeypatch.setattr(drill, "_clear", lambda: None)

    settings.GW_FAULT_INJECTION = False
    settings.GW_CACHE_ENABLED = True

    rows = [{"q": "学生证丢了怎么补办", "expect": "answer", "doc": "学生证"}]
    out = asyncio.run(drill.run_drill(rows, limit=1))

    assert out["cache"] == "off"
    assert len(out["scenarios"]) == len(drill.SCENARIOS)
    assert all(item["samples"] == 1 for item in out["scenarios"])
    assert applied and any(item for item in applied)          # 至少注入过一个场景
    assert settings.GW_FAULT_INJECTION is False
    assert settings.GW_CACHE_ENABLED is True


def test_drill_matrix_shape():
    result = {
        "limit": 1,
        "cache": "off",
        "scenarios": [
            {
                "scenario": "baseline",
                "desc": "不注入故障",
                "samples": 3,
                "answered": 3,
                "refused": 0,
                "wrong": 0,
                "bad": 0,
                "fallback": 0,
                "degraded": 0,
                "with_citation": 3,
                "latency_p50_ms": 100,
                "elapsed_ms": 300,
            }
        ],
    }
    rows = drill.matrix_rows(result)
    assert rows[0][0] == "场景"
    assert rows[1][0] == "baseline"
    assert rows[1][-1] == "100ms"
