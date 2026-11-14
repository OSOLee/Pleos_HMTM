"""차대보행자 도표 (보1~보36, rules_pedestrian.json) — hmtm-0.1.0

- 도표마다 조건을 채운 facts → 그 도표가 선택되고 base 비율이 나오는지
- 수정요소 사례 (HANDOFF "확인된 사례")
A = 자동차, B = 보행자. 비율은 원문을 옮긴 값이라 시험이 실패해도 숫자를 고치지 않는다.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fault_engine import judge, load_category  # noqa: E402

RULES, CATALOG = load_category("car_pedestrian")
BY_ID = {r["id"]: r for r in RULES["rules"]}


def _setv(obj, path, val):
    ks = path.split(".")
    for k in ks[:-1]:
        obj = obj.setdefault(k, {})
    obj[ks[-1]] = val


def _val(c):
    op, v = c["op"], c["value"]
    if op == "in":
        return v[0]
    if op == ">":
        return v + 1
    if op == "<":
        return v - 1
    if op == "contains":
        return [v]
    return v   # ==, <=, >=


def _apply(c, facts, target):
    if "any" in c:
        return _apply(c["any"][0], facts, target)
    if "all" in c:
        for x in c["all"]:
            _apply(x, facts, target)
        return
    if c.get("of") == "facts":
        _setv(facts, c["fact"], _val(c))
    elif c["fact"] == "dist_from_crosswalk_m" and c["op"] == "<=" and target.get(c["fact"]) is not None:
        pass   # 범위의 하한을 이미 넣었으면 상한으로 덮지 않음
    else:
        target[c["fact"]] = _val(c)


def chart_facts(rule_id):
    """도표 조건을 채운 엔진 facts. 반환 (facts, A, B)"""
    r = BY_ID[rule_id]
    a, b = {"track_id": "1"}, {"track_id": "2"}
    facts = {"video": "t", "vehicles": [a, b], "collision": {"between": ["1", "2"]}}
    for c in r["applies_when"].get("scene", []):
        _apply(c, facts, facts)
    for c in r["applies_when"]["roles"]["A"]["where"]:
        _apply(c, facts, a)
    for c in r["applies_when"]["roles"]["B"]["where"]:
        _apply(c, facts, b)
    d = b.get("dist_from_crosswalk_m")
    if d is not None and d <= 30:
        b["dist_from_crosswalk_m"] = min(d, 8)   # 10m 이내 → 거리 가산이 붙지 않는 값
    return facts, a, b


def fault(res):
    return res.get("rule_id"), (res["fault"]["A"], res["fault"]["B"]) if res.get("supported") else None


class PedestrianFileTest(unittest.TestCase):
    def test_rule_count_and_category(self):
        self.assertEqual(RULES["category"], "car_pedestrian")
        self.assertEqual(len(RULES["rules"]), 45)

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
                facts, _, _ = chart_facts(r["id"])
                res = judge(facts)
                self.assertEqual(res.get("accident_category"), "car_pedestrian")
                self.assertEqual(fault(res), (r["id"], (r["base"]["A"], r["base"]["B"])), res.get("message"))


class PedestrianModifierTest(unittest.TestCase):
    def check(self, rule_id, expect, scene=None, a=None, b=None):
        facts, _, _ = chart_facts(rule_id)
        facts = copy.deepcopy(facts)
        fa, fb = facts["vehicles"]
        facts.setdefault("scene", {}).update(scene or {})
        fa.update(a or {})
        fb.update(b or {})
        self.assertEqual(fault(judge(facts)), (rule_id, expect))

    def test_b1_night_child_in_protection_zone(self):
        # 어린이 −5는 보호구역 −15와 같은 묶음이라 하나만 (큰 쪽)
        self.check("보1", (40, 60), scene={"night": True},
                   b={"vulnerable_type": "child", "in_own_protection_zone": True})

    def test_b1_night_and_view_obstructed_one_only(self):
        self.check("보1", (25, 75), scene={"night": True, "view_obstructed": True})

    def test_b14_na_20m_and_barrier(self):
        self.check("보14(나)", (30, 70), scene={"crossing_prohibition": "barrier"},
                   b={"dist_from_crosswalk_m": 20})

    def test_b8_speeding_15_avoidable(self):
        # 이 장은 10km/h 이상부터 현저한 과실
        self.check("보8", (40, 60), a={"speed_over_limit_kmh": 15, "avoidable_at_limit": True})

    def test_b8_speeding_5_not_fault(self):
        self.check("보8", (30, 70), a={"speed_over_limit_kmh": 5, "avoidable_at_limit": True})

    def test_b8_drunk_and_phone_grave_only(self):
        # 중대한 과실(음주 0.03% 이상)이 있으면 현저한 과실(휴대전화)은 더하지 않음
        self.check("보8", (50, 50), a={"user_factors": ["drunk_0.03_plus", "phone"]})

    def test_b5_night_not_applicable(self):
        self.check("보5", (100, 0), scene={"night": True})

    def test_b36_shoulder_and_no_license(self):
        self.check("보36", (80, 20), a={"user_factors": ["no_license"]}, b={"on_shoulder": True})


if __name__ == "__main__":
    unittest.main()
