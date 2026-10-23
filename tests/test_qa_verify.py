"""M9 校验：纯函数，不碰数据库与模型。"""

from apps.qa.types import Evidence
from apps.qa.verify import check, detect_conflicts, extract_refs, numbers_in


def ev(ref: int, title: str, content: str, section: str = "") -> Evidence:
    return Evidence(
        ref=ref,
        chunk_id=ref,
        document_id=ref,
        title=title,
        doc_type="guide",
        dept="教务处",
        section=section,
        page=1,
        content=content,
        score=0.9,
        fusion=1.0,
        source="both",
    )


def test_extract_refs_dedup_and_order():
    text = "结论见[2]，材料在[1]，另外[2]也说了，[12] 是干扰"
    assert extract_refs(text) == [2, 1, 12]


def test_numbers_normalized():
    assert numbers_in("受理后3 个工作日领取，收费 2 元/份，共 1次") == {
        "3工作日",
        "2元",
        "1次",
    }


def test_numbers_match_across_scripts():
    """语料里两种写法混用：回答写"3 个工作日"、证据写"三个工作日"必须能对上。"""
    assert numbers_in("三个工作日") == numbers_in("3 个工作日") == {"3工作日"}
    assert numbers_in("二十五元") == {"25元"}
    assert numbers_in("一次性告知，一站式办理") == set()

    evidence = [ev(1, "学生证补办", "受理后三个工作日领取新证。")]
    assert check("受理后 3 个工作日领取[1]。", evidence, []).ok


def test_check_flags_number_not_in_evidence():
    evidence = [ev(1, "成绩单打印", "普通件当日取，中英文对照件两个工作日取。")]
    text = "普通件当日可取[1]。"
    assert check(text, evidence, []).ok

    bad = check("普通件三个工作日可取[1]。", evidence, [])
    assert not bad.ok
    assert bad.unverified_numbers == ["3工作日"]
    assert [i.code for i in bad.blocking] == ["unverified_number"]


def test_check_flags_bad_ref_and_missing_citation():
    evidence = [ev(1, "学生证补办", "到教务处学籍科窗口提交。")]
    report = check("到教务处学籍科办理。", evidence, [])
    assert {i.code for i in report.issues} == {"no_citation"}

    report2 = check("到教务处学籍科办理[3]。", evidence, [])
    assert report2.bad_refs == [3]
    assert "bad_ref" in {i.code for i in report2.issues}


def test_check_ignores_unknown_claims():
    """承认"资料未涉及"的句子不要求引用，否则模型越诚实越被判失败。"""
    evidence = [ev(1, "学生证补办", "补办后原证自动作废。")]
    report = check("补办后原证作废[1]。现有资料未涉及加急办理。", evidence, [])
    assert report.ok
    assert report.citation_coverage == 1.0


def test_conflict_detected_only_for_same_matter():
    same = [
        ev(1, "学生证补办", "补办收取工本费 10 元/份。"),
        ev(2, "学生证补办（修订）", "补办收取工本费 20 元/份。"),
    ]
    conflicts = detect_conflicts(same)
    assert len(conflicts) == 1
    assert conflicts[0].field.startswith("费用")
    assert set(conflicts[0].values) == {"10元", "20元"}

    different = [
        ev(1, "学生证补办", "补办收取工本费 10 元/份。"),
        ev(2, "校园卡补办", "补办收取工本费 20 元/份。"),
    ]
    assert detect_conflicts(different) == []


def test_conflict_must_be_surfaced_in_answer():
    evidence = [
        ev(1, "学生证补办", "补办收取工本费 10 元/份。"),
        ev(2, "学生证补办（修订）", "补办收取工本费 20 元/份。"),
    ]
    conflicts = detect_conflicts(evidence)
    partial = check("补办工本费 10 元/份[1]。", evidence, conflicts)
    assert "conflict_not_surfaced" in {i.code for i in partial.blocking}

    full = check("存在两种口径：10 元/份[1]，另有 20 元/份[2]。", evidence, conflicts)
    assert "conflict_not_surfaced" not in {i.code for i in full.blocking}


def test_empty_conflicts_is_noop():
    assert detect_conflicts([]) == []
    assert check("结论[1]。", [ev(1, "x", "结论。")], []).ok
