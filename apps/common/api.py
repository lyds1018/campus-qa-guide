"""健康检查接口：P0 唯一的业务接口，也是后续各阶段的冒烟入口。"""

from django.conf import settings
from ninja import Router, Schema
from pydantic import ConfigDict

from apps.common.checks import check_db, check_redis, check_storage

router = Router(tags=["ops"])


class Check(Schema):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    ok: bool
    detail: str


class HealthOut(Schema):
    status: str
    checks: dict[str, Check]
    version: str


@router.get("", response={200: HealthOut, 503: HealthOut})
def health(request):
    checks = {"db": check_db(), "redis": check_redis(), "storage": check_storage()}
    ok = all(c.ok for c in checks.values())
    body = HealthOut(
        status="ok" if ok else "degraded",
        checks=checks,
        version=settings.APP_VERSION,
    )
    return (200 if ok else 503), body
