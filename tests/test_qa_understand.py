"""M5 词表与意图规则：改写、分词、停用词、规则兜底。"""

import pytest

from apps.qa import lexicon
from apps.qa.types import Intent
from apps.qa.understand import rules_intent


@pytest.fixture
def fake_terms(monkeypatch):
    monkeypatch.setattr(
        lexicon,
        "terms_map",
        lambda: {"一卡通": "校园卡", "饭卡": "校园卡", "教务处": "教务处", "教务": "教务处"},
    )


def test_rewrite_longest_first(fake_terms):
    text, hits = lexicon.rewrite("一卡通丢了，去教务问一下")
    assert text == "校园卡丢了，去教务处问一下"
    assert ("一卡通", "校园卡") in hits


def test_rewrite_no_hit_keeps_text(fake_terms):
    text, hits = lexicon.rewrite("学生证补办流程")
    assert text == "学生证补办流程"
    assert hits == []


def test_lexemes_drop_stopwords_and_punct():
    terms = lexicon.lexemes("请问一下，学生证丢了怎么补办？")
    assert "学生证" in terms or "学生" in terms
    assert "怎么" not in terms
    assert "请问" not in terms
    assert len(terms) <= 10


def test_audience_and_channel():
    assert lexicon.audience_of("我是研一学生") == "grad"
    assert lexicon.audience_of("本科在读") == "undergrad"
    assert lexicon.audience_of("请问怎么补办") == "unknown"
    assert lexicon.channel_of("能不能在线上办") == "online"
    assert lexicon.channel_of("去窗口办") == "offline"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你好", Intent.SMALLTALK),
        ("帮我写一段代码", Intent.OUT_OF_SCOPE),
        ("学生证丢了怎么补办", Intent.MATTER),
        ("国家奖学金评定的条件是什么", Intent.POLICY),
        ("图书馆几点开门", Intent.FAQ),
    ],
)
def test_rules_intent(text, expected):
    assert rules_intent(text) is expected
