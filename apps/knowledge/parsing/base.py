"""解析结果的统一数据结构。

所有解析器输出 ParsedDoc，切分只认这一个结构，不关心来源格式。
JSON 形状固定为 pages[{no, text, blocks[{text, level}]}]，落 parsed/ 后可回溯。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Block:
    text: str
    level: int = 0  # 0 正文，1/2/3 标题层级


@dataclass
class Page:
    no: int
    text: str
    blocks: list[Block] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "no": self.no,
            "text": self.text,
            "blocks": [{"text": b.text, "level": b.level} for b in self.blocks],
        }


@dataclass
class ParsedDoc:
    pages: list[Page]
    parser: str

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parser": self.parser,
            "page_count": self.page_count,
            "char_count": self.char_count,
            "pages": [p.to_dict() for p in self.pages],
        }

    def iter_blocks(self) -> Iterator[tuple[int, Block]]:
        """按阅读顺序展平为 (页码, Block)。"""
        for page in self.pages:
            for block in page.blocks:
                yield page.no, block


class Parser(Protocol):
    def __call__(self, data: bytes) -> ParsedDoc: ...
