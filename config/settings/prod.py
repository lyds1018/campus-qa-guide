"""部署配置：DEBUG 关闭，来源与主机走白名单。"""

from config.env import env
from config.settings.base import *  # noqa: F403

DEBUG = False

ALLOWED_HOSTS = [
    h.strip() for h in env("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()
]

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [o.strip() for o in env("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]

# 生产由 Nginx 终结 TLS，转发头可信
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
