"""A가 내보내는 당사자 종류(cls)로 B 판정 모듈이 사고 유형을 고르는지 (judge hmtm-0.1.0)

  python -m unittest tests.test_judge_category -v

A 형식 facts(0.3) → judge_bridge.judge(파일 경로) → B adapter → B 엔진을 그대로 거친다.
judge_bridge가 규칙을 직접 넘기면 늘 차대차가 되므로, 그 회귀를 막는 시험이기도 하다. 판정 모듈이 없으면 건너뜀.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.app import answers, chapters, judge_bridge

JUDGE = os.path.join(ROOT, "judge")


def facts(cls_b, cls_a="car"):
    return {"schema_version": "0.3", "video": "test", "fps": 15,
            "road": {"location": {"value": "intersection", "source": "model"}},
            "collision": {"frame": 50, "t": 3.3, "a": "1", "b": "2", "zone": "intersection"},
            "parties": {"1": {"cls": {"value": cls_a, "source": "model"}, "movement": "straight"},
                        "2": {"cls": {"value": cls_b, "source": "model"}, "movement": "straight"}},
            "events": [], "unknowns": []}


def judge(raw, assumptions=None):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(raw, f)
    try:
        return judge_bridge.judge(f.name, assumptions or {}, JUDGE)
    finally:
        os.remove(f.name)


@unittest.skipUnless(os.path.exists(os.path.join(JUDGE, "fault_engine.py")), "판정 모듈이 없음")
class JudgeCategory(unittest.TestCase):
    def category(self, raw, assumptions=None):
        return judge(raw, assumptions)["result"].get("accident_category")

    def test_pedestrian(self):   # 영상 파이프라인(finalize_tracks)의 이름
        self.assertEqual(self.category(facts("pedestrian")), "car_pedestrian")

    def test_person(self):       # 블랙박스 분석기 계약(src/blackbox/analyzer.py CLASSES)의 이름
        self.assertEqual(self.category(facts("person")), "car_pedestrian")

    def test_bicycle(self):
        self.assertEqual(self.category(facts("bicycle")), "car_bicycle")

    def test_farm_machine_from_user_answer(self):   # 농기계는 탐지하지 않고 종류 질문 답으로만 들어옴
        asm = {"parties": {"2": {"cls": "farm_machine"}}}
        self.assertEqual(self.category(facts("car"), asm), "car_bicycle")

    def test_car_and_two_wheeler_stay_car_car(self):
        for cls in ("car", "truck", "bus", "two_wheeler"):
            self.assertEqual(self.category(facts(cls)), "car_car", cls)

    def test_bridge_fields(self):
        out = judge(facts("pedestrian"))
        with open(os.path.join(JUDGE, "VERSION"), encoding="utf-8") as f:
            self.assertEqual(out["judge_version"], f.read().strip())   # 문자열 버전(hmtm-0.1.0)을 그대로 넘김
        self.assertIn(out["status"], ("ok", "no_rule"))


@unittest.skipUnless(os.path.exists(os.path.join(JUDGE, "fault_engine.py")), "판정 모듈이 없음")
class ChapterAnswersReachJudge(unittest.TestCase):
    """chapters.py 질문 답 → answers.to_assumptions → B adapter: B가 읽는 이름(ped_place 등)으로 닿는지 (judge hmtm-0.1.1)"""

    def engine_party(self, answers_):
        raw = facts("pedestrian")
        adapter = judge_bridge.load(JUDGE)[0]
        engine_facts, _ = adapter.to_engine_facts(raw, answers.to_assumptions(raw, answers_))
        return engine_facts["vehicles"][1]

    def test_place_and_signal(self):
        b = self.engine_party({"parties.2.crossing_place": "on_crosswalk",
                               "parties.2.ped_signal_at_crossing": "green_flashing"})
        self.assertEqual((b["ped_place"], b["_sources"]["ped_place"]), ("crosswalk", "user"))
        self.assertEqual(b["ped_signal_at_crossing"], "flashing_green")
        self.assertIs(b["crossing_on_crosswalk"], True)   # 차53-1용 값은 그대로

    def test_choice_options_are_known(self):
        # chapters.py 보기가 바뀌면 변환표도 같이 봐야 함
        adapter = judge_bridge.load(JUDGE)[0]
        self.assertLessEqual(set(adapter.CROSSING_PLACE_TO_PED_PLACE), set(chapters.PLACE_OPTIONS))
        self.assertLessEqual(set(adapter.PED_SIGNAL_VALUES), set(chapters.PED_SIGNAL_OPTIONS))


if __name__ == "__main__":
    unittest.main()
