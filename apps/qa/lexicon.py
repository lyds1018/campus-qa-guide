"""词典、停用词与分词口径。

检索侧与理解侧必须共用同一套分词（P1 的 search_text 是 jieba 搜索模式），
所以 tokenize 直接复用 knowledge.chunking，不另写一份。
"""

from __future__ import annotations

import re

from django.core.cache import cache

from apps.knowledge.chunking import tokenize
from apps.knowledge.repositories import ReadRepository

TERMS_KEY = "qa:terms"
TERMS_TTL = 300  # P6 改完词典立即 delete 该键，不必等过期

# 停用词只收"问句骨架"，不收业务词：办理、流程、材料、时限都必须留下
STOPWORDS = {
    "的", "了", "吗", "呢", "啊", "呀", "吧", "哦", "嗯", "是", "有", "在", "和", "与", "及",
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那", "这个", "那个", "其",
    "怎么", "怎样", "如何", "什么", "多少", "哪些", "哪个", "哪里", "哪儿",
    "我想", "想问", "问一下", "请问", "麻烦", "帮我", "帮忙", "告诉", "一下", "一般",
    "可以", "能否", "能不能", "是否", "需要", "要不要", "该", "应该", "都", "还", "就",
    "学校", "本校", "校内", "学生", "同学", "老师", "现在", "目前", "具体", "相关",
    "或者", "还是", "以及", "如果", "因为", "所以", "但是", "然后", "还有",
}

PUNCT_RE = re.compile(r"[\s\u3000-\u303f\uff00-\uffef!-/:-@\[-`{-~]+")

AUDIENCE_WORDS: dict[str, str] = {
    "本科生": "undergrad", "本科": "undergrad", "大一大二": "undergrad", "在读本科": "undergrad",
    "研究生": "grad", "硕士": "grad", "博士": "grad", "博一": "grad", "研一": "grad",
    "教职工": "staff", "教师": "staff", "辅导员": "staff", "在职": "staff",
    "毕业生": "alumni", "校友": "alumni", "往届": "alumni", "已毕业": "alumni",
}

CHANNEL_WORDS: dict[str, str] = {
    "线上": "online", "网上": "online", "网站": "online", "系统": "online", "自助": "online",
    "线下": "offline", "窗口": "offline", "现场": "offline", "大厅": "offline",
}


def terms_map() -> dict[str, str]:
    """别名 → 规范名。300 秒缓存，避免每问一次查一遍词典表。"""
    cached = cache.get(TERMS_KEY)
    if cached:
        return cached
    data = ReadRepository().terms_map()
    cache.set(TERMS_KEY, data, TERMS_TTL)
    return data


def rewrite(text: str) -> tuple[str, list[tuple[str, str]]]:
    """按词典做最长优先替换，一次扫描完成，已替换的片段不再参与匹配。"""
    mapping = terms_map()
    if not text or not mapping:
        return text, []
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    hits: list[tuple[str, str]] = []

    def _sub(m: re.Match[str]) -> str:
        key = m.group(0)
        canonical = mapping[key]
        if canonical == key:
            return key
        hits.append((key, canonical))
        return canonical

    return pattern.sub(_sub, text), hits


def lexemes(text: str, limit: int = 10) -> list[str]:
    """供全文检索的查询词：去停用词、去标点、去重、保序。

    PG 侧用 OR 组合（见 retrieve），因为问句里的词几乎不可能全部命中同一块。
    """
    out: list[str] = []
    for token in tokenize(text).split(" "):
        token = token.strip()
        if not token or token in STOPWORDS or PUNCT_RE.fullmatch(token):
            continue
        if token.isdigit() or len(token) > 12:
            continue
        if token not in out:
            out.append(token)
        if len(out) >= limit:
            break
    return out


def keyword(text: str, limit: int = 6) -> str:
    """给提示与日志用的核心词，不参与检索。"""
    return " ".join(lexemes(text, limit))


def audience_of(text: str) -> str:
    for word, code in AUDIENCE_WORDS.items():
        if word in text:
            return code
    return "unknown"


def channel_of(text: str) -> str:
    for word, code in CHANNEL_WORDS.items():
        if word in text:
            return code
    return "unknown"
