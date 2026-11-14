"""사고 유형 판단과 유형별 규칙 파일 선택 (hmtm-0.1.0)"""
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fault_engine import CATEGORIES, detect_category, judge, load_category  # noqa: E402


def facts(*classes, **extra):
    vs = [{"track_id": str(i + 1), "cls": c} for i, c in enumerate(classes)]
    return {"video": "t", "vehicles": vs,
            "collision": {"between": [v["track_id"] for v in vs]}, **extra}


class CategoryTest(unittest.TestCase):
    def test_car_car(self):
        self.assertEqual(detect_category(facts("car", "truck"))[0], "car_car")
        self.assertEqual(detect_category(facts("car", "two_wheeler"))[0], "car_car")

    def test_missing_cls_keeps_old_behavior(self):
        self.assertEqual(detect_category(facts(None, "car"))[0], "car_car")

    def test_pedestrian(self):
        self.assertEqual(detect_category(facts("car", "person"))[0], "car_pedestrian")
        self.assertEqual(detect_category(facts("two_wheeler", "person"))[0], "car_pedestrian")

    def test_bicycle_and_farm_machine(self):
        self.assertEqual(detect_category(facts("car", "bicycle"))[0], "car_bicycle")
        self.assertEqual(detect_category(facts("truck", "farm_machine"))[0], "car_bicycle")

    def test_bicycle_vs_pedestrian_out_of_scope(self):
        self.assertIsNone(detect_category(facts("bicycle", "person"))[0])
        self.assertFalse(judge(facts("bicycle", "person"))["supported"])

    def test_only_collision_parties_count(self):
        f = facts("car", "car", "person")
        f["collision"]["between"] = ["1", "2"]   # 화면에 보행자가 있어도 충돌 당사자가 아니면 차대차
        self.assertEqual(detect_category(f)[0], "car_car")

    def test_explicit_category(self):
        self.assertEqual(detect_category(facts("car", "car", accident_category="car_pedestrian"))[0],
                         "car_pedestrian")

    def test_unmapped_category_reports(self):
        # 매핑되지 않은 유형은 이제 없으므로, 규칙 파일이 없는 경우를 임시로 만들어 확인
        with mock.patch.dict(CATEGORIES["car_bicycle"], {"rules": "없는_규칙_파일.json"}):
            r = judge(facts("car", "bicycle"))
        self.assertFalse(r["supported"])
        self.assertEqual(r["accident_category"], "car_bicycle")
        self.assertIn("매핑되지 않았", r["message"])

    def test_all_categories_mapped(self):
        for name in CATEGORIES:
            rules, _ = load_category(name)
            self.assertTrue(rules and rules.get("rules"), name)
            self.assertEqual(rules["category"], name)

    def test_pedestrian_file_loads(self):
        rules, catalog = load_category("car_pedestrian")
        self.assertEqual(rules["category"], "car_pedestrian")
        self.assertTrue(catalog["modifiers"])

    def test_car_rules_tagged(self):
        rules, _ = load_category("car_car")
        self.assertEqual(rules["category"], "car_car")
        self.assertEqual(len(rules["rules"]), 124)

    def test_all_category_files_named(self):
        self.assertEqual(set(CATEGORIES), {"car_car", "car_pedestrian", "car_bicycle"})


if __name__ == "__main__":
    unittest.main()
