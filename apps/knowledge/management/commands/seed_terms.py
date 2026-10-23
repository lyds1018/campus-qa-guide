"""种子词典：校内简称、别名、同义词，供 M5 做查询改写。

默认读 apps/knowledge/fixtures/terms.csv，也可传自定义 CSV。
CSV 列：term,canonical,term_type,weight
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.knowledge.repositories import WriteRepository

DEFAULT_CSV = Path(settings.BASE_DIR) / "apps" / "knowledge" / "fixtures" / "terms.csv"


class Command(BaseCommand):
    help = "导入种子词典（别名 / 简称 / 同义词）"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", nargs="?", default=str(DEFAULT_CSV))

    def handle(self, *args, **options):
        path = Path(options["csv_path"])
        if not path.is_file():
            raise CommandError(f"词典文件不存在：{path}")

        rows: list[dict] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                term = (row.get("term") or "").strip()
                canonical = (row.get("canonical") or "").strip()
                if not term or not canonical:
                    continue
                rows.append(
                    {
                        "term": term,
                        "canonical": canonical,
                        "term_type": (row.get("term_type") or "alias").strip(),
                        "weight": int(row.get("weight") or 1),
                    }
                )

        if not rows:
            raise CommandError("词典文件为空或列名不符（需要 term,canonical）")

        created = WriteRepository().upsert_terms(rows)
        self.stdout.write(
            self.style.SUCCESS(f"词典导入完成：{len(rows)} 条，新增 {created} 条")
        )
