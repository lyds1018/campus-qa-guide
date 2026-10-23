"""本地开发配置：DEBUG、CORS 放开、SQL 打印。"""

from config.env import env
from config.settings.base import *  # noqa: F403
from config.settings.base import LOGGING

DEBUG = True

# 开发期前端走 Vite 代理，直连场景也放开
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in env("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

# 本地打印每条 SQL，便于排查 ORM 问题
# 合并而非覆盖：base 里已把 httpx / httpcore 压到 WARNING，直接赋值会把它抹掉
LOGGING["loggers"] = {
    **LOGGING.get("loggers", {}),
    "django.db.backends": {
        "handlers": ["console"],
        "level": "DEBUG",
        "propagate": False,
    },
}
