"""PDF 解析：pymupdf 逐页抽文本，按字号识别标题行。

标题判定：行长短于 40 字、不以句末标点收尾，且字号明显大于正文字号。
不做版面还原，只求正文与标题层级可用。
"""

from __future__ import annotations

import re
import statistics

import fitz

from apps.knowledge.parsing.base import Block, Page, ParsedDoc

HEADING_MAX_LEN = 40
SENT_END = "。！？；，、,.;:"
# CJK 字体渲染常把数字拆成单字符加空格（"1 0 元"），提取后合并
NUM_GAP = re.compile(r"(?<=\d) (?=[\d.．])")


def _clean(text: str) -> str:
    return NUM_GAP.sub("", text)


def _body_size(doc: fitz.Document) -> float:
    sizes: list[float] = []
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        sizes.append(round(span.get("size", 0), 1))
    return statistics.median(sizes) if sizes else 10.0


def _is_heading(text: str, size: float, body: float, bold: bool) -> tuple[bool, int]:
    if len(text) > HEADING_MAX_LEN or text[-1] in SENT_END:
        return False, 0
    if size >= body * 1.4:
        return True, 1
    if size >= body * 1.15 or (bold and size >= body):
        return True, 2
    return False, 0


def parse_pdf(data: bytes) -> ParsedDoc:
    doc = fitz.open(stream=data, filetype="pdf")
    body = _body_size(doc)
    pages: list[Page] = []
    try:
        for page in doc:
            blocks: list[Block] = []
            for raw in page.get_text("dict").get("blocks", []):
                lines: list[str] = []
                level = 0
                max_size = 0.0
                bold = False
                for line in raw.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    lines.append("".join(s["text"] for s in spans))
                    for span in spans:
                        max_size = max(max_size, span.get("size", 0))
                        bold = bold or bool(span.get("flags", 0) & 2**4)
                text = _clean("\n".join(lines)).strip()
                if not text:
                    continue
                is_heading, level = _is_heading(text, max_size, body, bold)
                blocks.append(Block(text=text, level=level if is_heading else 0))
            pages.append(
                Page(no=page.number + 1, text=_clean(page.get_text("text")), blocks=blocks)
            )
    finally:
        doc.close()

    return ParsedDoc(pages=pages, parser="pymupdf")
