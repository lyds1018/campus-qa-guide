"""模拟身份。

不做真登录：毕设不接学校统一身份认证，用两枚演示 token 区分"学生"与"管理员"。
但**取身份这件事必须走同一个入口**——否则后面换真登录时，每个视图都要改。

token 走 `X-Demo-Token` 请求头；P5 前端登录页只是把 token 存进 localStorage。
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.http import HttpRequest


@dataclass(frozen=True)
class Identity:
    user_key: str
    audience: str
    role: str          # student / admin
    token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def resolve(request: HttpRequest) -> Identity | None:
    token = (request.headers.get("X-Demo-Token") or "").strip()
    if not token:
        return None
    # 演示 token → 身份。生产换成统一身份认证的会话校验，调用点不变。
    tokens = {
        settings.ACCESS_STUDENT_TOKEN: Identity(
            user_key="demo-student", audience="undergrad", role="student", token=token
        ),
        settings.ACCESS_ADMIN_TOKEN: Identity(
            user_key="demo-admin", audience="", role="admin", token=token
        ),
    }
    return tokens.get(token)
