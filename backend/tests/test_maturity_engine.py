"""
Рушій зрілості за Додатком В (services/maturity.py) і каталог annex_v.py: формули, межі правил,
k-анонімність (приховані категорії не відновлюються, null не стає 0). Без БД і HTTP.
"""
import json
from fractions import Fraction

import pytest

from app.annex_v import (CHECKLIST, CRITERIA, FORMS, INDEX_CRITERIA, LEVEL_RULE, criterion_levels,
                         validate_answers)
from app.services import maturity
from app.services.maturity import calculate, round_half_up

ASSESSMENT = {"id": 99, "name": "SYN", "status": "closed"}
K = 5


def levels(value, **override) -> dict:
    """Рівні всіх 11 критеріїв однієї анкети/експерта."""
    return {key: Fraction(str(override.get(key, value))) for key in CRITERIA}


def crowd(category: str, n: int, value, **override) -> list:
    return [(category, levels(value, **override)) for _ in range(n)]


def run(responses=(), experts=(), checklist=(), indicators=(), k=K) -> dict:
    return calculate(ASSESSMENT, k, list(responses), list(experts), list(checklist), list(indicators))


def criterion(result: dict, key: str) -> dict:
    return next(c for c in result["criteria"] if c["key"] == key)


def rules(result: dict, key: str | None = None) -> set[str]:
    return {r["rule_id"] for r in result["recommendations"] if key is None or r["criterion"] == key}


def full_answers(form: int, letter: str = "c") -> dict:
    return {qid: f"{qid}-{letter}" for qid in FORMS[form]}


# --- Каталог ---------------------------------------------------------------------------------------------------

def test_catalog_mirrors_catalog_v2_ids():
    assert len(FORMS[1]) == 12 and len(FORMS[2]) == 10
    assert "av-f1-culture-1" in FORMS[1] and FORMS[1]["av-f1-culture-1"]["criterion"] == "leadership"
    assert all(q["criterion"] != "leadership" for q in FORMS[2].values())
    assert FORMS[1]["av-f1-accountability-3"]["criterion"] == "whistleblowers"
    assert set(FORMS[1]["av-f1-accountability-3"]["options"]) == {f"av-f1-accountability-3-{x}" for x in "abcdef"}
    assert set(FORMS[2]["av-f2-system-1"]["options"]) == {f"av-f2-system-1-{x}" for x in "abcde"}
    assert len(CHECKLIST) == 20 and {i["criterion"] for i in CHECKLIST} == set(INDEX_CRITERIA)
    assert "Додаток Г" in LEVEL_RULE


def test_level_rule_and_whistleblowers_mapping():
    answers = full_answers(1, "e")
    answers["av-f1-accountability-3"] = "av-f1-accountability-3-e"
    assert criterion_levels(1, answers)["whistleblowers"] == 4          # Додаток Г: e=4
    answers["av-f1-accountability-3"] = "av-f1-accountability-3-f"
    assert criterion_levels(1, answers)["whistleblowers"] == 5          # f=5, не виключається
    assert criterion_levels(1, full_answers(1, "a"))["leadership"] == 1
    assert criterion_levels(2, full_answers(2, "d"))["audit"] == 4


def test_openness_counts_once_per_questionnaire():
    answers = full_answers(1, "c")
    answers["av-f1-culture-4"], answers["av-f1-culture-5"] = "av-f1-culture-4-a", "av-f1-culture-5-e"
    assert criterion_levels(1, answers)["openness"] == 3               # (1 + 5) / 2 у межах анкети
    one = criterion_levels(1, answers)
    other = criterion_levels(2, full_answers(2, "e"))                  # форма 2: openness = 5
    result = run(responses=[("npp", one)] * 5 + [("npp", other)] * 5, k=5)
    assert criterion(result, "openness")["self"] == {"level": 4.0, "responses": 10, "status": "ok"}


