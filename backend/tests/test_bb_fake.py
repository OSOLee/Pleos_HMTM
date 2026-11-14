"""가짜 블랙박스 분석기 시험 (docs/design-blackbox.md 2절)

  python -m pytest tests/test_bb_fake.py

시나리오 9개, 시나리오 고르기(요청 > 파일 이름 __scn- > 기본값), 영상 길이를 파일에서 읽기.
시험 영상은 테스트 안에서 OpenCV로 만든다.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from bb_common import make_video
from src.blackbox import analyzer, fake

SCENARIOS = ["right_turn_left_straight", "right_turn_motion", "left_turn_motion", "left_turn_motion_nosignal", "straight_motion_slowed", "straight_same_time", "left_turn_opposite", "rear_end_lead",
             "ego_reverse_video_wrong", "mostly_unknown", "no_collision", "no_collision_pick", "unsupported", "analyzer_broken",
             "ped_crosswalk_unsignalized", "bike_crossing_side"]
STATUS = {"no_collision": "no_collision", "no_collision_pick": "no_collision", "unsupported": "unsupported", "analyzer_broken": "failed"}


class Fake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hmtm_bbfake_")
        cls.video = make_video(os.path.join(cls.tmp, "20261109_143012_F.mp4"), seconds=6.0, fps=5.0)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_scenarios(self):
        self.assertEqual(fake.scenario_names(), sorted(SCENARIOS))
        for name in SCENARIOS:
            out = analyzer.run(self.video, scenario=name, name="fake")
            self.assertEqual(out["status"], STATUS.get(name, "ok"), name)
            self.assertEqual(out["analyzer"], {"name": "fake", "version": fake.VERSION})
            if name == "analyzer_broken":
                self.assertEqual(out["reason"], "analyzer_output_invalid")
            if name not in STATUS:
                self.assertIn("expect", fake.load_scenario(name)["fake"])

    def test_video_read_from_file_and_times_scaled(self):
        out = analyzer.run(self.video, scenario="straight_same_time", name="fake")
        self.assertEqual(out["video"]["frames"], 30)
        self.assertAlmostEqual(out["video"]["duration_s"], 6.0, places=2)
        self.assertEqual((out["video"]["width"], out["video"]["height"]), (64, 48))
        k = 6.0 / 30.0                       # 시나리오 영상 30초 → 실제 6초
        col = out["facts"]["collision"]
        self.assertAlmostEqual(col["t"], 18.2 * k, places=3)
        self.assertEqual(col["frame"], round(col["t"] * 5))
        self.assertAlmostEqual(out["facts"]["parties"]["other"]["intersection_entry"]["t"], 17.3 * k, places=3)
        self.assertAlmostEqual(out["ego_motion"]["jolt_t"][0], 18.2 * k, places=3)
        self.assertTrue(out["hints"]["fake"]["video_read"])

    def test_unreadable_video_keeps_scenario_values(self):
        bad = os.path.join(self.tmp, "broken.mp4")
        with open(bad, "wb") as f:
            f.write(b"not a video")
        out = analyzer.run(bad, scenario="right_turn_left_straight", name="fake")
        self.assertEqual(out["video"]["duration_s"], 30.0)
        self.assertEqual(out["facts"]["collision"]["t"], 18.2)
        self.assertFalse(out["hints"]["fake"]["video_read"])

    def test_choose_order(self):
        named = "20261109_143012_F__scn-rear_end_lead.mp4"
        self.assertEqual(fake.choose("mostly_unknown", named), ("mostly_unknown", "request"))
        self.assertEqual(fake.choose(None, named), ("rear_end_lead", "filename"))
        with mock.patch.dict(os.environ, {fake.ENV_DEFAULT: ""}):
            self.assertEqual(fake.choose(None, "plain.mp4"), (fake.DEFAULT_SCENARIO, "default"))
        with mock.patch.dict(os.environ, {fake.ENV_DEFAULT: "left_turn_opposite"}):
            self.assertEqual(fake.choose(None, "plain.mp4"), ("left_turn_opposite", "default"))
        out = analyzer.run(self.video, filename=named, name="fake")
        self.assertEqual(out["hints"]["fake"], dict(out["hints"]["fake"], scenario="rear_end_lead", chosen_by="filename"))

    def test_unknown_scenario_failed(self):
        out = analyzer.run(self.video, scenario="nope", name="fake")
        self.assertEqual((out["status"], out["reason"]), ("failed", "scenario_unknown"))
        out = analyzer.run(self.video, scenario="../rules", name="fake")
        self.assertEqual(out["reason"], "scenario_unknown")

    def test_env_selects_fake(self):
        with mock.patch.dict(os.environ, {analyzer.ENV: "FAKE"}):
            self.assertEqual(analyzer.get_analyzer().name, "fake")
        with mock.patch.dict(os.environ, {analyzer.ENV: ""}):
            self.assertEqual(analyzer.get_analyzer().name, "fake")

    def test_delay_reports_progress(self):
        seen = []
        scn = fake.load_scenario("right_turn_left_straight")
        scn["fake"]["delay_sec"] = 0.05
        with mock.patch.object(fake, "load_scenario", lambda n: scn):
            analyzer.run(self.video, progress=seen.append, name="fake")
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(len(seen), 5)


if __name__ == "__main__":
    unittest.main()
