"""차대자전거 도표 (거1~거43, rules_bicycle.json) — hmtm-0.1.0

- 도표마다 조건을 채운 facts → 그 도표가 선택되고 base 비율이 나오는지
- 수정요소 사례 (HANDOFF "확인된 사례")
A = 자전거(농기계 포함), B = 자동차. 비율은 원문을 옮긴 값이라 시험이 실패해도 숫자를 고치지 않는다.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fault_engine import judge, load_category  # noqa: E402

RULES, CATALOG = load_category("car_bicycle")
BY_ID = {r["id"]: r for r in RULES["rules"]}
# B(자동차)가 A(자전거) 기준으로 들어오는 쪽. A는 남쪽에서 들어온다고 둔다
REL = {"enters_from_right_of": "east", "enters_from_left_of": "west", "enters_from_opposite_of": "north",
       "enters_from_side_of": "east", "enters_same_direction_as": "south"}


def _setv(obj, path, val):
    ks = path.split(".")
    for k in ks[:-1]:
        obj = obj.setdefault(k, {})
    obj[ks[-1]] = val


def _val(c):
    op, v = c["op"], c["value"]
    if op == "in":
        return v[0]
    if op == "!=":
        return "straight" if v == "intersection" else "x"
    if op == ">":
        return v + 1
    if op == "<":
        return v - 1
    if op == "contains":
        return [v]
    return v   # ==, <=, >=


def _apply(c, facts, target):
    if "all" in c:
        for x in c["all"]:
            _apply(x, facts, target)
        return
    if "any" in c:
        return _apply(c["any"][0], facts, target)
    if c.get("of") == "facts":
        _setv(facts, c["fact"], _val(c))
    else:
        target[c["fact"]] = _val(c)


def chart_facts(rule_id):
    """도표 조건을 채운 엔진 facts"""
    r = BY_ID[rule_id]
    a, b = {"track_id": "1", "entry_from": "south"}, {"track_id": "2"}
    facts = {"video": "t", "vehicles": [a, b], "collision": {"between": ["1", "2"]}}
    for c in r["applies_when"].get("scene", []):
        _apply(c, facts, facts)
    for c in r["applies_when"]["roles"]["A"]["where"]:
        _apply(c, facts, a)
    for c in r["applies_when"]["roles"]["B"]["where"]:
        _apply(c, facts, b)
    rel = r["applies_when"]["roles"]["B"].get("relations", [{"type": "enters_from_side_of"}])[0]["type"]
    b["entry_from"] = REL[rel]
    return facts


def fault(res):
    return res.get("rule_id"), (res["fault"]["A"], res["fault"]["B"]) if res.get("supported") else None


class BicycleFileTest(unittest.TestCase):
    def test_rule_count_and_category(self):
        self.assertEqual(RULES["category"], "car_bicycle")
        self.assertEqual(len(RULES["rules"]), 55)

    def test_modifier_refs_exist_and_unique(self):
        ids = {m["id"] for m in CATALOG["modifiers"]}
        for r in RULES["rules"]:
            keys = [(m["ref"], m["party"]) for m in r["modifiers"]]
            self.assertEqual(len(keys), len(set(keys)), r["id"])
            for m in r["modifiers"]:
                self.assertIn(m["ref"], ids, (r["id"], m["ref"]))

    def test_base_sums_to_100(self):
        for r in RULES["rules"]:
            self.assertEqual(r["base"]["A"] + r["base"]["B"], 100, r["id"])

    def test_not_verified_yet(self):
        for r in RULES["rules"]:
            self.assertIs(r["source"]["verified"], False, r["id"])

    def test_every_chart_selected_with_base(self):
        for r in RULES["rules"]:
            with self.subTest(rule=r["id"]):
                res = judge(chart_facts(r["id"]))
                self.assertEqual(res.get("accident_category"), "car_bicycle")
                self.assertEqual(fault(res), (r["id"], (r["base"]["A"], r["base"]["B"])), res.get("message"))


class BicycleModifierTest(unittest.TestCase):
    def check(self, rule_id, expect, scene=None, a=None, b=None):
        facts = copy.deepcopy(chart_facts(rule_id))
        fa, fb = facts["vehicles"]
        facts.setdefault("scene", {}).update(scene or {})
        fa.update(a or {})
        fb.update(b or {})
        self.assertEqual(fault(judge(facts)), (rule_id, expect))

    def test_g1_2_child_bicycle(self):
        self.check("거1-2", (80, 20), a={"vulnerable_type": "child"})

    def test_g43_3_no_helmet(self):
        # 거43-3은 보호장구 미착용 상황 요소만 (현저한 과실 '안전모 미착용'과 중복 없음)
        self.check("거43-3", (20, 80), a={"user_factors": ["no_helmet"]})

    def test_g4_1_car_started_after_stop(self):
        self.check("거4-1", (20, 80), b={"stopped_before_entry": True})

    def test_g2_2_car_speeding_5_not_fault(self):
        self.check("거2-2", (60, 40), b={"speed_over_limit_kmh": 5, "avoidable_at_limit": True})

    def test_g31_2_car_sudden_stop(self):
        self.check("거31-2", (70, 30), b={"sudden_stop_without_reason": True})

    def test_drowsy_is_grave(self):
        rule = BY_ID["거1-2"]
        self.assertIn(("bike_car_drowsy", "B", 20), [(m["ref"], m["party"], m["delta"]) for m in rule["modifiers"]])
        self.check("거1-2", (70, 30), b={"user_factors": ["drowsy"]})


if __name__ == "__main__":
    unittest.main()
