"""提示模板加载与确定性话术。

模板用 string.Template 的 $var 占位，不用 str.format：
证据与问句里出现的大括号会把 format 打崩，$ 只与标识符冲突，风险小得多。
"""

from __future__ import annotations

from pathlib import Path
from string import Template

DIR = Path(__file__).resolve().parent / "prompts"
_cache: dict[str, str] = {}


def load(name: str) -> str:
    """读模板原文（不带 .txt）。文件缺失直接抛错，不在运行期静默降级。"""
    if name in _cache:
        return _cache[name]
    path = DIR / f"{name}.txt"
    text = path.read_text(encoding="utf-8").strip()
    _cache[name] = text
    return text


def render(name: str, **vars: object) -> str:
    return Template(load(name)).safe_substitute(**vars)


# --------------------------------------------------------------- 确定性话术
# 这几段不交给模型：拒答与寒暄的措辞必须每次一致，否则"口径一致性"无从谈起。

SMALLTALK = (
    "我可以回答三类问题：\n"
    "1. 办事流程与所需材料（如学生证补办、成绩单打印、宿舍调换）；\n"
    "2. 制度口径与资格条件（如奖学金评定、重修与免修规定）；\n"
    "3. 时间、地点、费用这类常见疑问。\n"
    "请直接说事项名称或把问题写具体一点。"
)

OUT_OF_SCOPE = (
    "这个问题不在本校校园办事与制度的范围内，我不做推测性回答。\n"
    "我能回答的是办事流程与材料、制度口径、常见疑问三类问题。"
)

REFUSAL_NO_EVIDENCE = (
    "没有在现有知识库里找到与「$question」对应的办理依据。为避免给错口径，这里不做推测。\n"
    "建议：1. 直接用事项名称再问一次；2. 到学校网上办事大厅检索该事项；"
    "3. 联系$dept确认。"
)

REFUSAL_LOW_CONFIDENCE = (
    "检索到的资料与这个问题的匹配度不足（$basis），"
    "可能是问句太宽或该事项尚未收录。\n"
    "建议补充具体事项名称、办理环节或本人身份后再问一次。"
)

REFUSAL_UNVERIFIED = (
    "生成的内容没有通过引用核对（$detail），为避免误导，这里不给结论。\n"
    "下面是与问题最相关的原文出处，请以原文为准：\n$sources"
)

REFUSAL_UNAVAILABLE = (
    "答案生成暂时不可用（$detail）。可以用下面这些原始出处自己核对，或稍后重试：\n$sources"
)

EMPTY_QUESTION = "请把问题写出来，例如「学生证丢了怎么补办」。"
TOO_LONG = "问题太长（超过 $limit 字），请只问一个具体问题。"

DEFAULT_DEPT = "相关职能部门"


def template(text: str, **vars: object) -> str:
    return Template(text).safe_substitute(**vars)


def refusal_no_evidence(question: str, dept: str = "") -> str:
    return Template(REFUSAL_NO_EVIDENCE).safe_substitute(
        question=question, dept=dept or DEFAULT_DEPT
    )


def refusal_low_confidence(basis: str) -> str:
    return Template(REFUSAL_LOW_CONFIDENCE).safe_substitute(basis=basis)


def refusal_unverified(detail: str, sources: str) -> str:
    return Template(REFUSAL_UNVERIFIED).safe_substitute(detail=detail, sources=sources)


def refusal_unavailable(detail: str, sources: str) -> str:
    return Template(REFUSAL_UNAVAILABLE).safe_substitute(detail=detail, sources=sources)
