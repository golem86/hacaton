"""
Зрілість за Додатком В: чистий розрахунок без БД, мережі й ШІ (methodology annex-v-maturity-0.1).

Вхід — уже зібрані з БД рівні (annex_v.criterion_levels) і записи чек-листа та показників.
Арифметика точна (Fraction); на виході рівні з 1 знаком після коми, індекси — з 2.

Формули (всі явні, задокументовані в docs/API_CONTRACT.md):
  - рівень варіанта: a=1, b=2, c=3, d=4, e=5; викривачі: a=1, b=2, c=3, d=4, e=4, f=5
    (Додаток Г, с. 73; annex_v.LEVEL_MAPS);
  - рівень критерію в одній анкеті = середнє її відповідей на питання критерію (openness у формі 1
    має два питання — анкета враховується один раз);
  - self (самооцінка) = середнє по анкетах (кожна анкета — однакова вага);
  - expert = середнє по експертних оцінках; checklist = 1 + 4 × (yes + 0,5·partial) / confirmed,
    лише за ПІДТВЕРДЖЕНИМИ пунктами критерію;
  - індекс джерела (0–100) = (середній рівень 10 критеріїв − 1) / 4 × 100, рівні ваги;
    критерій `maturity` (заявлений рівень) до індексу не входить; null, якщо хоч один критерій
    цього джерела відсутній або прихований (без перерозподілу ваг). Індекс рахується з ТОЧНИХ
    рівнів (не з округлених до 0,1) і лише потім округлюється до 2 знаків (half-up);
  - правила (прапорці розривів і порогів) порівнюють рівні, округлені до 1 знака (те, що бачить
    користувач), тож прапорці завжди узгоджені з показаними числами.

Анонімність (як anonymity.py і routes/results.py):
  - категорії з < k анкетами приховуються, плюс вторинне приховування (hidden_flags);
    приховані категорії НЕ перелічуються (D4);
  - для кожного критерію категорії додатково проходять hidden_flags за кількістю анкет із рівнем
    цього критерію (з примусовим приховуванням категорій, прихованих загалом);
  - загальний рівень критерію показується, лише якщо анкет з рівнем ≥ k і приховану частину
    не можна приписати одній категорії (рівно один прихований внесок → suppressed);
  - null ніколи не перетворюється на 0.
"""
import hashlib
import json
from fractions import Fraction

from ..anonymity import hidden_flags
from ..annex_v import CHECKLIST, CRITERIA, INDEX_CRITERIA, LEVEL_RULE, OVERALL_CRITERION

VERSION = "annex-v-maturity-0.1"
RULE_LOW = "MAT_LOW_LEVEL_LT_3"
RULE_SELF_EXPERT = "MAT_SELF_EXPERT_GAP_GE_1"
RULE_SELF_CHECKLIST = "MAT_SELF_CHECKLIST_GAP_GE_1"
RULE_BELOW_TARGET = "MAT_OBJECTIVE_BELOW_TARGET"
RULE_UNCONFIRMED = "MAT_OBJECTIVE_UNCONFIRMED"
LOW_THRESHOLD = Fraction(3)
GAP_THRESHOLD = Fraction(1)
BELOW_TARGET_SELF_MIN = Fraction(7, 2)       # 3,5
UNCONFIRMED_SELF_MIN = Fraction(4)

TEXTS = {
    RULE_LOW: "Рівень зрілості за критерієм «{name}» нижчий за 3 («визначений»): визначити заходи "
              "для переходу на наступний рівень і відповідальних за них.",
    RULE_SELF_EXPERT: "Самооцінка за критерієм «{name}» перевищує експертну оцінку щонайменше на 1 рівень: "
                      "обговорити розбіжність із робочою групою та перевірити підстави самооцінки.",
    RULE_SELF_CHECKLIST: "Самооцінка за критерієм «{name}» перевищує рівень, підтверджений чек-листом "
                         "(Додаток Б), щонайменше на 1 рівень: перевірити впровадження заходів і докази.",
    RULE_BELOW_TARGET: "За критерієм «{name}» підтверджений об'єктивний показник нижчий за цільове значення "
                       "за високої самооцінки (≥ 3,5): проаналізувати причини розриву.",
    RULE_UNCONFIRMED: "Висока самооцінка за критерієм «{name}» (≥ 4) не підкріплена підтвердженими "
                      "об'єктивними показниками: внести показники й підтвердити їх.",
}