@pytest.mark.parametrize("change,message", [
    (lambda a: a.pop("av-f1-culture-1"), "кожне питання"),
    (lambda a: a.update({"av-f9-x-1": "av-f9-x-1-a"}), "кожне питання"),
    (lambda a: a.update({"av-f1-culture-1": "av-f1-culture-2-a"}), "не належить"),
    (lambda a: a.update({"av-f1-culture-1": "av-f1-culture-1-f"}), "не належить"),
])
def test_validate_answers_rejects_incomplete_or_foreign_options(change, message):
    answers = full_answers(1)
    change(answers)
    assert message in validate_answers(1, answers)
    assert validate_answers(1, full_answers(1)) is None
    assert validate_answers(3, {}) is not None


# --- Формули ---------------------------------------------------------------------------------------------------

def test_round_half_up_boundaries():
    assert round_half_up(Fraction(325, 100), 1) == Fraction(33, 10)
    assert round_half_up(Fraction(3249, 1000), 1) == Fraction(32, 10)
    assert round_half_up(Fraction(1, 3) * 100, 2) == Fraction(3333, 100)


def test_checklist_level_uses_confirmed_items_only():
    checklist = [{"code": "B-06", "status": "yes", "confirmed": True},       # risks
                 {"code": "B-14", "status": "partial", "confirmed": True},
                 {"code": "B-20", "status": "no", "confirmed": True}]
    result = run(checklist=checklist)
    assert criterion(result, "risks")["checklist"] == {"level": 3.0, "items_total": 3, "items_confirmed": 3,
                                                       "status": "ok"}   # 1 + 4 × 1,5 / 3
    checklist[2]["confirmed"] = False                                        # «no» не підтверджено
    assert criterion(run(checklist=checklist), "risks")["checklist"]["level"] == 4.0
    missing = criterion(run(checklist=[{"code": "B-06", "status": "yes", "confirmed": False}]), "risks")
    assert missing["checklist"] == {"level": None, "items_total": 3, "items_confirmed": 0, "status": "missing"}


def test_expert_level_is_mean_over_experts_and_index_uses_exact_levels():
    experts = [levels(3), levels(3), levels(3), levels(4)]                  # 3,25 → показ 3,3
    result = run(experts=experts)
    assert criterion(result, "ethics")["expert"] == {"level": 3.3, "experts": 4, "status": "ok"}
    assert result["indices"]["expert"] == 56.25                             # (3,25 − 1) / 4 × 100, не 57,5
    assert result["indices"]["self"] is None and result["indices"]["checklist"] is None


def test_maturity_criterion_is_shown_separately_and_not_in_index():
    result = run(responses=crowd("npp", 6, 2, maturity=5), experts=[levels(2, maturity=5)])
    assert result["overall_self_declared"] == {"level": 5.0, "responses": 6, "status": "ok", "expert_level": 5.0}
    assert result["indices"]["self"] == 25.0 and result["indices"]["expert"] == 25.0
    assert "maturity" not in {c["key"] for c in result["criteria"]}
    assert result["methodology_version"] == "annex-v-maturity-0.1" and result["level_rule"] == LEVEL_RULE


def test_index_is_null_when_one_criterion_is_missing_never_zero():
    one_item_per_criterion = [{"code": code, "status": "yes", "confirmed": True}
                              for code in ("B-01", "B-02", "B-04", "B-06", "B-08", "B-09", "B-10",
                                           "B-12", "B-13", "B-15")]
    assert run(checklist=one_item_per_criterion)["indices"]["checklist"] == 100.0
    without_audit = [e for e in one_item_per_criterion if e["code"] != "B-12"]
    result = run(checklist=without_audit)
    assert result["indices"]["checklist"] is None
    assert criterion(result, "audit")["checklist"]["level"] is None


