"""降级演练：拿 P2 的故障注入当演习弹药，看系统在"半坏"状态下还能不能给可用结果。

五个场景，看四件事：还能不能作答、会不会变成明显的错误答案（应拒答却作答）、
延迟劣化多少、降级标记（`degraded`）有没有正确亮起。

只跑黄金集前 N 条：演练判的是"行为对不对"，不是"答对多少"，样本量大会变成烧钱。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from apps.eval import runner
from apps.gateway import breaker
from apps.gateway.router import ALL_SLOTS


@dataclass(frozen=True)
class Scenario:
    name: str
    desc: str
    faults: tuple[tuple[str, str], ...] = ()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("baseline", "不注入故障，作为对照"),
    Scenario("embed_down", "嵌入不可用，应退纯全文召回", (("embed", "error500"),)),
    Scenario("rerank_down", "重排不可用，应按融合分截断", (("rerank", "error500"),)),
    Scenario("main_timeout", "主模型超时，应降级到备用供应商", (("main", "timeout"),)),
    Scenario(
        "chat_all_down",
        "主备都不可用，应给原文出处或明确拒答",
        (("main", "timeout"), ("fallback", "error500")),
    ),
)


def _apply(faults: tuple[tuple[str, str], ...]) -> None:
    until = int(time.time()) + 300
    for slot, mode in faults:
        cache.set(f"gw:fault:{slot}", {"mode": mode, "until": until}, 300)


def _clear() -> None:
    for slot in ALL_SLOTS:
        cache.delete(f"gw:fault:{slot}")
        breaker.reset(slot)


async def run_drill(rows: list[dict], *, limit: int = 5, progress=None) -> dict:
    subset = rows[:limit]
    previous_fault = settings.GW_FAULT_INJECTION
    previous_cache = settings.GW_CACHE_ENABLED
    settings.GW_FAULT_INJECTION = True
    # 必须关缓存：命中 L1 时根本不发请求，注入的故障永远不触发，
    # 演练会得到"全部正常、47ms"的假象（第一次跑就踩到了）。
    settings.GW_CACHE_ENABLED = False
    out = []
    try:
        for scenario in SCENARIOS:
            _clear()
            _apply(scenario.faults)
            started = time.monotonic()
            samples = await runner.run_samples(subset)
            _clear()

            # 两类才算"演练失败"：该拒答却作答（错误自信），
            # 或该作答却没答也没给兜底出处（用户什么都没拿到）
            bad = [
                s
                for s in samples
                if (s.expect == "refuse" and s.answerable)
                or (s.expect != "refuse" and not s.answerable and not _fallback(s))
            ]
            out.append(
                {
                    "scenario": scenario.name,
                    "desc": scenario.desc,
                    "samples": len(samples),
                    "answered": sum(1 for s in samples if s.answerable),
                    "refused": sum(1 for s in samples if not s.answerable),
                    "bad": len(bad),
                    "fallback": sum(1 for s in samples if _fallback(s)),
                    "degraded": sum(1 for s in samples if s.degraded),
                    "with_citation": sum(1 for s in samples if s.citations > 0),
                    "latency_p50_ms": runner.median([s.latency_ms for s in samples]),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            )
            if progress is not None:
                progress(scenario, out[-1])
    finally:
        settings.GW_FAULT_INJECTION = previous_fault
        settings.GW_CACHE_ENABLED = previous_cache
        _clear()
    return {"limit": limit, "cache": "off", "scenarios": out}


def _fallback(sample) -> bool:
    """未作答但给了原文出处，算优雅降级（P3 的 ungrounded 路径）。"""
    return (not sample.answerable) and sample.refusal_reason == "ungrounded"


def matrix_rows(result: dict) -> list[list[str]]:
    rows = [["场景", "说明", "作答", "拒答", "兜底出处", "降级", "演练失败", "P50"]]
    for item in result["scenarios"]:
        rows.append(
            [
                item["scenario"],
                item["desc"],
                str(item["answered"]),
                str(item["refused"]),
                str(item["fallback"]),
                str(item["degraded"]),
                str(item["bad"]),
                f"{item['latency_p50_ms']}ms",
            ]
        )
    return rows


def markdown_report(result: dict, *, label: str, cost, duration_ms: int) -> str:
    """演练报告：矩阵 + 判定 + 口径，与基线报告同一目录、同一命名规则。"""
    env = runner.env_snapshot()
    scenarios = result["scenarios"]
    calls = sum(item["samples"] for item in scenarios)
    failed = [item for item in scenarios if item["bad"] > 0]

    lines = [
        f"# 降级演练 · {label}",
        "",
        f"- 生成时间：{env['at']}",
        f"- 语料：{env['documents']} 在版文档 / {env['chunks']} 块（已向量 {env['embedded']}）"
        f" / {env['matters']} 事项",
        f"- 模型：main `{env['main_model']}`、embed `{env['embed_model']}`、"
        f"rerank `{env['rerank_model']}`",
        f"- 样本：黄金集前 {result['limit']} 条 × {len(scenarios)} 场景，共 {calls} 次调用",
        "- 缓存：关闭（命中缓存就不发请求，注入的故障不会触发）",
        f"- 成本：¥{cost:.4f}，耗时 {duration_ms / 1000:.1f}s",
        "",
        "## 一、场景矩阵",
        "",
        "| 场景 | 注入说明 | 作答 | 拒答 | 兜底出处 | 降级标记 | 演练失败 | P50 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in scenarios:
        lines.append(
            f"| {item['scenario']} | {item['desc']} | {item['answered']}/{item['samples']} | "
            f"{item['refused']} | {item['fallback']} | {item['degraded']} | "
            f"{item['bad']} | {item['latency_p50_ms']}ms |"
        )

    lines += ["", "## 二、判定", ""]
    if not failed:
        lines.append(
            f"{len(scenarios)} 个场景全部通过：没有把该拒答的问题答成肯定结论，"
            "也没有出现既未作答又未给原文的情况。"
        )
    else:
        names = "、".join(item["scenario"] for item in failed)
        lines.append(f"{len(scenarios) - len(failed)}/{len(scenarios)} 通过，失败场景：{names}。")
        lines += ["", "| 场景 | 演练失败 | 注入说明 |", "| --- | --- | --- |"]
        for item in failed:
            lines.append(f"| {item['scenario']} | {item['bad']} | {item['desc']} |")

    lines += [
        "",
        "## 三、口径说明",
        "",
        "- 演练失败只算两类：该拒答却作答（错误自信），或该作答却没答且没给原文出处"
        "（用户什么都没拿到）。",
        "- 未作答但给出原文出处属于优雅降级，不计失败。",
        "- 延迟含重试与换槽等待，明显高于基线报告属预期。",
    ]
    return "\n".join(lines) + "\n"

