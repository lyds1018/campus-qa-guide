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
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # 必须在 CommonMiddleware 之前
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
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

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
