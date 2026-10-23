"""故障注入：给指定槽位挂一个 Redis 开关，网关命中后按模式模拟失败。

不改被调代码、不改供应商配置，随时开随时关。用完记得 --clear。
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.gateway import breaker
from apps.gateway.router import ALL_SLOTS

MODES = ("timeout", "error500", "ratelimit", "slow", "badjson")


class Command(BaseCommand):
    help = "给槽位注入故障（timeout / error500 / ratelimit / slow / badjson）"

    def add_arguments(self, parser):
        parser.add_argument("--provider", choices=ALL_SLOTS, help="槽位名")
        parser.add_argument("--mode", choices=MODES, help="故障模式")
        parser.add_argument("--ttl", type=int, default=120, help="持续秒数，默认 120")
        parser.add_argument("--clear", action="store_true", help="清掉该槽位的故障开关")
        parser.add_argument("--clear-all", action="store_true", help="清掉全部槽位")
        parser.add_argument(
            "--reset-breaker", action="store_true", help="把该槽位熔断状态重置为 closed"
        )
        parser.add_argument("--list", action="store_true", help="列出当前开关与熔断状态")

    def handle(self, *args, **options):
        slot = options["provider"]

        if options["clear_all"]:
            for name in ALL_SLOTS:
                cache.delete(f"gw:fault:{name}")
            self.stdout.write(self.style.SUCCESS("已清除全部故障开关"))
            return

        if options["reset_breaker"]:
            if not slot:
                raise CommandError("--reset-breaker 需要同时给 --provider")
            breaker.reset(slot)
            self.stdout.write(self.style.SUCCESS(f"{slot} 熔断状态已重置为 closed"))
            return

        if options["list"] or (not slot and not options["clear"]):
            self._list()
            return

        if not slot:
            raise CommandError("--provider 必填（main / fallback / aux / embed / rerank）")

        if options["clear"]:
            cache.delete(f"gw:fault:{slot}")
            self.stdout.write(self.style.SUCCESS(f"{slot} 故障开关已清除"))
            return

        if not options["mode"]:
            raise CommandError("--mode 必填（或用 --clear / --list）")

        if not settings.GW_FAULT_INJECTION:
            raise CommandError(
                "GW_FAULT_INJECTION=false，开关不会生效。"
                "先在 .env 改成 true 并重启 uvicorn / worker。"
            )

        cache.set(
            f"gw:fault:{slot}",
            {"mode": options["mode"], "until": time.time() + options["ttl"]},
            options["ttl"],
        )
        self.stdout.write(
            self.style.WARNING(
                f"{slot} 注入 {options['mode']}，持续 {options['ttl']}s。"
                "用完执行 --clear 或 --reset-breaker。"
            )
        )

    def _list(self) -> None:
        self.stdout.write(f"故障注入总开关 GW_FAULT_INJECTION = {settings.GW_FAULT_INJECTION}")
        self.stdout.write("")
        self.stdout.write(f"{'槽位':<10}{'故障':<12}{'熔断':<12}failures")
        self.stdout.write("-" * 46)
        snap = breaker.snapshot(ALL_SLOTS)
        for slot in ALL_SLOTS:
            spec = cache.get(f"gw:fault:{slot}") or {}
            info = snap[slot]
            self.stdout.write(
                f"{slot:<10}{spec.get('mode', '-'):<12}{info['state']:<12}{info['failures']}"
            )