# --- Правила і межі --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("expert,fires", [(3.0, True), (3.1, False)])
def test_self_expert_gap_boundary(expert, fires):
    result = run(responses=crowd("npp", 5, 4), experts=[levels(4, ethics=expert)])
    gap = criterion(result, "ethics")["gaps"][0]
    assert gap["rule_id"] == "MAT_SELF_EXPERT_GAP_GE_1" and gap["right"] == "expert"
    assert gap["diff"] == round(4 - expert, 1) and gap["flag"] is fires
    assert ("MAT_SELF_EXPERT_GAP_GE_1" in rules(result, "ethics")) is fires


@pytest.mark.parametrize("status,fires", [("partial", True), ("yes", False)])
def test_self_checklist_gap_boundary(status, fires):
    # self 4,0; checklist: partial → 3,0 (різниця 1,0, спрацьовує), yes → 5,0
    result = run(responses=crowd("npp", 5, 4), checklist=[{"code": "B-09", "status": status, "confirmed": True}])
    gap = criterion(result, "whistleblowers")["gaps"][1]
    assert gap["right"] == "checklist" and gap["flag"] is fires
    assert ("MAT_SELF_CHECKLIST_GAP_GE_1" in rules(result, "whistleblowers")) is fires


def test_gaps_are_null_without_other_source():
    gaps = criterion(run(responses=crowd("npp", 5, 4)), "audit")["gaps"]
    assert [g["diff"] for g in gaps] == [None, None] and not any(g["flag"] for g in gaps)


@pytest.mark.parametrize("expert,fires", [(2.9, True), (3.0, False)])
def test_low_level_uses_expert_when_present(expert, fires):
    result = run(responses=crowd("npp", 5, 1), experts=[levels(4, risks=expert)])
    assert ("MAT_LOW_LEVEL_LT_3" in rules(result, "risks")) is fires


@pytest.mark.parametrize("self_level,fires", [(2.9, True), (3.0, False)])
def test_low_level_falls_back_to_self(self_level, fires):
    result = run(responses=crowd("npp", 5, 4, checks=self_level))
    assert ("MAT_LOW_LEVEL_LT_3" in rules(result, "checks")) is fires
    if fires:
        rec = next(r for r in result["recommendations"] if r["rule_id"] == "MAT_LOW_LEVEL_LT_3")
        assert rec["basis"]["source"] == "self" and rec["requires_human_decision"] is True


@pytest.mark.parametrize("self_level,confirmed,fires", [(3.5, True, True), (3.4, True, False), (3.5, False, False)])
def test_objective_below_target(self_level, confirmed, fires):
    indicator = {"criterion": "education", "name": "Навчання", "value": 81.0, "target": 90.0, "confirmed": confirmed}
    result = run(responses=crowd("npp", 5, 2, education=self_level), indicators=[indicator])
    assert ("MAT_OBJECTIVE_BELOW_TARGET" in rules(result, "education")) is fires
    assert criterion(result, "education")["objective"] == [
        {"name": "Навчання", "value": 81.0, "target": 90.0, "confirmed": confirmed}]


def test_objective_at_target_does_not_fire():
    indicator = {"criterion": "education", "name": "Навчання", "value": 90, "target": 90, "confirmed": True}
    assert "MAT_OBJECTIVE_BELOW_TARGET" not in rules(run(responses=crowd("npp", 5, 4), indicators=[indicator]))


@pytest.mark.parametrize("self_level,indicators,fires", [
    (4.0, [], True),
    (3.9, [], False),
    (4.0, [{"criterion": "officer", "name": "План", "value": 92, "target": 90, "confirmed": False}], True),
    (4.0, [{"criterion": "officer", "name": "План", "value": 92, "target": 90, "confirmed": True}], False),
])
def test_objective_unconfirmed(self_level, indicators, fires):
    result = run(responses=crowd("npp", 5, 2, officer=self_level), indicators=indicators)
    assert ("MAT_OBJECTIVE_UNCONFIRMED" in rules(result, "officer")) is fires


