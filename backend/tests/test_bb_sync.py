"""블랙박스 시각 맞추기 v0 시험 (docs/design-blackbox.md 5절)

  python -m pytest tests/test_bb_sync.py

촬영 시각 추정(파일 이름·mp4 메타데이터·수정 시각), 차량 기록 구간(길이 + 30초, 최대 300초), 등급 coarse/none.
"""
import datetime as dt
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from bb_common import make_video
from src.blackbox import sync

KST = dt.timezone(dt.timedelta(hours=9))
S0 = int(dt.datetime(2026, 11, 9, 14, 30, 12, tzinfo=KST).timestamp() * 1000)


def box(kind, payload):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def mp4_with_creation(path, when_utc, version=0):
    secs = int((when_utc - sync.MP4_EPOCH).total_seconds())
    if version == 1:
        mvhd = bytes([1, 0, 0, 0]) + struct.pack(">QQ", secs, secs) + b"\0" * 80
    else:
        mvhd = bytes([0, 0, 0, 0]) + struct.pack(">II", secs, secs) + b"\0" * 80
    with open(path, "wb") as f:
        f.write(box(b"ftyp", b"isom\0\0\0\0") + box(b"free", b"") + box(b"moov", box(b"mvhd", mvhd)))
    return path


class StartTime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hmtm_bbsync_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_filename_patterns(self):
        for name in ["20261109_143012_F.mp4", "EVT_20261109_143012.mp4", "REC_2026-11-09_14-30-12.avi",
                     "/sd/Normal/20261109143012.MP4", "2026.11.09 14:30:12 front.mp4"]:
            self.assertEqual(sync.from_filename(name), S0, name)
        for name in ["video.mp4", "20261309_143012.mp4", "20261109_256012.mp4", None]:
            self.assertIsNone(sync.from_filename(name), name)
        self.assertEqual(sync.from_filename("20261109_143012.mp4", tz_min=0), S0 + 9 * 3600 * 1000)

    def test_mp4_creation_time(self):
        when = dt.datetime(2026, 11, 9, 5, 30, 12, tzinfo=dt.timezone.utc)   # = 14:30:12 KST
        for v in (0, 1):
            p = mp4_with_creation(os.path.join(self.tmp, f"m{v}.mp4"), when, v)
            self.assertEqual(sync.mp4_creation_ms(p), S0)
        zero = mp4_with_creation(os.path.join(self.tmp, "zero.mp4"), sync.MP4_EPOCH)
        self.assertIsNone(sync.mp4_creation_ms(zero))
        junk = os.path.join(self.tmp, "junk.mp4")
        with open(junk, "wb") as f:
            f.write(b"\xff" * 40)
        self.assertIsNone(sync.mp4_creation_ms(junk))
        self.assertIsNone(sync.mp4_creation_ms(os.path.join(self.tmp, "missing.mp4")))
        # OpenCV가 만든 영상: 읽다가 오류가 나지 않음 (값이 있어도 2000년 이후만)
        v = sync.mp4_creation_ms(make_video(os.path.join(self.tmp, "cv.mp4"), 1.0))
        self.assertTrue(v is None or v > 946684800000)

    def test_candidates_order_and_mtime(self):
        meta = {"recorded_at": [{"source": "metadata", "start_ms": S0 + 5000}, {"source": "weird", "start_ms": S0 + 7000},
                                {"source": "user", "start_ms": "bad"}],
                "mtime_ms": S0 + 30_000}
        c = sync.start_candidates("20261109_143012_F.mp4", meta, None, duration_s=30.0)
        self.assertEqual([x["source"] for x in c], ["filename", "metadata", "app", "mtime"])
        self.assertEqual(c[0]["start_ms"], S0)
        self.assertEqual(c[-1]["start_ms"], S0)          # 수정 시각 − 길이
        self.assertEqual(sync.pick_start(c)["source"], "filename")
        c = sync.start_candidates("video.mp4", {"mtime_ms": S0 + 10_000}, None, duration_s=10.0)
        self.assertEqual(c, [{"source": "mtime", "start_ms": S0}])
        self.assertEqual(sync.start_candidates("video.mp4", None), [])
        c = sync.start_candidates("20261109_143012.mp4", {"tz_offset_min": 0})
        self.assertEqual(c[0]["start_ms"], S0 + 9 * 3600 * 1000)


class Window(unittest.TestCase):
    def test_length_plus_30s(self):
        self.assertEqual(sync.vehicle_window(S0, 60.0), {"from": S0 - 15_000, "to": S0 + 75_000})

    def test_capped_at_300s(self):
        w = sync.vehicle_window(S0, 600.0)
        self.assertEqual(w, {"from": S0 - 15_000, "to": S0 - 15_000 + 300_000})


class Grade(unittest.TestCase):
    C = [{"source": "filename", "start_ms": S0}]
    RNG = {"from": S0 - 15_000, "to": S0 + 45_000}

    def test_coarse(self):
        s = sync.sync(self.C, 18.2, self.RNG)
        self.assertEqual((s["grade"], s["reason"], s["start_source"]), ("coarse", None, "filename"))
        self.assertEqual(s["t_collision_ms"], S0 + 18_200)
        self.assertEqual(s["offset_ms"], 0)

    def test_none_cases(self):
        cases = [(sync.sync([], 18.2, self.RNG), "no_start_time"),
                 (sync.sync(self.C, 18.2, None), "no_vehicle_record"),
                 (sync.sync([{"source": "mtime", "start_ms": S0}], 18.2, self.RNG), "start_time_unreliable"),
                 (sync.sync(self.C, None, self.RNG), "no_collision_time"),
                 (sync.sync(self.C, 18.2, {"from": S0 + 16_000, "to": S0 + 45_000}), "vehicle_record_not_covering"),
                 (sync.sync(self.C, 18.2, {"from": S0, "to": S0 + 18_000}), "vehicle_record_not_covering")]
        for s, reason in cases:
            self.assertEqual((s["grade"], s["reason"]), ("none", reason))
        self.assertIsNone(sync.sync([], 1.0)["t_collision_ms"])
        self.assertEqual(sync.sync(self.C, 1.0)["t_collision_ms"], S0 + 1000)   # 차량 기록이 없어도 시각은 계산

    def test_never_fine_in_v0(self):
        s = sync.sync([{"source": "user", "start_ms": S0}], 18.2, self.RNG)
        self.assertEqual(s["grade"], "coarse")


if __name__ == "__main__":
    unittest.main()
