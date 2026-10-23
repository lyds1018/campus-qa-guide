"""按扩展名分发解析器。新增格式只需在这里登记。"""

from __future__ import annotations

from pathlib import Path

from apps.knowledge.parsing.base import ParsedDoc
from apps.knowledge.parsing.pdf import parse_pdf
from apps.knowledge.parsing.text import parse_html, parse_markdown, parse_text

PARSERS = {
    ".pdf": parse_pdf,
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".txt": parse_text,
    ".html": parse_html,
    ".htm": parse_html,
}

SUPPORTED_SUFFIXES = tuple(PARSERS)


class UnsupportedFormat(Exception):
    pass


def parse_bytes(data: bytes, suffix: str) -> ParsedDoc:
    parser = PARSERS.get(suffix.lower())
    if parser is None:
        raise UnsupportedFormat(f"不支持的格式：{suffix}")
    return parser(data)


def parse_path(path: Path | str) -> ParsedDoc:
    p = Path(path)
    return parse_bytes(p.read_bytes(), p.suffix)


__all__ = [
    "SUPPORTED_SUFFIXES",
    "UnsupportedFormat",
    "parse_bytes",
    "parse_path",
]
