"""环境变量读取与必填校验。

工程不引入 python-dotenv / pydantic-settings：启动时解析一次工程根目录的 .env，
已存在的真实环境变量优先，不做兜底默认值（必填项缺失即抛错）。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class EnvError(RuntimeError):
    """必填环境变量缺失。"""


def load_env_file(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file()


def env(key: str, default: str | None = None, required: bool = True) -> str | None:
    """读取环境变量。required=True 且缺失时在进程启动阶段直接抛错。"""
    value = os.environ.get(key, default)
    if required and not value:
        raise EnvError(
            f"缺少必填环境变量 {key}。参考 .env.example 补齐后重试。"
        )
    return value
