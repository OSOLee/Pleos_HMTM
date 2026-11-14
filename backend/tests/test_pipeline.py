"""src/app/pipeline.py를 서버처럼 직접 불러 시험 (prepare / set_scene / solve)

  python -m unittest tests.test_pipeline              # 순서 오류 (몇 초)
  MTM_SLOW=1 python -m unittest tests.test_pipeline   # 탐지부터 끝까지 (1분 안팎)

평가 영상(data/videos)과 평가 결과(outputs/eval_auto)가 있어야 함. 없으면 건너뜀.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)   # 모델 경로 등이 backend 폴더 기준 (판정 모듈은 backend/judge)
from src.app import pipeline
from src.app.pipeline import InputError

NAME = "cc_3_211208_vehicle_120_011"
VIDEO = os.path.join(ROOT, "data/videos/cc", NAME + ".mp4")
AUTO = os.path.join(ROOT, "outputs/eval_auto", NAME)
SLOW = os.environ.get("MTM_SLOW") == "1"


def corners_of(case):
    with open(os.path.join(case, "scene.json"), encoding="utf-8") as f:
        s = json.load(f)
    return s["corners"], s.get("closed_side")


@unittest.skipUnless(os.path.exists(VIDEO) and os.path.isdir(AUTO), "평가 영상·결과가 없음")
class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mtm_pipe_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_solve_needs_scene_and_tracks(self):
        with self.assertRaises(InputError) as e:
            pipeline.solve(self.tmp, VIDEO)
        self.assertEqual(e.exception.code, "scene_missing")
        corners, closed = corners_of(AUTO)
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.set_scene(self.tmp, VIDEO, corners, closed)   # 탐지 전에 모서리부터 와도 됨
        with self.assertRaises(InputError) as e:
            pipeline.solve(self.tmp, VIDEO)
        self.assertEqual(e.exception.code, "not_prepared")

    def test_bad_inputs(self):
        for corners, code in (([[0.5, 0.5]] * 4, "corners_too_close"), ([[0.1, 0.1]] * 3, "corners_count"),
                              ([[0.1, 2], [0.2, 0.1], [0.3, 0.3], [0.1, 0.4]], "corners_range"),
                              ([["a", "b"]] * 4, "corners_invalid")):
            with self.subTest(code), self.assertRaises(InputError) as e:
                pipeline.set_scene(self.tmp, VIDEO, corners)
            self.assertEqual(e.exception.code, code)
        with self.assertRaises(InputError) as e:
            pipeline.check_answers([1, 2])
        self.assertEqual(e.exception.code, "answers_shape")
        self.assertEqual(pipeline.prepare(self.tmp, VIDEO, "blackbox"), "unsupported")

    @unittest.skipUnless(SLOW, "MTM_SLOW=1일 때만 (탐지를 돌려서 느림)")
    def test_full_run_matches_saved_result(self):
        """모서리를 먼저 보내고 → 준비(탐지) → 판정. 저장된 자동 결과와 같은 판정이어야 함"""
        corners, closed = corners_of(AUTO)
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.set_scene(self.tmp, VIDEO, corners, closed)
            self.assertEqual(pipeline.prepare(self.tmp, VIDEO, "cctv", NAME), "ready")
            app = pipeline.solve(self.tmp, VIDEO, {}, name=NAME)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "background.jpg")))
        with open(os.path.join(AUTO, "app.json"), encoding="utf-8") as f:
            saved = json.load(f)
        for k in ("rule_id", "fault_by_track"):
            self.assertEqual(app["verdict"][k], saved["verdict"][k])
        self.assertEqual(app["status"], saved["status"])
        self.assertEqual([q["field"] for q in app["questions"]], [q["field"] for q in saved["questions"]])


if __name__ == "__main__":
    unittest.main()
