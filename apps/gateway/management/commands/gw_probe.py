"""三类任务连通性自检 + 熔断状态。

逐个槽位直调适配器（不经降级链、绕开缓存），
所以它验证的是"这个槽位配的对不对、通不通"，降级行为由 pytest 覆盖。
"""

from __future__ import annotations

import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.gateway import breaker, meter
from apps.gateway.base import (
    ChatMessage,
    ChatParams,
    GatewayError,
    NotConfigured,
    UpstreamTimeout,
)
from apps.gateway.router import (
    ALL_SLOTS,
    aux_adapter,
    embed_adapter,
    fallback_adapter,
    main_adapter,
    rerank_adapter,
)
from apps.gateway.sync import run

PROBE_TEXT = "连通性自检，只回复 ok"


class Command(BaseCommand):
    help = "探活 chat / embedding / rerank 三类任务，并打印熔断状态"

    def add_arguments(self, parser):
        parser.add_argument(
            "--task",
            default="all",
            choices=["all", "chat", "embedding", "rerank"],
            help="只探某一类任务",
        )

    def handle(self, *args, **options):
        rows = run(self._probe(options["task"]))
        self.stdout.write("")
        self.stdout.write(f"{'槽位':<10}{'任务':<12}{'结果':<8}{'延迟':<9}备注")
        self.stdout.write("-" * 76)
        for slot, task, verdict, latency, note in rows:
            self.stdout.write(f"{slot:<10}{task:<12}{verdict:<8}{latency:<9}{note}")

        self.stdout.write("")
        self.stdout.write("熔断状态：")
        for slot, info in breaker.snapshot(ALL_SLOTS).items():
            self.stdout.write(f"  {slot:<10}{info['state']:<11}failures={info['failures']}")

        flushed = meter.flush_sync()
        self.stdout.write(
            f"台账落库 {flushed} 条，今日累计花费 ¥{meter.spent_today():.4f}"
            f" / 预算 ¥{settings.GW_DAILY_BUDGET_CNY:.0f}"
        )

    async def _probe(self, task: str) -> list[tuple[str, str, str, str, str]]:
        rows: list[tuple[str, str, str, str, str]] = []

        if task in ("all", "chat"):
            rows.append(
                await self._timed(
                    "main",
                    "chat",
                    lambda: self._chat(main_adapter),
                    settings.GW_CHAT_MAIN_MODEL,
                )
            )
            if settings.GW_CHAT_FALLBACK_BASE_URL and settings.GW_CHAT_FALLBACK_API_KEY:
                rows.append(
                    await self._timed(
                        "fallback",
                        "chat",
                        lambda: self._chat(fallback_adapter),
                        settings.GW_CHAT_FALLBACK_MODEL,
                    )
                )
            else:
                rows.append(("fallback", "chat", "skip", "-", "未配置备供应商"))

            if settings.GW_CHAT_AUX_BASE_URL and settings.GW_CHAT_AUX_API_KEY:
                rows.append(
                    await self._timed(
                        "aux",
                        "chat",
                        lambda: self._chat(aux_adapter),
                        settings.GW_CHAT_AUX_MODEL,
                    )
                )
            else:
                rows.append(("aux", "chat", "skip", "-", "未配置，复用 main"))

        if task in ("all", "embedding"):
            rows.append(
                await self._timed("embed", "embedding", self._embed, settings.GW_EMBED_MODEL)
            )

        if task in ("all", "rerank"):
            adapter = rerank_adapter()
            if adapter is None:
                rows.append(("rerank", "rerank", "skip", "-", "未配置，按不重排降级"))
            else:
                rows.append(
                    await self._timed(
                        "rerank",
                        "rerank",
                        lambda: adapter.rerank(
                            "学生证丢了怎么办", ["去教务处补办", "食堂开饭时间"], 2
                        ),
                        settings.GW_RERANK_MODEL,
                    )
                )
        return rows

    async def _chat(self, factory):
        adapter = factory()
        return await adapter.chat(
            [ChatMessage("user", PROBE_TEXT)], ChatParams(temperature=0.9, max_tokens=8)
        )

    async def _embed(self):
        adapter = embed_adapter()
        return await adapter.embed([PROBE_TEXT], kind="query")

    async def _timed(self, slot: str, task: str, factory, model: str):
        started = time.monotonic()
        try:
            result = await factory()
        except NotConfigured as exc:
            return (slot, task, "skip", "-", str(exc))
        except GatewayError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            meter.record(
                trace_id=str(uuid.uuid4()),
                task=task,
                provider=slot,
                model=model,
                status="timeout" if isinstance(exc, UpstreamTimeout) else "failed",
                latency_ms=elapsed,
                error=exc,
                meta={"probe": True},
            )
            return (slot, task, "fail", f"{elapsed}ms", f"{type(exc).__name__}: {str(exc)[:56]}")

        elapsed = int((time.monotonic() - started) * 1000)
        prompt_tokens = getattr(result, "prompt_tokens", 0)
        completion_tokens = getattr(result, "completion_tokens", 0)
        used_model = getattr(result, "model", "") or model
        meter.record(
            trace_id=str(uuid.uuid4()),
            task=task,
            provider=slot,
            model=used_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=elapsed,
            meta={"probe": True},
        )

        if isinstance(result, list):
            note = f"{len(result)} 条候选" if result else "空结果（不重排）"
        else:
            note = used_model
        return (slot, task, "ok", f"{elapsed}ms", note)
