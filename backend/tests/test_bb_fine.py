"""정밀 시각 맞추기(fine) 시험 (bb-flow 2부 4단계, docs/design-blackbox.md 5.3)

  python -m pytest tests/test_bb_fine.py

가짜 분석기 시나리오 right_turn_motion의 내 차 움직임(ego_motion.speed_proxy)으로 차량 속도를 만들고,
블랙박스 시계와 차량 시계를 일부러 어긋나게(TRUE_OFFSET) 둔다. 속도 모양 상관 ≥ 0.7 + 충격 기준점 0.5초 안 → fine,
offset 보정, 시각에 민감한 차량 값(지시등)을 확정 답으로. 안 되면 coarse/none으로 내려가는지.
"""
import os
import random
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from src.blackbox import adapter, analyzer, sync
from test_bb_api import S0 as API_S0, ApiBase, DURATION

S0 = 1_762_666_212_000
START = [{"source": "filename", "start_ms": S0}]
TRUE_OFFSET = -1_300          # 차량 시각 = S0 + TRUE_OFFSET + 영상 t
SCN = "right_turn_motion"


def motion(bb):
    em = bb["ego_motion"]
    return np.asarray(em["t"]), np.asarray(em["speed_proxy"])


def samples(bb, s0=S0, offset=TRUE_OFFSET, before=15_000, after=15_000, kmh=40.0, turn=None, noise=0.0,
            drop=True, flat=None, step=100):
    """영상 움직임을 따라 달린 차량 기록. turn: 영상 충돌 기준 몇 ms 전부터 RIGHT (None이면 OFF)"""
    t, sp = motion(bb)
    col = bb["facts"]["collision"]["t"]
    if not drop:   # 충돌 뒤 급감속이 없음 (충격 기준점 없음)
        sp = np.where(t >= col, np.interp(col, t, sp), sp)
    rnd = random.Random(7)
    dur = bb["video"]["duration_s"]
    out = []
    for vt in range(s0 + offset - before, s0 + offset + int(dur * 1000) + after + 1, step):
        x = (vt - s0 - offset) / 1000
        v = flat if flat is not None else kmh * float(np.interp(x, t, sp, left=0.0, right=0.0))
        v = max(0.0, v + rnd.gauss(0, noise)) if noise else v
        rel = (x - col) * 1000
        sig = "RIGHT" if turn is not None and -turn <= rel else "OFF"
        out.append({"t": vt, "speedKmh": round(v, 2), "gear": "D", "turnSignal": sig, "brake": rel >= 0})
    return out


