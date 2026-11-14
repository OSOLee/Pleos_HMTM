"""이상한 입력을 run_app.py에 넣어도 파이썬 오류(Traceback)로 죽지 않고 한국어 안내나 앱 상태로 끝나는지

  python -m unittest tests.test_inputs               # 모서리·답 입력 (1분 안팎)
  MTM_SLOW=1 python -m unittest tests.test_inputs    # 처음 보는 영상까지 (YOLO를 돌려서 10분 안팎)

영상(data/videos)과 평가 결과(outputs/eval_tap)가 있어야 함. git에 없는 파일이라 없으면 건너뜀.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data/videos/cc/cc_3_211208_vehicle_120_011.mp4")
TAP = os.path.join(ROOT, "outputs/eval_tap/cc_3_211208_vehicle_120_011")
BB = os.path.join(ROOT, "data/videos/bb_lights")
CORNERS = "0.3,0.3 0.7,0.3 0.7,0.7 0.3,0.7"
SLOW = os.environ.get("MTM_SLOW") == "1"


def run_app(args, out):
    p = subprocess.run([sys.executable, "run_app.py", *args, "--out", out], cwd=ROOT,
                       capture_output=True, text=True, timeout=1200)
    status = None
    if os.path.exists(os.path.join(out, "app.json")):
        with open(os.path.join(out, "app.json"), encoding="utf-8") as f:
            status = json.load(f).get("status")
    return p.returncode, p.stdout + p.stderr, status


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mtm_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def no_crash(self, args, out=None, expect_status=None, expect_text=None):
        code, text, status = run_app(args, out or os.path.join(self.tmp, "out"))
        self.assertNotIn("Traceback", text, text[-1500:])
        if expect_status:
            self.assertEqual(status, expect_status, text[-500:])
        if expect_text:
            self.assertIn(expect_text, text)
        return code, status


@unittest.skipUnless(os.path.exists(SRC), "평가 영상이 없음")
class Corners(Base):
    def test_bad_corners(self):
        cases = {
            "0.3,0.3 0.7,0.3 0.7,0.7": "4개",
            "0.3,0.3 1.7,0.3 0.7,0.7 0.3,0.7": "0~1",
            "0.5,0.5 0.5,0.5 0.5,0.5 0.5,0.5": "붙어",
            "a,b c,d e,f g,h": "숫자",
            "0.3 0.7 0.7 0.3": "4개",
        }
        for corners, text in cases.items():
            with self.subTest(corners=corners):
                code, _ = self.no_crash([SRC, "--corners", corners], expect_text=text)
                self.assertEqual(code, 1)

    def test_no_corners(self):
        self.no_crash([SRC], expect_text="--corners")

    def test_blackbox_selected(self):
        self.no_crash([SRC, "--source", "blackbox"], expect_status="unsupported")


@unittest.skipUnless(os.path.exists(TAP), "평가 결과(eval_tap)가 없음")
class Answers(Base):
    """평가 결과 폴더를 복사해서 쓰므로 YOLO를 다시 돌리지 않음"""

    def with_answers(self, content, raw=False):
        out = os.path.join(self.tmp, "out")
        shutil.rmtree(out, ignore_errors=True)
        shutil.copytree(TAP, out)
        path = os.path.join(out, "answers.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content if raw else json.dumps(content, ensure_ascii=False))
        return out, path

    def good(self):
        with open(os.path.join(TAP, "answers.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_saved_answers_still_work(self):
        out, path = self.with_answers(self.good())
        code, status = self.no_crash([SRC, "--answers", path], out=out)
        self.assertEqual(code, 0)
        self.assertIn(status, ("done", "needs_answers"))

    def test_bad_answers_give_message(self):
        good = self.good()
        t = good["collision.parties"][0]
        cases = {
            "보기 밖 값": (dict(good, **{f"parties.{t}.movement": "fly"}), "보기"),
            "프레임 글자": (dict(good, **{f"parties.{t}.intersection_entry": "abc"}), "프레임"),
            "프레임 범위 밖": (dict(good, **{f"parties.{t}.intersection_entry": 99999}), "프레임"),
            "박스 이상": (dict(good, user_tracks={"9001": {"frame": 5, "bbox": [0.5, 0.5, -0.1, 2], "cls": "car"}}), "박스"),
            "박스 프레임 밖": (dict(good, user_tracks={"9001": {"frame": 99999, "bbox": [0.4, 0.4, 0.1, 0.1], "cls": "car"}}), "프레임"),
            "user_tracks 목록": (dict(good, user_tracks=[1, 2]), "user_tracks"),
            "답이 목록": ([1, 2, 3], "모양"),
        }
        for name, (content, text) in cases.items():
            with self.subTest(name):
                out, path = self.with_answers(content)
                code, _ = self.no_crash([SRC, "--answers", path], out=out, expect_text=text)
                self.assertEqual(code, 1)

    def test_broken_files(self):
        out, path = self.with_answers("{broken", raw=True)
        self.no_crash([SRC, "--answers", path], out=out, expect_text="JSON")
        self.no_crash([SRC, "--answers", os.path.join(out, "nope.json")], out=out, expect_text="찾지 못했어요")

    def test_bad_pair_asks_again(self):
        good = self.good()
        t = good["collision.parties"][0]
        for pair in (["99999", t], [t, t], [t]):
            with self.subTest(pair=pair):
                out, path = self.with_answers(dict(good, **{"collision.parties": pair}))
                self.no_crash([SRC, "--answers", path], out=out, expect_status="no_collision")


@unittest.skipUnless(SLOW and os.path.exists(SRC), "MTM_SLOW=1일 때만 (YOLO를 돌려서 느림)")
class Videos(Base):
    def make(self, name, frames):
        path = os.path.join(self.tmp, name)
        h, w = frames[0].shape[:2]
        vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 15, (w, h))
        for f in frames:
            vw.write(f)
        vw.release()
        return path

    def frames(self, n):
        cap, out = cv2.VideoCapture(SRC), []
        while len(out) < n:
            ok, f = cap.read()
            if not ok:
                break
            out.append(f)
        return out

    def test_broken_inputs(self):
        with open(os.path.join(self.tmp, "text.mp4"), "w") as f:
            f.write("not a video")
        open(os.path.join(self.tmp, "empty.mp4"), "w").close()
        for v in ("nope.mp4", "text.mp4", "empty.mp4"):
            with self.subTest(v):
                code, _ = self.no_crash([os.path.join(self.tmp, v), "--corners", CORNERS], expect_text="읽지 못했")
                self.assertEqual(code, 1)

    def test_odd_videos(self):
        src = self.frames(90)
        cases = {
            "one.mp4": src[:1],
            "ten.mp4": src[:10],
            "blank.mp4": [np.full((720, 1280, 3), 90, np.uint8)] * 60,
            "portrait.mp4": [cv2.rotate(f, cv2.ROTATE_90_CLOCKWISE) for f in src],
            "tiny.mp4": [cv2.resize(f, (160, 90)) for f in src],
        }
        for name, fr in cases.items():
            with self.subTest(name):
                self.no_crash([self.make(name, fr), "--corners", CORNERS], out=os.path.join(self.tmp, "out_" + name))

    @unittest.skipUnless(os.path.isdir(BB), "블랙박스 영상이 없음")
    def test_moving_blackbox_as_cctv(self):
        v = os.path.join(BB, "bb_1_170606_bike_228_22977.mp4")
        self.no_crash([v, "--corners", CORNERS], expect_status="unsupported")


if __name__ == "__main__":
    unittest.main()
