"""보행자·자전거 상대 처리 시험 (B 요청 2026-11-14)

  python -m pytest tests/test_bb_ped_bike_facts.py

1. 상대가 보행자·자전거면 entry_from·movement·lead_order를 내지 않는다 (차대차 사실 섞임 방지)
2. 진행률 함수를 track_video.run처럼 (처리한 프레임 수, 전체 프레임 수) 두 인자로 부른다
3. 횡단보도 판정은 사고 3초 전까지 사람 박스가 잡힌 마지막 N개 프레임을 쓰고, 3개 미만이면 판단하지 않는다 (질문)
"""
import copy
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from src.blackbox import video_analyzer as va
from src.blackbox.video_lib import scene_crosswalk as sc


def out_with(cls, status="ok"):
    return {
        "status": status,
        "facts": {"parties": {
            "ego": {"movement": {"value": "straight", "source": "model"}},
            "other": {"cls": {"value": cls, "source": "model", "confidence": 0.8},
                      "entry_from": {"value": "south", "source": "model"},
                      "movement": {"value": None, "source": "model", "guess": "lane_change"},
                      "lead_order": {"value": "leading", "source": "model"}}}},
    }


class DropCarFactsTest(unittest.TestCase):
    def test_person_and_bicycle_lose_car_only_facts(self):
        for cls in ("person", "pedestrian", "bicycle"):
            out = out_with(cls)
            va._drop_car_facts_for_ped_bike(out)
            other = out["facts"]["parties"]["other"]
            for key in va.CAR_ONLY_PARTY_KEYS:
                self.assertNotIn(key, other, f"{cls}: {key}")
            self.assertEqual(other["cls"]["value"], cls)          # 종류는 그대로

    def test_car_keeps_facts(self):
        out = out_with("car")
        before = copy.deepcopy(out)
        va._drop_car_facts_for_ped_bike(out)
        self.assertEqual(out, before)

    def test_ego_untouched_and_failed_output_skipped(self):
        out = out_with("person")
        va._drop_car_facts_for_ped_bike(out)
        self.assertIn("movement", out["facts"]["parties"]["ego"])
        failed = {"status": "failed", "facts": None}
        va._drop_car_facts_for_ped_bike(failed)
        self.assertEqual(failed, {"status": "failed", "facts": None})

    def test_no_collision_status_also_cleaned(self):
        out = out_with("bicycle", status="no_collision")
        va._drop_car_facts_for_ped_bike(out)
        self.assertNotIn("lead_order", out["facts"]["parties"]["other"])


class TrackProgressTest(unittest.TestCase):
    def test_called_like_track_video_with_two_args(self):
        seen = []
        fn = va._track_progress(seen.append)
        fn(75, 150)                       # track_video.run: progress(frame_no, total)
        fn(150, 150)
        self.assertAlmostEqual(seen[0], 0.5 * va.TRACK_SHARE)
        self.assertAlmostEqual(seen[1], va.TRACK_SHARE)

    def test_zero_total_does_not_divide_by_zero(self):
        va._track_progress(lambda n: None)(0, 0)


class _Boxes:
    def __init__(self, xyxy, conf):
        self.cls = np.zeros(len(xyxy))
        self.conf = np.array(conf)
        self.xyxy = type("X", (), {"cpu": lambda s: type("Y", (), {"numpy": lambda s2: np.array(xyxy, dtype=float).reshape(-1, 4)})()})()


class _Result:
    names = {0: "crosswalk"}

    def __init__(self, xyxy, conf):
        self.boxes = _Boxes(xyxy, conf)


class _Model:
    """프레임마다 같은 횡단보도 박스 하나를 돌려주고, 받은 프레임 수를 센다"""
    def __init__(self):
        self.calls = []

    def predict(self, imgs, **kw):
        self.calls.append(len(imgs))
        return [_Result([[0, 100, 200, 160]], [0.9]) for _ in imgs]


def frames_at(times):
    return [(t, np.zeros((4, 4, 3), np.uint8)) for t in times]


class CrosswalkLastNTest(unittest.TestCase):
    T = 5.0

    def feet(self, times):
        return {t: (100.0, 130.0) for t in times}    # 박스 안

    def test_uses_last_n_inside_three_seconds(self):
        times = [self.T - 3.5, self.T - 2.8, self.T - 2.4, self.T - 2.0, self.T - 1.6, self.T - 1.4,
                 self.T - 1.2, self.T - 1.0, self.T - 0.8]
        m = _Model()
        out = sc.relate_crosswalk(m, frames_at(times), self.feet(times), self.T)
        self.assertEqual(m.calls, [sc.CW_LAST_N])                 # 3초 밖(−3.5)은 빼고, 남은 8개 중 마지막 N개만
        self.assertEqual(out["parties.other.ped_place"].value, "crosswalk")

    def test_person_lost_near_impact_still_decides(self):
        # 사람 박스가 사고 직전(−1초 안)에는 하나도 없고 −2.5~−1.5초에만 있는 영상 (video2 모양)
        times = [self.T - 2.5, self.T - 2.2, self.T - 1.9, self.T - 1.6]
        m = _Model()
        out = sc.relate_crosswalk(m, frames_at(times), self.feet(times), self.T)
        self.assertEqual(out["parties.other.ped_place"].value, "crosswalk")

    def test_fewer_than_three_asks_question(self):
        times = [self.T - 2.0, self.T - 1.5]
        m = _Model()
        self.assertEqual(sc.relate_crosswalk(m, frames_at(times), self.feet(times), self.T), {})
        self.assertEqual(m.calls, [])                              # 모델도 부르지 않는다

    def test_only_old_frames_outside_window_asks_question(self):
        times = [self.T - 5.0, self.T - 4.5, self.T - 4.0]
        m = _Model()
        self.assertEqual(sc.relate_crosswalk(m, frames_at(times), self.feet(times), self.T), {})


if __name__ == "__main__":
    unittest.main()
