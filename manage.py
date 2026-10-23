#!/usr/bin/env python
"""Django 管理命令入口。"""

import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "无法导入 Django，请确认已执行 uv sync 并激活虚拟环境。"
        ) from exc
    execute_from_command_line(sys.argv)