def vreq(s):
    return {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle_cls": "car", "client": {}}


def do_sync(bb, s, start=START):
    return sync.sync(start, bb["facts"]["collision"]["t"], {"from": s[0]["t"], "to": s[-1]["t"]}, samples=s,
                     ego_motion=bb["ego_motion"], duration_s=bb["video"]["duration_s"])


class FineMatch(unittest.TestCase):
    def setUp(self):
        self.bb = analyzer.run("none.mp4", scenario=SCN, name="fake")   # 영상을 못 읽음 → 시나리오 시각 그대로 (30초)

    def test_fine_finds_offset(self):
        s = do_sync(self.bb, samples(self.bb))
        self.assertEqual(s["grade"], "fine", s["fine"])
        self.assertEqual(s["method"], "speed_xcorr+impact")
        self.assertLessEqual(abs(s["offset_ms"] - TRUE_OFFSET), 100)
        self.assertGreaterEqual(s["score"], 0.7)
        self.assertEqual(s["t_collision_ms"], S0 + s["offset_ms"] + 18_200)
        self.assertTrue(s["fine"]["impact"]["matched"])
        self.assertLessEqual(abs(s["fine"]["impact"]["offset_ms"] - TRUE_OFFSET), 500)
        self.assertEqual(s["fine"]["offset_candidates"][0]["offset_ms"], s["offset_ms"])
        self.assertIsNone(s["reason"])

    def test_fine_with_noise_and_other_offsets(self):
        for off in (-9_000, 0, 4_200, 12_000):
            s = do_sync(self.bb, samples(self.bb, offset=off, noise=1.5))
            self.assertEqual(s["grade"], "fine", (off, s["fine"]))
            self.assertLessEqual(abs(s["offset_ms"] - off), 200, off)

    def test_offset_outside_search_is_not_fine(self):
        """±15초 밖이면 못 찾음 → 거친 시각(offset 0)으로 coarse·none"""
        s = do_sync(self.bb, samples(self.bb, offset=25_000, before=40_000, after=40_000))
        self.assertNotEqual(s["grade"], "fine")
        self.assertEqual(s["offset_ms"], 0)

    def test_mtime_start_searches_60s(self):
        """시작 시각이 수정 시각뿐이면 coarse는 안 되지만, 움직임이 맞으면 ±60초에서 찾아 fine"""
        start = [{"source": "mtime", "start_ms": S0}]
        s = do_sync(self.bb, samples(self.bb, offset=40_000, before=60_000, after=60_000), start)
        self.assertEqual((s["grade"], s["start_source"]), ("fine", "mtime"), s["fine"])
        self.assertLessEqual(abs(s["offset_ms"] - 40_000), 100)
        flat = do_sync(self.bb, samples(self.bb, offset=0, flat=40.0), start)
        self.assertEqual((flat["grade"], flat["reason"]), ("none", "start_time_unreliable"))

    def test_flat_speed_falls_back(self):
        s = do_sync(self.bb, samples(self.bb, offset=0, flat=40.0))
        self.assertEqual((s["grade"], s["offset_ms"]), ("coarse", 0))
        self.assertEqual(s["fine"]["reason"], "no_speed_variation")

    def test_no_impact_falls_back(self):
        s = do_sync(self.bb, samples(self.bb, offset=0, drop=False))
        self.assertEqual(s["grade"], "coarse")
        # 충돌 뒤 급감속이 없으면 가장 센 감속은 12~14초 감속 → 기준점이 안 맞거나 없음
        self.assertIn(s["fine"]["reason"], ("no_impact", "impact_mismatch"))

    def test_low_correlation_falls_back(self):
        s = [dict(x, speedKmh=20.0 + 15 * np.sin((x["t"] - S0) / 900.0)) for x in samples(self.bb, offset=0)]
        r = do_sync(self.bb, s)
        self.assertEqual(r["grade"], "coarse")
        self.assertIn(r["fine"]["reason"], ("low_correlation", "impact_mismatch", "no_impact"))

    def test_no_ego_motion_scenario(self):
        bb = analyzer.run("none.mp4", scenario="right_turn_left_straight", name="fake")
        s = do_sync(bb, samples(self.bb, offset=0))
        self.assertEqual(s["grade"], "coarse")
        self.assertEqual(s["fine"]["reason"], "no_ego_motion")

    def test_record_not_covering_after_offset(self):
        """offset을 보정한 충돌 시각 앞 3초를 기록이 못 덮으면 fine으로 쓰지 않음"""
        s = samples(self.bb)
        col = S0 + TRUE_OFFSET + 18_200
        r = sync.sync(START, 18.2, {"from": col - 1_000, "to": s[-1]["t"]}, samples=s,
                      ego_motion=self.bb["ego_motion"], duration_s=30.0)
        self.assertNotEqual(r["grade"], "fine")


class FineMerge(unittest.TestCase):
    """fine일 때만 시각에 민감한 차량 값(지시등·서행·진로 변경 방향)을 확정 답으로"""

    def setUp(self):
        self.bb = analyzer.run("none.mp4", scenario=SCN, name="fake")

    def test_turn_signal_definite_only_when_fine(self):
        s = samples(self.bb, turn=6_000)
        fine = do_sync(self.bb, s)
        view = adapter.build(self.bb, vreq(s), fine, {})["with_vehicle"]
        self.assertEqual(fine["grade"], "fine")
        self.assertEqual(view["answers"]["parties.ego.turn_signal_used"]["source"], "vehicle")
        self.assertTrue(view["answers"]["parties.ego.turn_signal_used"]["value"])
        self.assertIn("parties.ego.turn_signal_used", [a["field"] for a in view["auto_answers"]])
        self.assertEqual(view["event"]["t_event"], fine["t_collision_ms"])
        self.assertEqual(view["data_quality"]["sync_grade"], "fine")
        # 같은 기록을 offset 0(coarse)으로 쓰면 지시등은 추정값으로만
        coarse = dict(fine, grade="coarse", offset_ms=0, t_collision_ms=S0 + 18_200)
        view = adapter.build(self.bb, vreq(s), coarse, {})["with_vehicle"]
        self.assertNotIn("parties.ego.turn_signal_used", [a["field"] for a in view["auto_answers"]])
        a = view["answers"].get("parties.ego.turn_signal_used")
        self.assertTrue(a is None or a["source"] == "default")

    def test_fine_uses_corrected_t(self):
        """지시등을 진짜 충돌 1.5초 전에야 켬: offset을 보정하면 '늦게 켬'(False), 보정 안 하면(offset 0) 다르게 읽힘"""
        s = samples(self.bb, turn=1_500)
        fine = do_sync(self.bb, s)
        view = adapter.build(self.bb, vreq(s), fine, {})["with_vehicle"]
        self.assertEqual(view["answers"]["parties.ego.turn_signal_used"]["value"], False)
        self.assertIn("1.5초 전에야", view["answers"]["parties.ego.turn_signal_used"]["evidence"])


class FineApi(ApiBase):
    def test_upload_fine(self):
        """실제 업로드: 영상 12초(시나리오 시각을 0.4배로 옮김) + 어긋난 차량 시계 → fine, PUT answers 뒤에도 그대로"""
        h = self.login("kim")
        bb = analyzer.run(self.video, scenario=SCN, name="fake")                  # 업로드 때와 같은 시각 비율
        self.assertAlmostEqual(bb["video"]["duration_s"], DURATION, places=2)
        s = samples(bb, s0=API_S0, offset=TRUE_OFFSET, turn=2_400)
        veh = {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle": {"cls": "car"}}
        view = self.run_case(h, scenario=SCN, veh=veh)
        self.assertEqual(view["sync"]["grade"], "fine", view["sync"]["fine"])
        self.assertLessEqual(abs(view["sync"]["offset_ms"] - TRUE_OFFSET), 100)
        self.assertEqual(view["data_quality"]["sync_grade"], "fine")
        hint = {q["field"]: q for q in view["remaining"]}["parties.ego.turn_signal_used"]["vehicle_hint"]
        self.assertEqual((hint["value"], hint["applied"]), (False, True))   # 2.4초 전에야 켬
        self.assertEqual(view["result_with_vehicle"]["fault_by_party"], view["result"]["fault_by_party"])
        self.assertEqual(view["vehicle_effects"], [])   # 차13-1에는 지시등 가감 요소가 없음
        r = self.c.put(f"/api/bb-cases/{view['id']}/answers", json={"answers": {"road.signal_present": False}},
                       headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["sync"], view["sync"])
        self.assertEqual(r.json()["vehicle_timeline"]["sync_grade"], "fine")


if __name__ == "__main__":
    unittest.main()