def test_recommendation_ids_are_deterministic_and_texts_ukrainian():
    first = run(responses=crowd("npp", 5, 4), experts=[levels(2)])
    second = run(responses=crowd("npp", 5, 4), experts=[levels(2)])
    assert [r["id"] for r in first["recommendations"]] == [r["id"] for r in second["recommendations"]]
    assert len({r["id"] for r in first["recommendations"]}) == len(first["recommendations"])
    assert all("«" in r["text"] and r["requires_human_decision"] for r in first["recommendations"])


def test_no_rules_without_data():
    result = run()
    assert result["recommendations"] == []
    assert all(c["self"] == {"level": None, "responses": None, "status": "missing"} for c in result["criteria"])
    assert result["indices"] == {"self": None, "expert": None, "checklist": None}


# --- k-анонімність ---------------------------------------------------------------------------------------------

def test_small_category_and_secondary_are_hidden_and_not_listed():
    responses = crowd("cadets", 10, 3) + crowd("mgmt", 7, 5) + crowd("staff", 3, 1)
    result = run(responses=responses)
    text = json.dumps(result, ensure_ascii=False)
    assert result["visible_categories"] == ["cadets"] and result["suppressed"] is True
    assert '"mgmt"' not in text and '"staff"' not in text                    # D4: навіть назв немає
    ethics = criterion(result, "ethics")
    assert ethics["self_by_category"] == [{"category": "cadets", "level": 3.0, "hidden": False}]
    # Загальний рівень = 20 анкет; «загальне − видимі» дає лише суму mgmt + staff (10 ≥ k)
    assert ethics["self"] == {"level": 3.4, "responses": 20, "status": "ok"}   # (30 + 35 + 3) / 20


def test_single_hidden_contributor_is_suppressed():
    # leadership є лише у формі 1: її заповнила тільки mgmt (прихована вторинно через staff)
    responses = ([("cadets", {k: v for k, v in levels(3).items() if k != "leadership"})] * 10
                 + crowd("mgmt", 7, 5) + [("staff", {k: v for k, v in levels(1).items() if k != "leadership"})] * 3)
    result = run(responses=responses)
    leadership = criterion(result, "leadership")
    assert leadership["self"] == {"level": None, "responses": None, "status": "suppressed"}
    assert leadership["self_by_category"] == [{"category": "cadets", "level": None, "hidden": False}]
    assert result["indices"]["self"] is None                                  # null, не 0
    assert criterion(result, "ethics")["self"]["status"] == "ok"


def test_total_below_k_suppresses_everything():
    result = run(responses=crowd("npp", 4, 5), experts=[levels(3)])
    assert all(c["self"] == {"level": None, "responses": None, "status": "suppressed"} for c in result["criteria"])
    assert result["overall_self_declared"]["level"] is None
    assert result["visible_categories"] == [] and result["indices"]["self"] is None
    assert not rules(result) & {"MAT_SELF_EXPERT_GAP_GE_1", "MAT_OBJECTIVE_UNCONFIRMED"}


def test_per_criterion_secondary_suppression_inside_visible_categories():
    # Категорії видимі (npp 8, cadets 20), але audit заповнили лише 3 з npp → клітинка npp прихована,
    # і вторинно — cadets (інакше npp = загальне − cadets)
    responses = ([("npp", levels(4))] * 3 + [("npp", {k: v for k, v in levels(4).items() if k != "audit"})] * 5
                 + crowd("cadets", 20, 2))
    audit = criterion(run(responses=responses), "audit")
    assert [c["level"] for c in audit["self_by_category"]] == [None, None]
    assert audit["self"]["status"] == "ok" and audit["self"]["responses"] == 23


def test_engine_has_no_individual_answers_in_output():
    result = run(responses=crowd("npp", 6, 3))
    assert "av-f" not in json.dumps(result)
    assert maturity.VERSION == "annex-v-maturity-0.1"
