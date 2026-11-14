"""사고 순간 고르기 (docs/design-blackbox.md 3.2 PUT collision, 3.6 collision_review, 2026-11-12)

  python -m pytest tests/test_bb_pick.py

Pick        fake 모드(API 스레드): no_collision → 영상 보관 → PUT collision → 고른 순간으로 다시 분석·판정 → 영상 삭제.
            고른 순간으로도 판정 못 하면 고르기 전 결과로 되돌리고 다시 고를 수 있음. 오류 응답. 7일 기한이 지나면 영상 삭제
PickWorker  mtm 모드(작업자 프로세스): PUT collision은 행만 바꾸고 작업자가 다시 분석
MtmPick     MTM 분석기(무거운 단계는 대역)에 고른 순간이 analyze(collision_t=초)로 그대로 가고, 그 순간이 충격 프레임이 됨
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
from test_bb_api import DURATION, K, S0, ApiBase, vehicle   # noqa: E402  (경로·DB 준비는 test_bb_api가 함)
from test_bb_video_analyzer import _write, fake_track   # noqa: E402
from test_bb_worker import WorkerMode   # noqa: E402
from bb_common import make_video   # noqa: E402
from src.blackbox import analyzer, fake, store, worker   # noqa: E402
from src.blackbox import api as bb_api   # noqa: E402
from src.blackbox import video_analyzer as mtm   # noqa: E402

SCN = "no_collision_pick"
CANDS = [round(18.2 * K, 3), round(12.0 * K, 3)]     # 시나리오 후보(30초 기준) → 시험 영상(12초) 시각


class PickBase(ApiBase):
    def pick(self, h, cid, t):
        return self.c.put(f"/api/bb-cases/{cid}/collision", json={"t": t}, headers=h)

    def assert_waiting(self, view):
        rv = view["collision_review"]
        self.assertTrue(rv["needed"])
        self.assertTrue(rv["can_pick"])
        self.assertIsNotNone(rv["pick_until"])
        self.assertTrue(bb_api.video_file(view["id"]))
        row = store.get(view["id"])
        self.assertEqual(row["video_until"], rv["pick_until"])
        self.assertTrue(row["video_kept"])


class Pick(PickBase):
    def test_no_collision_then_pick(self):
        h = self.login("kim")
        view = self.run_case(h, scenario=SCN, veh=vehicle())
        self.assertEqual(view["status"], "no_collision")
        rv = view["collision_review"]
        self.assertEqual(rv["reason"], "no_collision")
        self.assertEqual([c["t"] for c in rv["candidates"]], CANDS)            # 분석기 후보를 영상 시각으로 전달
        self.assert_waiting(view)
        self.assertAlmostEqual(rv["pick_until"] - store.get(view["id"])["updated_at"], bb_api.PICK_MS, delta=5000)
        listed = self.c.get("/api/bb-cases", headers=h).json()[0]
        self.assertEqual((listed["collision_review_needed"], listed["collision_pick_until"]), (True, rv["pick_until"]))

        r = self.pick(h, view["id"], CANDS[0])
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(r.json()["status"], "analyzing")
        self.assertEqual(r.json()["created_at"], view["created_at"])
        done = self.result(h, view["id"])
        self.assertEqual((done["status"], done["result"]["rule_id"]), ("needs_answers", "차13-1"))
        self.assertEqual(done["analysis"]["scenario"]["picked_from"], SCN)
        rv = done["collision_review"]
        self.assertEqual((rv["needed"], rv["reason"], rv["can_pick"], rv["pick_until"]), (False, None, False, None))
        self.assertEqual(rv["picked"]["t"], CANDS[0])
        self.assertEqual((done["event"]["collision_t"], done["event"]["collision_frame"]), (CANDS[0], round(CANDS[0] * 5)))
        # 고른 순간이 사고 순간이 되어 차량 기록을 다시 씀 (시각 맞추기 coarse, 충돌 시각 = 촬영 시작 + 고른 초)
        self.assertEqual(done["sync"]["grade"], "coarse")
        self.assertEqual(done["event"]["t_event"], S0 + int(round(CANDS[0] * 1000)))
        self.assertIsNotNone(done["vehicle_timeline"])
        bb = store.get(view["id"])["bb_facts"]
        self.assertEqual(bb["facts"]["collision"]["t_source"], "user")
        # 판정이 되면 영상 삭제 (Q13)
        self.assertIsNone(bb_api.video_file(view["id"]))
        row = store.get(view["id"])
        self.assertEqual((row["video_until"], row["video_kept"]), (None, False))
        self.assertFalse(row["pick"]["pending"])
        # 이미 정함 → 다시 고를 수 없음
        r = self.pick(h, view["id"], CANDS[1])
        self.assertEqual((r.status_code, r.json()["error"]), (409, "collision_not_needed"))
        listed = self.c.get("/api/bb-cases", headers=h).json()[0]
        self.assertEqual((listed["collision_review_needed"], listed["collision_pick_until"]), (False, None))

    def test_keep_video_env(self):
        h = self.login("kim")
        with mock.patch.dict(os.environ, {bb_api.KEEP_ENV: "1"}):
            view = self.run_case(h, scenario=SCN)
            self.assertEqual(self.pick(h, view["id"], 2.0).status_code, 202)
            done = self.result(h, view["id"])
        self.assertEqual(done["status"], "needs_answers")
        self.assertTrue(bb_api.video_file(view["id"]))          # 개발 모드는 판정 뒤에도 보관
        self.assertIsNone(store.get(view["id"])["video_until"])

    def test_pick_that_still_fails(self):
        """고른 순간으로도 판정하지 못하면(가짜 no_collision은 다시 no_collision) 처음 결과로 되돌리고 다시 고를 수 있음"""
        h = self.login("kim")
        view = self.run_case(h, scenario="no_collision")
        self.assert_waiting(view)
        until = view["collision_review"]["pick_until"]
        self.assertEqual(self.pick(h, view["id"], 3.0).status_code, 202)
        again = self.result(h, view["id"])
        self.assertEqual(again["status"], "no_collision")
        self.assert_waiting(again)
        rv = again["collision_review"]
        self.assertEqual(rv["pick_until"], until)                 # 기한은 늘지 않음
        self.assertEqual((rv["last_pick"]["t"], rv["last_pick"]["status"]), (3.0, "no_collision"))
        self.assertEqual(self.pick(h, view["id"], 4.0).status_code, 202)   # 다시 고를 수 있음
        self.assertEqual(self.result(h, view["id"])["collision_review"]["last_pick"]["t"], 4.0)

    def test_failed_reanalysis_keeps_judgement(self):
        """판정까지 된(확신도 낮은) 사건에서 고른 순간 분석이 실패하면 전 판정·답을 그대로 둠"""
        h = self.login("kim")
        real = fake.FakeAnalyzer.analyze
        state = {"fail": False}

        def patched(an, *a, **kw):
            if state["fail"]:
                raise RuntimeError("분석기 오류")
            out = real(an, *a, **kw)
            out["facts"]["collision"]["t_confidence"] = 0.2
            return out

        with mock.patch.object(fake.FakeAnalyzer, "analyze", patched):
            view = self.run_case(h, scenario="right_turn_left_straight", veh=vehicle())
            self.assertEqual(view["collision_review"]["reason"], "low_confidence")
            self.assert_waiting(view)
            r = self.c.put(f"/api/bb-cases/{view['id']}/answers", json={"answers": {"road.signal_present": False}},
                           headers=h).json()
            self.assertTrue(r["collision_review"]["can_pick"])        # 답해도 고르기 표시는 그대로
            state["fail"] = True
            self.assertEqual(self.pick(h, view["id"], 4.0).status_code, 202)
            back = self.result(h, view["id"])
        self.assertEqual((back["status"], back["result"]), (r["status"], r["result"]))
        self.assertEqual(back["answers"]["road.signal_present"]["source"], "user")
        self.assertEqual(back["collision_review"]["last_pick"]["reason"], "server_error")
        self.assertEqual(back["sync"]["grade"], "none")
        self.assert_waiting(back)

    def test_low_confidence_pick_uses_vehicle(self):
        """확신도가 낮아 차량 기록을 안 쓰던 사건: 순간을 고르면 차량 기록을 쓰고, 그 전에 한 답은 그대로"""
        h = self.login("kim")
        real = fake.FakeAnalyzer.analyze

        def patched(an, *a, **kw):
            out = real(an, *a, **kw)
            out["facts"]["collision"]["t_confidence"] = 0.2
            return out

        with mock.patch.object(fake.FakeAnalyzer, "analyze", patched):
            view = self.run_case(h, scenario="right_turn_left_straight", veh=vehicle())
            self.assertEqual(view["sync"]["reason"], "collision_uncertain")
            self.c.put(f"/api/bb-cases/{view['id']}/answers", json={"answers": {"road.signal_present": False}},
                       headers=h)
            t = view["event"]["collision_t"]
            self.assertEqual(self.pick(h, view["id"], t).status_code, 202)
            done = self.result(h, view["id"])
        self.assertEqual(done["sync"]["grade"], "coarse")
        self.assertIsNotNone(done["event"]["t_event"])
        self.assertFalse(done["collision_review"]["needed"])
        self.assertEqual(done["answers"]["road.signal_present"]["source"], "user")
        self.assertIsNone(bb_api.video_file(view["id"]))

    def test_bad_requests(self):
        kim, lee = self.login("kim"), self.login("lee")
        view = self.run_case(kim, scenario=SCN)
        cid = view["id"]
        for body, code in (({}, "request_invalid"), ([1], "request_invalid"), ({"t": "3"}, "collision_invalid"),
                           ({"t": -1}, "collision_invalid"), ({"t": True}, "collision_invalid"),
                           ({"t": DURATION + 1}, "collision_invalid"), ({"t": None}, "collision_invalid")):
            r = self.c.put(f"/api/bb-cases/{cid}/collision", json=body, headers=kim)
            self.assertEqual((r.status_code, r.json()["error"]), (422, code), body)
        r = self.pick(lee, cid, 2.0)
        self.assertEqual((r.status_code, r.json()["error"]), (404, "bb_case_not_found"))
        self.assertEqual(store.get(cid)["status"], "no_collision")   # 오류면 그대로
        ok = self.run_case(kim, scenario="right_turn_left_straight")
        r = self.pick(kim, ok["id"], 2.0)
        self.assertEqual((r.status_code, r.json()["error"]), (409, "collision_not_needed"))
        with mock.patch.object(bb_api, "enqueue"):
            busy = self.upload(kim, SCN).json()["id"]
        r = self.pick(kim, busy, 2.0)
        self.assertEqual((r.status_code, r.json()["error"]), (409, "bb_case_analyzing"))
        r = self.c.put(f"/api/bb-cases/{ok['id']}/answers", json={"answers": {}}, headers=kim)
        self.assertEqual(r.status_code, 200)

    def test_answers_on_no_collision_still_rejected(self):
        h = self.login("kim")
        view = self.run_case(h, scenario=SCN)
        r = self.c.put(f"/api/bb-cases/{view['id']}/answers", json={"answers": {}}, headers=h)
        self.assertEqual((r.status_code, r.json()["error"]), (409, "bb_case_not_judged"))

    def test_expiry(self):
        h = self.login("kim")
        view = self.run_case(h, scenario=SCN)
        cid = view["id"]
        until = view["collision_review"]["pick_until"]
        self.assertEqual(bb_api.expire_videos(until - 1), 0)         # 기한 전에는 그대로
        self.assertTrue(bb_api.video_file(cid))
        self.assertEqual(bb_api.expire_videos(until), 1)
        self.assertIsNone(bb_api.video_file(cid))
        got = self.c.get(f"/api/bb-cases/{cid}", headers=h).json()
        rv = got["collision_review"]
        self.assertEqual((rv["needed"], rv["can_pick"], rv["pick_until"], rv["expired"]), (True, False, None, True))
        self.assertEqual(got["updated_at"], view["updated_at"])
        r = self.pick(h, cid, 2.0)
        self.assertEqual((r.status_code, r.json()["error"]), (410, "video_gone"))
        self.assertEqual(bb_api.expire_videos(until + bb_api.PICK_MS), 0)   # 한 번만
        row = store.get(cid)
        self.assertEqual((row["video_until"], row["video_kept"]), (None, False))

    def test_expiry_keep_video_env(self):
        h = self.login("kim")
        with mock.patch.dict(os.environ, {bb_api.KEEP_ENV: "1"}):
            view = self.run_case(h, scenario=SCN)
            self.assertEqual(bb_api.expire_videos(view["collision_review"]["pick_until"]), 1)
        self.assertTrue(bb_api.video_file(view["id"]))           # 개발 모드는 파일을 남김
        r = self.pick(h, view["id"], 2.0)                       # 고르기는 끝남
        self.assertEqual((r.status_code, r.json()["error"]), (410, "video_gone"))

    def test_put_after_deadline_before_sweep(self):
        """주기 정리가 아직 안 돌았어도 기한이 지났으면 410 + 그 자리에서 영상 삭제"""
        h = self.login("kim")
        view = self.run_case(h, scenario=SCN)
        with store.connect() as con:
            con.execute("UPDATE bb_cases SET video_until = ? WHERE id = ?", (store.now_ms() - 1, view["id"]))
        r = self.pick(h, view["id"], 2.0)
        self.assertEqual((r.status_code, r.json()["error"]), (410, "video_gone"))
        self.assertIsNone(bb_api.video_file(view["id"]))

    def test_delete_waiting_case(self):
        h = self.login("kim")
        view = self.run_case(h, scenario=SCN)
        self.assertEqual(self.c.delete(f"/api/bb-cases/{view['id']}", headers=h).status_code, 204)
        self.assertFalse(os.path.exists(store.case_dir(view["id"])))

    def test_old_db_gets_new_columns(self):
        """2026-11-12 전 DB 파일(video_until·pick 칸 없음)에도 칸을 더함"""
        from src.server import db
        with db.connect() as con:
            con.execute("DROP TABLE IF EXISTS bb_cases")
            con.executescript(store.SCHEMA.replace("  video_until INTEGER,           -- 사고 순간 고르기를 기다리는 영상의 기한 (epoch ms)\n", "")
                              .replace("  pick TEXT,                     -- JSON: 사용자가 고른 사고 순간\n", ""))
            cols = {r[1] for r in con.execute("PRAGMA table_info(bb_cases)")}
        self.assertNotIn("pick", cols)
        store._migrated.discard(db.DB_PATH)
        h = self.login("kim")
        view = self.run_case(h, scenario=SCN)
        self.assertTrue(store.get(view["id"])["video_until"])


class PickWorker(WorkerMode, PickBase):
    def test_worker_reanalyzes_pick(self):
        h = self.login("kim")
        cid = self.upload(h, SCN).json()["id"]
        self.assertTrue(worker.run_once())
        view = self.c.get(f"/api/bb-cases/{cid}", headers=h).json()
        self.assertEqual(view["status"], "no_collision")
        self.assert_waiting(view)
        r = self.pick(h, cid, CANDS[1])
        self.assertEqual(r.status_code, 202, r.text)
        self.assertTrue(bb_api.idle())                            # API 프로세스는 분석하지 않음
        self.assertEqual(self.c.get(f"/api/bb-cases/{cid}", headers=h).json()["status"], "analyzing")
        self.assertTrue(worker.run_once())
        done = self.c.get(f"/api/bb-cases/{cid}", headers=h).json()
        self.assertEqual((done["status"], done["event"]["collision_t"]), ("needs_answers", CANDS[1]))
        self.assertIsNone(bb_api.video_file(cid))

    def test_pick_not_ready(self):
        """mtm 가중치가 준비 안 됐으면 503, 사건은 그대로 (영상도 남음)"""
        h = self.login("kim")
        cid = self.upload(h, SCN).json()["id"]
        worker.run_once()

        def not_ready(name=None):
            raise analyzer.AnalyzerNotReady("mtm", "준비 안 됨")
        with mock.patch.object(analyzer, "get_analyzer", not_ready):
            r = self.pick(h, cid, 2.0)
        self.assertEqual((r.status_code, r.json()["error"]), (503, "analyzer_not_ready"))
        self.assertEqual(store.get(cid)["status"], "no_collision")
        self.assertTrue(bb_api.video_file(cid))


def still_ego(video, out_dir, **kw):
    """촬영 차가 처음부터 서 있음 → MTM 분석기는 사고 순간을 못 찾음 (no_collision)"""
    frames = [{"frame": i, "mag": 0.0, "tx": 0.0, "ty": 0.0, "scale": 0.0, "n": 50, "ok": True} for i in range(60)]
    _write(out_dir, "ego_motion.json", {"params": {}, "frames": frames, "summary": {
        "frames": 60, "fps": 5.0, "segments": [{"state": "stopped", "from": 0, "to": 59}], "jolt_frames": []}})


class MtmPick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hmtm_mtmpick_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.video = make_video(os.path.join(self.tmp, "v.mp4"), seconds=12.0, fps=5.0)
        self.det = os.path.join(self.tmp, "bb_v3.pt")
        open(self.det, "wb").close()

    def run_mtm(self, **kw):
        from src.analyze import ego_motion, track_video
        with mock.patch.object(track_video, "run", fake_track), mock.patch.object(ego_motion, "run", still_ego), \
                mock.patch.object(mtm, "BB_MODEL", self.det), mock.patch.dict(os.environ, {"HMTM_BB_MODEL_CHECK": "0"}):
            return analyzer.run(self.video, None, name="mtm", **kw)

    def test_picked_time_becomes_impact(self):
        self.assertEqual(self.run_mtm()["status"], "no_collision")
        work = os.path.join(self.tmp, "work")
        out = self.run_mtm(collision_t=4.0, work_dir=work)
        self.assertEqual(out["status"], "ok", out.get("message"))
        col = out["facts"]["collision"]
        self.assertEqual((col["t"], col["frame"], col["t_source"], col["t_confidence"]), (4.0, 20, "user", None))
        self.assertEqual(out["hints"]["collision_pick"]["analyzer_t"], 4.0)   # 분석기도 그 프레임으로 분석함
        self.assertFalse(analyzer.collision_review(out)["needed"])

        with open(os.path.join(work, "bb_partner.json"), encoding="utf-8") as f:
            part = json.load(f)
        self.assertEqual((part["impact_frame"], part["impact_source"]), (20, "user_pick"))   # A가 고른 순간을 받음

    def test_picked_time_passed_to_analyze(self):
        """고른 순간이 video_analyzer.analyze(collision_t=)에 그대로 감. 고르지 않으면 None"""
        real, seen = mtm.analyze, []

        def spy(*a, **kw):
            seen.append(kw.get("collision_t", "missing"))
            return real(*a, **kw)
        with mock.patch.object(mtm, "analyze", spy):
            self.run_mtm()
            self.run_mtm(collision_t=4.25)
        self.assertEqual(seen, [None, 4.25])

    def test_error_becomes_failed(self):
        def boom(*a, **kw):
            raise RuntimeError("x")
        with mock.patch.object(mtm, "analyze", boom):
            out = self.run_mtm(collision_t=4.0)
        self.assertEqual((out["status"], out["reason"]), ("failed", "server_error"))


if __name__ == "__main__":
    unittest.main()
