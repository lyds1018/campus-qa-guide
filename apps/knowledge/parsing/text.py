"""纯文本类解析：Markdown、TXT、HTML。

这三种格式没有分页概念，统一输出单页（no=1），只保留块与标题层级。
不引入 markdown / beautifulsoup 依赖，标准库够用。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from apps.knowledge.parsing.base import Block, Page, ParsedDoc

MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3}
BLOCK_TAGS = {"p", "div", "li", "td", "tr", "br", "section", "article"}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _flush(blocks: list[Block], buf: list[str]) -> None:
    text = "\n".join(buf).strip()
    if text:
        blocks.append(Block(text=text, level=0))
    buf.clear()


def parse_markdown(data: bytes) -> ParsedDoc:
    blocks: list[Block] = []
    buf: list[str] = []
    for line in _decode(data).splitlines():
        m = MD_HEADING.match(line)
        if m:
            _flush(blocks, buf)
            blocks.append(Block(text=m.group(2).strip(), level=min(len(m.group(1)), 3)))
            continue
        if not line.strip():
            _flush(blocks, buf)
            continue
        buf.append(line.strip())
    _flush(blocks, buf)
    text = "\n".join(b.text for b in blocks)
    return ParsedDoc(pages=[Page(no=1, text=text, blocks=blocks)], parser="markdown")


def parse_text(data: bytes) -> ParsedDoc:
    blocks: list[Block] = []
    buf: list[str] = []
    for line in _decode(data).splitlines():
        if not line.strip():
            _flush(blocks, buf)
            continue
        buf.append(line.strip())
    _flush(blocks, buf)
    text = "\n".join(b.text for b in blocks)
    return ParsedDoc(pages=[Page(no=1, text=text, blocks=blocks)], parser="text")


class _HTMLExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._buf: list[str] = []
        self._level = 0
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
            return
        if tag in HEADING_TAGS:
            self._flush()
            self._level = HEADING_TAGS[tag]
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
            return
        if tag in HEADING_TAGS or tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self._buf.append(text)

    def _flush(self) -> None:
        text = " ".join(self._buf).strip()
        if text:
            self.blocks.append(Block(text=text, level=self._level))
        self._buf.clear()
        self._level = 0

    def close(self) -> None:
        super().close()
        self._flush()


def parse_html(data: bytes) -> ParsedDoc:
    extractor = _HTMLExtractor()
    extractor.feed(_decode(data))
    extractor.close()
    blocks = extractor.blocks
    text = "\n".join(b.text for b in blocks)
    return ParsedDoc(pages=[Page(no=1, text=text, blocks=blocks)], parser="html")