def round_half_up(value: Fraction, places: int) -> Fraction:
    """Точне округлення «половина вгору» (рівні й індекси невід'ємні)."""
    scale = 10 ** places
    return Fraction((value * scale + Fraction(1, 2)).__floor__(), scale)


def show(value: Fraction | None) -> float | None:
    return None if value is None else float(value)


def _mean(values: list[Fraction]) -> Fraction | None:
    return sum(values, Fraction(0)) / len(values) if values else None


def _level(values: list[Fraction]) -> Fraction | None:
    mean = _mean(values)
    return None if mean is None else round_half_up(mean, 1)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _self(responses: list[tuple[str, dict]], k: int) -> tuple[dict, list[str], bool]:
    """Самооцінка по критеріях з k-анонімністю. Повертає (по критеріях, видимі категорії, suppressed)."""
    categories = sorted({category for category, _ in responses})
    sizes = [sum(1 for c, _ in responses if c == category) for category in categories]
    category_hidden = hidden_flags(sizes, k)
    visible = [c for c, hidden in zip(categories, category_hidden) if not hidden]
    total = len(responses)

    result = {}
    for key in CRITERIA:
        per_category = {c: [levels[key] for cat, levels in responses if cat == c and key in levels]
                        for c in categories}
        counts = [len(per_category[c]) for c in categories]
        flags = hidden_flags(counts, k, force_hidden=category_hidden) if categories else []
        hidden_contributors = sum(1 for n, hidden in zip(counts, flags) if hidden and n > 0)
        n = sum(counts)
        if total == 0 or (total >= k and n == 0):
            status = "missing"
        elif total < k or n < k or hidden_contributors == 1:
            status = "suppressed"
        else:
            status = "ok"
        everything = [level for c in categories for level in per_category[c]]
        by_category = []
        for c, count, hidden in zip(categories, counts, flags):
            if c not in visible:
                continue                                     # D4: приховані категорії не перелічуються
            shown = status == "ok" and not hidden and count > 0
            # hidden: дані категорії є, але приховані; без даних (count = 0) — level null, hidden false
            by_category.append({"category": c, "level": show(_level(per_category[c])) if shown else None,
                                "hidden": not shown and count > 0})
        result[key] = {"level": _level(everything) if status == "ok" else None,
                       "exact": _mean(everything) if status == "ok" else None,
                       "responses": n if status == "ok" else None,
                       "status": status, "by_category": by_category}
    return result, visible, total < k or any(category_hidden)


def _sources(experts: list[dict], checklist: list[dict]) -> tuple[dict, dict]:
    expert = {}
    for key in CRITERIA:
        values = [levels[key] for levels in experts if key in levels]
        expert[key] = {"level": _level(values), "exact": _mean(values), "experts": len(values),
                       "status": "ok" if values else "missing"}
    entries = {e["code"]: e for e in checklist}
    check = {}
    for key in CRITERIA:
        items = [item for item in CHECKLIST if item["criterion"] == key]
        confirmed = [entries[i["code"]] for i in items
                     if i["code"] in entries and entries[i["code"]]["confirmed"] and entries[i["code"]]["status"]]
        exact = None
        if confirmed:
            score = sum((Fraction(1) if e["status"] == "yes" else Fraction(1, 2) if e["status"] == "partial"
                         else Fraction(0)) for e in confirmed)
            exact = 1 + 4 * score / len(confirmed)
        check[key] = {"level": None if exact is None else round_half_up(exact, 1), "exact": exact,
                      "items_total": len(items), "items_confirmed": len(confirmed),
                      "status": "ok" if confirmed else "missing"}
    return expert, check


def _index(levels: list[Fraction | None]) -> Fraction | None:
    if any(level is None for level in levels):
        return None
    return round_half_up((_mean(levels) - 1) / 4 * 100, 2)


