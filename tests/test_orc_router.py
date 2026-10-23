"""意图路由：指代补全、单段与 fan-out 的判定边界。"""

from apps.orchestrator.router import DIRECT, FANOUT, SINGLE, enrich, plan_for
from apps.orchestrator.session import SessionState
from apps.qa.types import Intent, Understanding


def u(intent=Intent.MATTER, subs=None, original="学生证丢了怎么补办"):
    return Understanding(
        intent=intent,
        original=original,
        rewritten=original,
        sub_questions=subs or [],
        confidence=0.9,
    )


def state(matter=""):
    return SessionState(conversation_id="c1", last_matter=matter)


def test_direct_for_smalltalk_and_out_of_scope():
    assert plan_for(u(Intent.SMALLTALK, original="你好")).mode == DIRECT
    assert plan_for(u(Intent.OUT_OF_SCOPE, original="今天天气")).mode == DIRECT


def test_single_when_no_sub_questions():
    plan = plan_for(u())
    assert plan.mode == SINGLE
    assert plan.segments == ("学生证丢了怎么补办",)


def test_single_when_only_one_sub_question():
    """拆成一段等于多花一次调用，不并行。"""
    plan = plan_for(u(subs=["学生证补办要多久"]))
    assert plan.mode == SINGLE


def test_fanout_keeps_order_and_caps(settings):
    settings.ORC_FANOUT_MAX = 2
    plan = plan_for(u(subs=["要什么材料", "多久能办好", "去哪里办"]))
    assert plan.mode == FANOUT
    assert plan.segments == ("要什么材料", "多久能办好")


def test_fanout_drops_duplicates_and_original():
    """重复项与"原句"不算子问题；清理后不足两段就退回单段。"""
    plan = plan_for(u(subs=["学生证丢了怎么补办", "要什么材料", "要什么材料", "多久能办好"]))
    assert plan.mode == FANOUT
    assert plan.segments == ("要什么材料", "多久能办好")

    assert plan_for(u(subs=["学生证丢了怎么补办", "  ", "要什么材料"])).mode == SINGLE


def test_enrich_fills_pronoun_from_last_matter():
    q, patched = enrich("那要多久", state("学生证补办"))
    assert patched is True
    assert q.startswith("学生证补办")


def test_enrich_leaves_standalone_questions():
    q, patched = enrich("学生证丢了怎么补办", state("学生证补办"))
    assert patched is False and q == "学生证丢了怎么补办"

    q2, patched2 = enrich("补办需要多久", state(""))
    assert patched2 is False and q2 == "补办需要多久"


def test_enrich_only_touches_short_follow_ups():
    """长问句里的"这个/它"多半是新话题，补上上一轮事项会把两件事糅在一起。"""
    q, patched = enrich("这个学校的图书馆远不远", state("学生证补办"))
    assert patched is False and q == "这个学校的图书馆远不远"

    q2, patched2 = enrich("它需要多久", state("学生证补办"))
    assert patched2 is True and q2.startswith("学生证补办")
