"""切分与分词：不依赖数据库与外部服务。"""

from apps.knowledge.chunking import build_chunks, tokenize
from apps.knowledge.parsing.base import Block, Page, ParsedDoc


def make_doc(*blocks: tuple[str, int]) -> ParsedDoc:
    page = Page(
        no=1,
        text="\n".join(t for t, _ in blocks),
        blocks=[Block(text=t, level=lv) for t, lv in blocks],
    )
    return ParsedDoc(pages=[page], parser="test")


def test_chunk_size_and_ordinal():
    body = "办理学生证补办需要携带身份证原件。" * 60
    doc = make_doc(("一、办理流程", 1), (body, 0))
    chunks = build_chunks(doc, size=500, overlap=80, min_len=120)

    assert chunks, "至少产出一个块"
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert 120 <= len(c["content"]) <= 800, len(c["content"])
        assert c["meta"]["char_len"] == len(c["content"])


def test_section_path_tracked():
    # 两段各约 440 字，必然切成两块，第二块应带"二、所需材料"
    p1 = "办理学生证需要到教务处窗口提交材料。" * 23
    p2 = "身份证原件及复印件各一份请提前准备。" * 23
    doc = make_doc(("一、办理流程", 1), (p1, 0), ("二、所需材料", 1), (p2, 0))
    chunks = build_chunks(doc, size=500, overlap=80, min_len=120)

    assert len(chunks) >= 2, [len(c["content"]) for c in chunks]
    paths = [c["meta"]["section_path"] for c in chunks]
    assert all(p for p in paths), "标题存在时 section_path 不应为空"
    assert any(p[-1] == "二、所需材料" for p in paths), paths


def test_no_empty_chunk():
    doc = make_doc(("标题", 1), ("   ", 0), ("正文内容。" * 30, 0))
    chunks = build_chunks(doc, size=500, overlap=80, min_len=120)
    assert all(c["content"].strip() for c in chunks)


def test_tokenize_returns_spaced_tokens():
    text = tokenize("学生证补办需要教务处审核")
    assert " " in text
    assert "学生证" in text.split(" ")
    assert "\n" not in text
