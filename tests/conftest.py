"""测试基础设施。

Django 建测试库时不会继承原库的扩展，健康检查要求 vector 存在，这里在测试库建好后补建。
P1 的 migration 会自带 CREATE EXTENSION，届时本 fixture 可删。
"""

import pytest
from django.db import connection

EXTENSIONS = ("vector", "pg_trgm")


@pytest.fixture(scope="session", autouse=True)
def ensure_test_db_extensions(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), connection.cursor() as cur:
        for ext in EXTENSIONS:
            cur.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
