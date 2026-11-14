"""가감 요소 근거 사실 → 질문 키 대응표 시험 (src/vehicle/adapter.fact_keys, notes C10)

  python -m pytest tests/test_modifier_source.py

엔진 사실 이름과 질문 키가 다를 때(user_factors ← driver_factors, entry_lead_sec ← intersection_entry_order 등)
가감 요소 출처가 default로 나오던 문제. 블랙박스·차량 사건이 같은 표를 쓴다.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from src.vehicle import adapter as va


class FactKeys(unittest.TestCase):
    def test_direct_name(self):
        self.assertEqual(va.fact_keys("turn_signal_used", "ego"), ["parties.ego.turn_signal_used"])

    def test_renamed_facts(self):
        cases = {"user_factors": "parties.ego.driver_factors", "speed_over_limit_kmh": "parties.ego.driver_factors",
                 "slowed_before_entry": "parties.ego.stopped_before_entry", "on_wider_road": "road.wider_road",
                 "stop_sign": "road.stop_sign_side", "entry_lead_sec": "intersection_entry_order",
                 "lead_order": "pair.lead_order", "ped_place": "parties.ego.crosswalk_distance",
                 "dist_from_crosswalk_m": "parties.ego.overpass_distance"}
        for fact, key in cases.items():
            with self.subTest(fact):
                self.assertIn(key, va.fact_keys(fact, "ego"))

    def test_other_prefix_is_other_party(self):
        """observed 키 "other.사실"은 가감 요소 당사자의 상대 사실"""
        self.assertEqual(va.fact_keys("other.movement", "ego")[0], "parties.other.movement")
        self.assertEqual(va.fact_keys("other.movement", "other")[0], "parties.ego.movement")

    def test_scene_and_special(self):
        self.assertIn("road.wider_road", va.fact_keys("facts.scene.road_width", "ego"))
        self.assertIn("road.signal_present", va.fact_keys("facts.signal.state", "ego"))
        self.assertIn("road.night", va.fact_keys("facts.scene.night", "ego"))
        self.assertIn("situation.special", va.fact_keys("sudden_lane_change", "other"))
        self.assertIn("situation.special", va.fact_keys("facts.scene.view_obstructed", "ego"))


class ModifierSource(unittest.TestCase):
    def test_driver_factors_user(self):
        """운전자 사정(driver_factors) 답으로 적용된 가감 요소(user_factors)는 출처 user (전에는 default)"""
        import test_bb_merge as m
        v = m.run("right_turn_left_straight", user={"parties.ego.driver_factors": ["phone"]})["view"]
        mod = [x for x in v["result"]["modifiers"] if x["facts"] == ["user_factors"]][0]
        self.assertEqual((mod["party"], mod["source"], mod["needs_proof"]), ("ego", "user", True))

    def test_vehicle_case_same_table(self):
        """차량 사건(view_result)도 같은 표"""
        verdict = {"status": "ok", "result": {
            "roles": {"A": {"track_id": "ego"}, "B": {"track_id": "other"}}, "rule_id": "x", "title": "x",
            "fault_by_track": {"ego": 50, "other": 50}, "base": {"A": 50, "B": 50},
            "applied_modifiers": [{"label": "l", "party": "A", "delta": 10, "observed": {"entry_lead_sec": 1.2}}]}}
        out = va.view_result(verdict, False, {"intersection_entry_order": {"value": "ego", "source": "user"}}, [])
        self.assertEqual(out["modifiers"][0]["source"], "user")


if __name__ == "__main__":
    unittest.main()
