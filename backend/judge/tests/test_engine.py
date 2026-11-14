"""규칙 엔진 테스트: python -m unittest discover -s tests"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapter import to_engine_facts  # noqa: E402
from fault_engine import judge, load_catalog, load_rules  # noqa: E402

RULES, CATALOG = load_rules(), load_catalog()


def base_facts():
    """차14-1 기본 상황 (엔진 형식). 모든 판단 값을 '해당 없음'으로 채워 기본 비율만 나오게 함"""
    common = {"user_factors": [], "speed_over_limit_kmh": 0, "entry_speed_to_limit": 0.3,
              "entry_speed": 0.01, "entry_speed_ratio": 1.0, "entry_lead_sec": 0.0,
              "damage_severity": "minor", "damage_enlarged": False, "_sources": {}}
    return {
        "schema_version": "2.0", "video": "test.mp4",
        "scene": {"location": "intersection", "junction_type": "cross",
                  "road_width": "equal", "road_class": "side_street"},
        "signal": {"state": "none"},
        "vehicles": [
            {**copy.deepcopy(common), "track_id": "3", "cls": "car", "entry_from": "south",
             "movement": "right_turn", "wide_turn": False},
            {**copy.deepcopy(common), "track_id": "5", "cls": "car", "entry_from": "east",
             "movement": "straight", "off_right_side": False},
        ],
        "collision": {"frame": 100, "between": ["3", "5"]},
    }


def veh(f, tid):
    return next(v for v in f["vehicles"] if v["track_id"] == tid)


def run(f, rules=RULES):
    return judge(f, rules, CATALOG)


class TestCh14_1(unittest.TestCase):
    def test_base(self):
        r = run(base_facts())
        self.assertEqual(r["rule_id"], "차14-1")
        self.assertEqual(r["fault"], {"A": 70, "B": 30})

    def test_precedent_keep_right(self):
        """참고판례 2019나51699: B 오른쪽 통행 불이행 → 60:40"""
        f = base_facts()
        veh(f, "5")["off_right_side"] = True
        r = run(f)
        self.assertEqual(r["fault"], {"A": 60, "B": 40})

    def test_signal_present_not_matched(self):
        f = base_facts()
        f["signal"]["state"] = "red"
        self.assertFalse(run(f)["supported"])


class TestOverlapRules(unittest.TestCase):
    def test_notable_cap_20(self):
        """현저한 과실 3개(+30)여도 합계 20%까지 (총설 p.21 ⑤)"""
        f = base_facts()
        veh(f, "3")["user_factors"] = ["phone", "inattention", "dark_tint"]
        r = run(f)
        self.assertEqual(r["fault"], {"A": 90, "B": 10})
        self.assertTrue(any("상한" in e["reason"] for e in r["excluded_modifiers"]))

    def test_grave_over_notable(self):
        """중대한 과실과 현저한 과실이 겹치면 중대한 과실만 (총설 p.21 ④)"""
        f = base_facts()
        veh(f, "3")["user_factors"] = ["phone", "drunk_0.03_plus"]
        r = run(f)
        self.assertEqual(r["fault"], {"A": 90, "B": 10})
        labels = [m["label"] for m in r["applied_modifiers"]]
        self.assertTrue(any("0.03% 이상" in x for x in labels))
        self.assertFalse(any("휴대전화" in x for x in labels))

    def test_speed_group_exclusive(self):
        """서행불이행과 속도위반은 중복 적용 불가 (p.135)"""
        f = base_facts()
        v = veh(f, "5")
        v["entry_speed_to_limit"] = 0.9
        v["speed_over_limit_kmh"] = 10
        v["avoidable_at_limit"] = True
        r = run(f)
        self.assertEqual(r["fault"], {"A": 60, "B": 40})
        self.assertEqual(len(r["excluded_modifiers"]), 1)

    def test_speeding_without_causation(self):
        """속도위반이어도 제한속도였어도 못 피했으면 비적용 (총설 p.16)"""
        f = base_facts()
        v = veh(f, "5")
        v["speed_over_limit_kmh"] = 30
        v["avoidable_at_limit"] = False
        r = run(f)
        self.assertEqual(r["fault"], {"A": 70, "B": 30})
        self.assertEqual(r["not_applied_modifiers"][0]["reason"], "위반은 있으나 사고와 인과관계 없음")

    def test_two_wheeler_reduction(self):
        f = base_facts()
        v = veh(f, "5")
        v["cls"] = "two_wheeler"
        v["damage_severity"] = "severe"
        self.assertEqual(run(f)["fault"], {"A": 80, "B": 20})

    def test_two_wheeler_with_grave_not_reduced(self):
        f = base_facts()
        v = veh(f, "5")
        v["cls"] = "two_wheeler"
        v["damage_severity"] = "severe"
        v["user_factors"] = ["no_license"]
        r = run(f)
        self.assertEqual(r["fault"], {"A": 50, "B": 50})
        self.assertTrue(any("중대한 과실" in e["reason"] for e in r["excluded_modifiers"]))

    def test_zero_base_order(self):
        """기본 0:100이면 0인 쪽 먼저, 상대가 100% 미만일 때만 상대 수정요소 (총설 p.21 ②)"""
        rules = copy.deepcopy(RULES)
        next(x for x in rules["rules"] if x["id"] == "차14-1")["base"] = {"A": 0, "B": 100}
        f = base_facts()
        veh(f, "5")["user_factors"] = ["phone"]          # B 현저한 과실 (+10)
        r = run(f, rules)
        self.assertEqual(r["fault"], {"A": 0, "B": 100})   # A에 수정요소가 없으니 B 것은 미적용
        veh(f, "3")["user_factors"] = ["inattention"]    # A 현저한 과실 (+10)
        r = run(f, rules)
        self.assertEqual(r["fault"], {"A": 0, "B": 100})   # A +10 → 10:90, 그다음 B +10 → 0:100

    def test_user_input_needs_proof(self):
        f = base_facts()
        v = veh(f, "3")
        v["user_factors"] = ["phone"]
        v["_sources"] = {"user_factors": "user"}
        r = run(f)
        self.assertTrue(r["applied_modifiers"][0]["needs_proof"])
        self.assertTrue(r["notes"])


class TestAdapterV02(unittest.TestCase):
    def test_v02_sample_with_assumptions(self):
        raw = {
            "schema_version": "0.2", "video": "data/videos/x.mp4", "fps": 15.0,
            "road_type": "no_center_line",
            "collision": {"frame": 109, "t": 7.267, "a": "22", "b": "28"},
            "parties": {
                "22": {"cls": "vehicle", "origin_zone": "side_entry_left",
                       "enter_road": {"frame": 59, "t": 3.933}, "movement": "unknown",
                       "heading_start": [0.0198, 0.0004], "approach_speed": 0.016},
                "28": {"cls": "two_wheeler", "origin_zone": "road", "movement": "straight",
                       "heading_start": [-0.0846, -0.1838], "approach_speed": 0.064},
            },
            "events": [],
        }
        assumptions = {"scene": {"location": "intersection", "junction_type": "t", "road_width": "equal"},
                       "signal": {"state": "none"}, "intersection": {"side_entry_is_road": True},
                       "parties": {"22": {"movement": "right_turn"}}}
        f, assumed = to_engine_facts(raw, assumptions)
        r = run(f)
        self.assertEqual(r["rule_id"], "차14-1")
        self.assertEqual(r["roles"]["A"]["track_id"], "22")
        self.assertEqual(r["fault"], {"A": 70, "B": 30})
        self.assertEqual(r["fault_if_pending_applied"], {"A": 60, "B": 40})

    def test_v03_value_objects(self):
        raw = {
            "schema_version": "0.3", "video": "y.mp4",
            "road": {"location": "intersection", "junction_type": "cross", "road_width": "equal",
                     "road_class": "side_street", "signal_present": False, "speed_limit_kmh": 30},
            "collision": {"a": "1", "b": "2"},
            "parties": {
                "1": {"cls": "car", "movement": {"value": "right_turn", "source": "user", "evidence_frame": 50},
                      "heading_start": [1, 0], "intersection_entry": {"t": 2.0},
                      "intersection_entry_speed_kmh": 10},
                "2": {"cls": "car", "movement": "straight", "heading_start": [0, -1],
                      "intersection_entry": {"t": 4.0}, "intersection_entry_speed_kmh": 25,
                      "off_right_side": {"value": False, "source": "model", "evidence_frame": 80}},
            },
        }
        f, _ = to_engine_facts(raw, {})
        r = run(f)
        self.assertEqual(r["rule_id"], "차14-1")
        ids = [m["id"] for m in r["applied_modifiers"]]
        self.assertIn("B:slow_violation", ids)       # 진입 속도 25/30 = 0.83 ≥ 0.5 → 감속 불이행
        self.assertIn("A:clear_first_entry", ids)    # 2초 앞섬, 속도 비율 10/25 = 0.4 ≤ 1.3
        self.assertEqual(r["fault"], {"A": 50, "B": 50})  # A -10, B +10 → 둘 다 A 쪽 비율을 낮춤

class TestEntryFrom(unittest.TestCase):
    def test_compass_overrides_heading(self):
        """두 차 모두 entry_from이 있으면 화면 방향 벡터가 틀려도 방위로 판단"""
        f = base_facts()                       # A south(우회전), B east(A의 오른쪽) → 차14-1
        for v in f["vehicles"]:
            v["heading"] = [1, 0]              # 화면 방향은 일부러 같은 방향으로 망가뜨림
        self.assertEqual(run(f)["rule_id"], "차14-1")
        veh(f, "5")["entry_from"] = "west"     # 방위상 A의 왼쪽 → 차14-1 아님
        self.assertNotEqual(run(f).get("rule_id"), "차14-1")

    def test_adapter_passes_entry_from(self):
        raw = {"schema_version": "0.3", "video": "z.mp4",
               "road": {"location": "intersection", "junction_type": "cross", "road_width": "equal",
                        "road_class": "side_street", "signal_present": False},
               "collision": {"a": "1", "b": "2"},
               "parties": {"1": {"cls": "car", "movement": "right_turn", "entry_from": "appr_s", "heading_start": [1, 0]},
                           "2": {"cls": "car", "movement": "straight", "entry_from": {"value": "E", "source": "model"},
                                 "heading_start": [1, 0]}}}
        f, _ = to_engine_facts(raw, {})
        self.assertEqual([v["entry_from"] for v in f["vehicles"]], ["south", "east"])
        self.assertEqual(run(f)["rule_id"], "차14-1")


if __name__ == "__main__":
    unittest.main()
