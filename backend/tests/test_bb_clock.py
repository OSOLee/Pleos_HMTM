"""시계 차이 경고·시각 맞추기 none 이유 시험 (docs/api-spec.md 6.1, docs/design-blackbox.md 5절)

  python -m pytest tests/test_bb_clock.py

- src/vehicle/clock.warnings: 서버 시각과 하루 넘게 다르면 경고 (영상 촬영 시각, 차량 기록 구간)
- sync: 차량 기록을 올렸는데 영상 구간과 안 겹치면 vehicle_clock_mismatch (전에는 no_vehicle_record), vehicle_gap, reason_text
- API: 블랙박스 사건 data_quality.clock_warnings·sync_reason_text, 차량 사건 data_quality.clock_warnings
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
import test_bb_api as bbt
import test_vehicle_api as vt
from src.blackbox import store as bb_store
from src.blackbox import sync
from src.vehicle import adapter as vadapter
from src.vehicle import clock
from src.vehicle.samples import validate

DAY = clock.DAY_MS
HOUR = 3_600_000
S0 = bbt.S0
C = [{"source": "filename", "start_ms": S0}]


class Warnings(unittest.TestCase):
    def test_within_a_day_no_warning(self):
        self.assertEqual(clock.warnings(S0 + DAY, S0, "filename", {"from": S0 - DAY, "to": S0}), [])
        self.assertEqual(clock.warnings(None, S0, "filename"), [])

    def test_video_behind_and_ahead(self):
        w, = clock.warnings(S0 + 3 * DAY, S0, "filename")
        self.assertEqual((w["kind"], w["source"], w["direction"], w["diff_ms"]),
                         ("video_clock", "filename", "behind", -3 * DAY))
        self.assertIn("3일 전이에요", w["message"])
        w, = clock.warnings(S0 - 2 * DAY, S0, "metadata")
        self.assertEqual(w["direction"], "ahead")
        self.assertIn("영상 정보", w["message"])

    def test_vehicle_range_nearest_end(self):
        rng = {"from": S0 - 5 * DAY, "to": S0 - 2 * DAY}
        w, = clock.warnings(S0, vehicle_range=rng)
        self.assertEqual((w["kind"], w["t_ms"], w["diff_ms"]), ("vehicle_clock", rng["to"], -2 * DAY))
        self.assertEqual(clock.warnings(S0, vehicle_range={"from": S0 - 3 * DAY, "to": S0 + 1}), [])


class SyncReason(unittest.TestCase):
    T = S0 + 18_200

    def test_uploaded_but_outside_video(self):
        far = {"from": S0 + 2 * HOUR, "to": S0 + 2 * HOUR + 60_000}
        s = sync.sync(C, 18.2, None, uploaded_range=far, server_ms=S0 + 3 * HOUR)
        self.assertEqual((s["grade"], s["reason"]), ("none", "vehicle_clock_mismatch"))
        self.assertEqual(s["vehicle_gap"]["gap_ms"], far["from"] - self.T)
        self.assertEqual(s["vehicle_gap"]["need"], {"from": self.T - sync.MIN_BEFORE_MS, "to": self.T})
        self.assertIn("어긋나", s["reason_text"])
        self.assertIn("2.0시간 뒤예요", s["reason_text"])
        self.assertEqual(s["clock_warnings"], [])

    def test_not_covering_has_gap(self):
        rng = {"from": self.T - 1_000, "to": self.T + 5_000}       # 충돌 앞 3초를 못 덮음 (겹침)
        s = sync.sync(C, 18.2, rng, uploaded_range=rng)
        self.assertEqual(s["reason"], "vehicle_record_not_covering")
        self.assertEqual(s["vehicle_gap"]["gap_ms"], 0)
        self.assertEqual(s["reason_text"], sync.REASON_TEXT["vehicle_record_not_covering"])
        rng = {"from": self.T - 60_000, "to": self.T - 10_000}     # 충돌 전에 끝남 (자른 뒤에도 남는 경우)
        s = sync.sync(C, 18.2, rng, uploaded_range=rng)
        self.assertEqual(s["vehicle_gap"]["gap_ms"], -7_000)
        self.assertIn("7초 앞이에요", s["reason_text"])

    def test_no_record_and_ok_grades(self):
        s = sync.sync(C, 18.2, None)
        self.assertEqual((s["reason"], s["reason_text"], s["vehicle_gap"]), ("no_vehicle_record", "차량 기록이 없어요", None))
        s = sync.sync(C, 18.2, {"from": S0, "to": S0 + 30_000})
        self.assertEqual((s["grade"], s["reason_text"]), ("coarse", None))


class BbApi(bbt.ApiBase):
    def test_vehicle_clock_mismatch_and_warnings(self):
        h = self.login("clock")
        veh = bbt.vehicle()
        shift = 3 * DAY                     # 앱 시계가 3일 앞섬
        for x in veh["samples"]:
            x["t"] += shift
        veh["range"] = {"from": veh["range"]["from"] + shift, "to": veh["range"]["to"] + shift}
        with mock.patch.object(bb_store, "now_ms", return_value=S0 + 60_000):   # 서버는 촬영 1분 뒤에 받음
            cid = self.upload(h, "right_turn_left_straight", veh=veh).json()["id"]
            view = self.result(h, cid)
        s, dq = view["sync"], view["data_quality"]
        self.assertEqual((s["grade"], s["reason"]), ("none", "vehicle_clock_mismatch"))
        self.assertGreater(s["vehicle_gap"]["gap_ms"], 2 * DAY)
        self.assertEqual(dq["sync_reason"], "vehicle_clock_mismatch")
        self.assertEqual(dq["sync_reason_text"], s["reason_text"])
        self.assertEqual([w["kind"] for w in dq["clock_warnings"]], ["vehicle_clock"])
        self.assertEqual(dq["clock_warnings"][0]["direction"], "ahead")
        self.assertIsNone(view["result_with_vehicle"])
        # 다시 판정해도 저장한 sync의 경고가 그대로
        r = self.c.put(f"/api/bb-cases/{cid}/answers", json={"answers": {}}, headers=h).json()
        self.assertEqual(r["data_quality"]["clock_warnings"], dq["clock_warnings"])

    def test_old_video_warning(self):
        h = self.login("old")
        with mock.patch.object(bb_store, "now_ms", return_value=S0 + 5 * DAY):
            cid = self.upload(h, "right_turn_left_straight").json()["id"]
            view = self.result(h, cid)
        w, = view["data_quality"]["clock_warnings"]
        self.assertEqual((w["kind"], w["source"], w["direction"]), ("video_clock", "filename", "behind"))
        self.assertEqual(view["sync"]["clock_warnings"], [w])

    def test_not_judged_case_still_warns(self):
        h = self.login("nocol")
        with mock.patch.object(bb_store, "now_ms", return_value=S0 - 2 * DAY):
            cid = self.upload(h, "no_collision", veh=bbt.vehicle()).json()["id"]
            view = self.result(h, cid)
        self.assertEqual(view["status"], "no_collision")
        self.assertEqual({w["kind"] for w in view["sync"]["clock_warnings"]}, {"video_clock", "vehicle_clock"})


class VehicleCase(unittest.TestCase):
    def test_vehicle_case_clock_warning(self):
        req = dict(validate(vt.body()), server_ms=vt.T + 2 * DAY)
        w, = vadapter.build(req, {})["view"]["data_quality"]["clock_warnings"]
        self.assertEqual((w["kind"], w["direction"]), ("vehicle_clock", "behind"))
        req["server_ms"] = vt.T + HOUR
        self.assertEqual(vadapter.build(req, {})["view"]["data_quality"]["clock_warnings"], [])
        old = validate(vt.body())                               # 받은 시각이 없는 옛 요청
        self.assertEqual(vadapter.build(old, {})["view"]["data_quality"]["clock_warnings"], [])


if __name__ == "__main__":
    unittest.main()
