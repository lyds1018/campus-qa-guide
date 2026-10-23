"""与部署环境无关的共性配置。dev / prod 只覆盖差异项。"""

from pathlib import Path

from config.env import BASE_DIR, env

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "ninja",
    "apps.common",
    "apps.knowledge",
    "apps.gateway",
    "apps.qa",
    "apps.orchestrator",
    "apps.access",
    "apps.ops",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # 必须在 CommonMiddleware 之前
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # 接入层（P5）：追踪在最外，审计在鉴权外，鉴权贴近视图
    "apps.access.middleware.TraceIdMiddleware",
    "apps.access.middleware.AuditMiddleware",
    "apps.access.middleware.AccessMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
USE_I18N = True
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"

STATIC_URL = "static/"
STATIC_ROOT = Path(BASE_DIR) / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 应用配置
APP_VERSION = env("APP_VERSION", "0.1.0")
MINIO_ENDPOINT = env("MINIO_ENDPOINT")
MINIO_BUCKET = env("MINIO_BUCKET")
MINIO_ACCESS_KEY = env("MINIO_ROOT_USER")
MINIO_SECRET_KEY = env("MINIO_ROOT_PASSWORD")

# 知识入库（P1）
EMBEDDING_DIM = int(env("EMBEDDING_DIM", "1024"))
CHUNK_SIZE = int(env("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(env("CHUNK_OVERLAP", "80"))
INGEST_QUEUE = env("INGEST_QUEUE", "queue:ingest")
WORKER_STALE_MINUTES = int(env("WORKER_STALE_MINUTES", "30"))


# 模型网关（P2）。槽位配置允许空缺：embedding / rerank 未配时相关调用抛 NotConfigured。
def _gw(key: str, default: str = "") -> str:
    return env(key, default, required=False) or default


GW_CHAT_MAIN_BASE_URL = _gw("GW_CHAT_MAIN_BASE_URL")
GW_CHAT_MAIN_API_KEY = _gw("GW_CHAT_MAIN_API_KEY")
GW_CHAT_MAIN_MODEL = _gw("GW_CHAT_MAIN_MODEL", "deepseek-chat")

GW_CHAT_FALLBACK_BASE_URL = _gw("GW_CHAT_FALLBACK_BASE_URL")
GW_CHAT_FALLBACK_API_KEY = _gw("GW_CHAT_FALLBACK_API_KEY")
GW_CHAT_FALLBACK_MODEL = _gw("GW_CHAT_FALLBACK_MODEL", "qwen-plus")

GW_CHAT_AUX_BASE_URL = _gw("GW_CHAT_AUX_BASE_URL")
GW_CHAT_AUX_API_KEY = _gw("GW_CHAT_AUX_API_KEY")
GW_CHAT_AUX_MODEL = _gw("GW_CHAT_AUX_MODEL", "qwen-flash")

GW_EMBED_BASE_URL = _gw("GW_EMBED_BASE_URL")
GW_EMBED_API_KEY = _gw("GW_EMBED_API_KEY")
GW_EMBED_MODEL = _gw("GW_EMBED_MODEL", "BAAI/bge-m3")
GW_EMBED_DOC_PREFIX = _gw("GW_EMBED_DOC_PREFIX")
GW_EMBED_QUERY_PREFIX = _gw("GW_EMBED_QUERY_PREFIX")

GW_RERANK_BASE_URL = _gw("GW_RERANK_BASE_URL")
GW_RERANK_API_KEY = _gw("GW_RERANK_API_KEY")
GW_RERANK_MODEL = _gw("GW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

GW_RETRY_MAX = int(_gw("GW_RETRY_MAX", "3"))
GW_RETRY_INITIAL = float(_gw("GW_RETRY_INITIAL", "0.5"))

GW_TIMEOUT_CONNECT = float(_gw("GW_TIMEOUT_CONNECT", "3"))
GW_TIMEOUT_CHAT = float(_gw("GW_TIMEOUT_CHAT", "60"))
GW_TIMEOUT_FIRST_TOKEN = float(_gw("GW_TIMEOUT_FIRST_TOKEN", "20"))
GW_TIMEOUT_STREAM = float(_gw("GW_TIMEOUT_STREAM", "120"))
GW_TIMEOUT_EMBED = float(_gw("GW_TIMEOUT_EMBED", "30"))
GW_TIMEOUT_RERANK = float(_gw("GW_TIMEOUT_RERANK", "20"))

GW_BREAKER_THRESHOLD = int(_gw("GW_BREAKER_THRESHOLD", "5"))
GW_BREAKER_WINDOW = int(_gw("GW_BREAKER_WINDOW", "60"))
GW_BREAKER_COOLDOWN = int(_gw("GW_BREAKER_COOLDOWN", "60"))
GW_BREAKER_RECOVER = int(_gw("GW_BREAKER_RECOVER", "2"))

GW_MAX_CONCURRENCY = int(_gw("GW_MAX_CONCURRENCY", "8"))

GW_CACHE_ENABLED = _gw("GW_CACHE_ENABLED", "true").lower() == "true"
GW_CACHE_TTL_CHAT = int(_gw("GW_CACHE_TTL_CHAT", "86400"))
GW_CACHE_TTL_EMBED = int(_gw("GW_CACHE_TTL_EMBED", "2592000"))
GW_CACHE_TTL_RERANK = int(_gw("GW_CACHE_TTL_RERANK", "604800"))
GW_CACHE_TTL_DEGRADED = int(_gw("GW_CACHE_TTL_DEGRADED", "600"))
GW_KB_FINGERPRINT_TTL = int(_gw("GW_KB_FINGERPRINT_TTL", "60"))

GW_DAILY_BUDGET_CNY = float(_gw("GW_DAILY_BUDGET_CNY", "20"))
GW_BUDGET_HARD_STOP = _gw("GW_BUDGET_HARD_STOP", "false").lower() == "true"

GW_FAULT_INJECTION = _gw("GW_FAULT_INJECTION", "false").lower() == "true"


# 智能能力（P3）：召回规模、融合与重排门槛、生成与校验口径。
def _qa_int(key: str, default: int) -> int:
    return int(_gw(key, str(default)))


def _qa_float(key: str, default: float) -> float:
    return float(_gw(key, str(default)))


QA_TOP_K_VECTOR = _qa_int("QA_TOP_K_VECTOR", 20)
QA_TOP_K_FTS = _qa_int("QA_TOP_K_FTS", 20)
QA_FUSE_KEEP = _qa_int("QA_FUSE_KEEP", 25)
QA_EVIDENCE_TOP = _qa_int("QA_EVIDENCE_TOP", 6)
QA_RRF_K = _qa_int("QA_RRF_K", 60)
QA_MIN_RERANK_SCORE = _qa_float("QA_MIN_RERANK_SCORE", 0.35)
QA_MIN_VECTOR_SIM = _qa_float("QA_MIN_VECTOR_SIM", 0.58)
QA_MIN_FTS_OVERLAP = _qa_int("QA_MIN_FTS_OVERLAP", 2)
QA_MAX_EVIDENCE_CHARS = _qa_int("QA_MAX_EVIDENCE_CHARS", 6000)
QA_ANSWER_MAX_TOKENS = _qa_int("QA_ANSWER_MAX_TOKENS", 900)
QA_ANSWER_TEMPERATURE = _qa_float("QA_ANSWER_TEMPERATURE", 0.2)
QA_HISTORY_TURNS = _qa_int("QA_HISTORY_TURNS", 3)
QA_MAX_QUESTION_CHARS = _qa_int("QA_MAX_QUESTION_CHARS", 200)
QA_MIN_CITATION_COVERAGE = _qa_float("QA_MIN_CITATION_COVERAGE", 0.6)
QA_REPAIR_MAX = _qa_int("QA_REPAIR_MAX", 1)


# 会话与编排（P4）
def _orc_int(key: str, default: int) -> int:
    return int(_gw(key, str(default)))


def _orc_float(key: str, default: float) -> float:
    return float(_gw(key, str(default)))


ORC_SESSION_TTL = _orc_int("ORC_SESSION_TTL", 1800)      # Redis 上下文窗口存活秒数
ORC_HISTORY_TURNS = _orc_int("ORC_HISTORY_TURNS", 6)     # 进指代还原的历史轮数
ORC_FANOUT_MAX = _orc_int("ORC_FANOUT_MAX", 3)           # 一轮最多拆几个子问题
ORC_SEGMENT_TIMEOUT = _orc_float("ORC_SEGMENT_TIMEOUT", 25.0)   # 单段总超时（秒）
ORC_HEARTBEAT = _orc_float("ORC_HEARTBEAT", 15.0)        # SSE 心跳间隔（秒）


# 接入层（P5）。模拟身份两枚演示 token，换真登录时只改 apps/access/identity.py
ACCESS_STUDENT_TOKEN = _gw("ACCESS_STUDENT_TOKEN", "student-demo")
ACCESS_ADMIN_TOKEN = _gw("ACCESS_ADMIN_TOKEN", "admin-demo")
ACCESS_RATE_CHAT = _qa_int("ACCESS_RATE_CHAT", 20)       # 每分钟问答次数
ACCESS_RATE_WRITE = _qa_int("ACCESS_RATE_WRITE", 60)     # 每分钟写操作
ACCESS_RATE_READ = _qa_int("ACCESS_RATE_READ", 120)      # 每分钟读操作
ACCESS_AUDIT_ENABLED = _gw("ACCESS_AUDIT_ENABLED", "true").lower() == "true"


# 知识运营（P6）：上传先落到本地暂存区，再由 P1 的 worker 解析入库
OPS_UPLOAD_DIR = _gw("OPS_UPLOAD_DIR", str(Path(BASE_DIR) / "var" / "uploads"))
OPS_UPLOAD_MAX_MB = _qa_int("OPS_UPLOAD_MAX_MB", 20)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    # httpx 每次请求打一条 INFO，会把命令输出和 uvicorn 日志冲掉
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