def calculate(assessment: dict, k: int, responses: list[tuple[str, dict]], experts: list[dict],
              checklist: list[dict], indicators: list[dict]) -> dict:
    """
    assessment — {id, name, status}; k — мінімальний розмір групи;
    responses — [(категорія, {критерій: Fraction рівень})] по одній на анкету (annex_v.criterion_levels);
    experts — [{критерій: Fraction}]; checklist — [{code, status, confirmed}];
    indicators — [{name, value, target, confirmed, criterion}] (value/target — числа 0–100).
    """
    self_data, visible, suppressed = _self(responses, k)
    expert, check = _sources(experts, checklist)

    criteria, recommendations = [], []
    for key in INDEX_CRITERIA:
        meta = CRITERIA[key]
        s, e, c = self_data[key]["level"], expert[key]["level"], check[key]["level"]
        own = [i for i in indicators if i["criterion"] == key]
        gaps = []
        for rule, right, other in ((RULE_SELF_EXPERT, "expert", e), (RULE_SELF_CHECKLIST, "checklist", c)):
            diff = s - other if s is not None and other is not None else None
            gaps.append({"rule_id": rule, "left": "self", "right": right, "diff": show(diff),
                         "flag": diff is not None and diff >= GAP_THRESHOLD})
        criteria.append({
            "key": key, "name_uk": meta["name_uk"], "component_code": meta["component_code"],
            "self": {"level": show(s), "responses": self_data[key]["responses"], "status": self_data[key]["status"]},
            "self_by_category": self_data[key]["by_category"],
            "expert": {"level": show(e), "experts": expert[key]["experts"], "status": expert[key]["status"]},
            "checklist": {"level": show(c), "items_total": check[key]["items_total"],
                          "items_confirmed": check[key]["items_confirmed"], "status": check[key]["status"]},
            "objective": [{"name": i["name"], "value": i["value"], "target": i["target"],
                           "confirmed": i["confirmed"]} for i in own],
            "gaps": gaps,
        })

        def add(rule: str, basis: dict) -> None:
            recommendations.append({
                "id": fingerprint({"assessment_id": assessment["id"], "methodology": VERSION,
                                   "rule_id": rule, "criterion": key})[:16],
                "rule_id": rule, "criterion": key, "component_code": meta["component_code"],
                "basis": basis, "text": TEXTS[rule].format(name=meta["name_uk"]),
                "requires_human_decision": True})

        base, source = (e, "expert") if e is not None else (s, "self")
        if base is not None and base < LOW_THRESHOLD:
            add(RULE_LOW, {"source": source, "level": show(base), "threshold": 3})
        for gap in gaps:
            if gap["flag"]:
                add(gap["rule_id"], {"self": show(s), gap["right"]: show(e if gap["right"] == "expert" else c),
                                     "diff": gap["diff"], "threshold": 1})
        confirmed = [i for i in own if i["confirmed"]]
        below = [i for i in confirmed if Fraction(str(i["value"])) < Fraction(str(i["target"]))]
        if s is not None and s >= BELOW_TARGET_SELF_MIN and below:
            add(RULE_BELOW_TARGET, {"self": show(s), "self_min": 3.5,
                                    "indicators": [{"name": i["name"], "value": i["value"], "target": i["target"]}
                                                   for i in below]})
        if s is not None and s >= UNCONFIRMED_SELF_MIN and not confirmed:
            add(RULE_UNCONFIRMED, {"self": show(s), "self_min": 4, "indicators_total": len(own),
                                   "indicators_confirmed": 0})

    overall = self_data[OVERALL_CRITERION]
    return {
        "assessment": assessment, "methodology_version": VERSION, "level_rule": LEVEL_RULE,
        "min_group_size": k, "synthetic_only": True, "official": False,
        "visible_categories": visible, "suppressed": suppressed,
        "criteria": criteria,
        "overall_self_declared": {"level": show(overall["level"]), "responses": overall["responses"],
                                  "status": overall["status"],
                                  "expert_level": show(expert[OVERALL_CRITERION]["level"])},
        "indices": {source: show(_index([data[key]["exact"] for key in INDEX_CRITERIA]))
                    for source, data in (("self", self_data), ("expert", expert), ("checklist", check))},
        "recommendations": recommendations,
    }
