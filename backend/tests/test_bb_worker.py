"""블랙박스 작업자 프로세스와 사고 순간 확인 필요 (docs/design-blackbox.md 3.4·3.6 collision_review)

  python -m pytest tests/test_bb_worker.py

Worker     HMTM_BB_ANALYZER=mtm이면 API는 사건만 만들고(스레드 없음) 작업자(src.blackbox.worker)가 DB의 analyzing 사건을 분석.
           진짜 MTM 분석기 대신 가짜 분석기를 끼운다 (get_analyzer 대역). 마지막 시험은 작업자를 실제 별도 프로세스로 띄운다.
Review     사고 순간이 없거나(no_collision) 추정이거나 확신도가 낮으면 collision_review.needed, 시각 맞추기 none,
           차량 기록 값(자동 답변·기록 쪽 판정·그래프)을 쓰지 않음
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
from test_bb_api import NAME, T, ApiBase, vehicle   # noqa: E402  (경로·DB 준비는 test_bb_api가 함)
from src.blackbox import analyzer, fake, store, worker   # noqa: E402
from src.blackbox import api as bb_api   # noqa: E402
from src.server import db   # noqa: E402


class WorkerMode(ApiBase):
    """mtm 모드 = 작업자 프로세스. 분석기는 가짜로 바꿔 끼움"""

    def setUp(self):
        super().setUp()
        self.env2 = mock.patch.dict(os.environ, {analyzer.ENV: "mtm"})
        self.env2.start()
        self.an = mock.patch.object(analyzer, "get_analyzer", lambda name=None: fake.FakeAnalyzer())
        self.an.start()

    def tearDown(self):
        self.an.stop()
        self.env2.stop()
        super().tearDown()


class Worker(WorkerMode):
    def test_api_only_creates_then_worker_analyzes(self):
        h = self.login("kim")
        r = self.upload(h, "right_turn_left_straight")
        self.assertEqual(r.status_code, 202, r.text)
        cid = r.json()["id"]
        self.assertTrue(bb_api.idle())                           # API 프로세스에서는 분석하지 않음
        self.assertEqual(self.c.get(f"/api/bb-cases/{cid}", headers=h).json()["status"], "analyzing")
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())                       # 남은 사건 없음
        view = self.c.get(f"/api/bb-cases/{cid}", headers=h).json()
        self.assertEqual((view["status"], view["result"]["rule_id"]), ("needs_answers", "차13-1"))
        self.assertIsNone(bb_api.video_file(cid))                 # 분석이 끝나면 영상 삭제 (Q13)

    def test_resume_is_worker_job(self):
        """서버 재시작: API의 resume은 아무것도 안 하고, 작업자가 남은 analyzing 사건을 오래된 것부터 끝냄"""
        ids = []
        for scn in ("rear_end_lead", "straight_same_time"):
            cid = store.create("u1", {"filename": NAME}, None, scn)
            shutil.copy(self.video, os.path.join(store.case_dir(cid), "video.mp4"))
            ids.append(cid)
        bb_api.resume()
        self.assertTrue(bb_api.idle())
        self.assertEqual(worker.next_case(), ids[0])
        while worker.run_once():
            pass
        self.assertEqual([store.get(c)["status"] for c in ids], ["needs_answers", "needs_answers"])

    def test_delete_during_analysis(self):
        """분석 중에 지운 사건: 진행률 알림에서 멈추고 사건 폴더를 남기지 않음"""
        h = self.login("kim")
        cid = self.upload(h, "right_turn_left_straight").json()["id"]

        class Deleting(fake.FakeAnalyzer):
            def analyze(self, video_path, start_time=None, *, progress=None, **kw):
                self_case = os.path.basename(os.path.dirname(video_path))
                store.delete(self_case)                           # API의 DELETE와 같음
                open(os.path.join(os.path.dirname(video_path), "partial.json"), "w").close()   # 분석기가 쓰던 파일
                progress(10)
                return super().analyze(video_path, start_time, progress=progress, **kw)

        with mock.patch.object(analyzer, "get_analyzer", lambda name=None: Deleting()):
            os.makedirs(store.case_dir(cid), exist_ok=True)
            self.assertTrue(worker.run_once())
        self.assertIsNone(store.get(cid))
        self.assertFalse(os.path.exists(store.case_dir(cid)))

    def test_exception_becomes_failed(self):
        h = self.login("kim")
        cid = self.upload(h, "right_turn_left_straight").json()["id"]
        with mock.patch.object(bb_api.adapter, "build", side_effect=RuntimeError("boom")):
            worker.run_once()
        self.assertEqual(store.get(cid)["status"], "failed")
        self.assertFalse(worker.run_once())                       # 실패한 사건을 다시 꺼내지 않음

    def test_separate_process(self):
        """작업자를 진짜 별도 프로세스로 (--once): DB와 사건 폴더만으로 API와 주고받음"""
        h = self.login("kim")
        cid = self.upload(h, "right_turn_left_straight").json()["id"]
        env = dict(os.environ, MTM_DB=db.DB_PATH, MTM_CASES_DIR=db.CASES_DIR, HMTM_BB_CASES_DIR=store.BB_DIR,
                   HMTM_BB_ANALYZER="fake", PYTHONIOENCODING="utf-8")   # 별도 프로세스에는 대역이 없어 가짜 분석기로
        root = os.path.dirname(TESTS)
        p = subprocess.run([sys.executable, "-m", "src.blackbox.worker", "--once"], cwd=root, env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        view = self.c.get(f"/api/bb-cases/{cid}", headers=h).json()
        self.assertEqual(view["status"], "needs_answers", p.stderr)


class Review(ApiBase):
    """사고 순간이 불확실할 때 HMTM 방어 (fake 모드, API 스레드)"""

    def run_with(self, h, change, scenario="right_turn_left_straight", veh=True):
        real = fake.FakeAnalyzer.analyze

        def patched(an, *a, **kw):
            out = real(an, *a, **kw)
            change(out)
            return out

        with mock.patch.object(fake.FakeAnalyzer, "analyze", patched):
            return self.run_case(h, scenario=scenario, veh=vehicle() if veh else None)

    def assert_no_vehicle_use(self, view):
        self.assertEqual((view["sync"]["grade"], view["sync"]["reason"]), ("none", "collision_uncertain"))
        self.assertIsNone(view["sync"]["t_collision_ms"])
        self.assertIsNone(view["event"]["t_event"])
        self.assertEqual(view["auto_answers"], [])
        self.assertIsNone(view["vehicle_timeline"])
        self.assertEqual(view["vehicle_effects"], [])
        self.assertEqual(view["result_with_vehicle"]["fault_by_party"], view["result"]["fault_by_party"])

    def test_confident_collision_uses_vehicle(self):
        h = self.login("kim")
        view = self.run_with(h, lambda o: o["facts"]["collision"].update(t_confidence=0.8))
        self.assertEqual(view["sync"]["grade"], "coarse")
        self.assertEqual(view["event"]["t_event"], T)
        self.assertFalse(view["collision_review"]["needed"])
        self.assertEqual(view["collision_review"]["candidates"], [])

    def test_low_confidence(self):
        h = self.login("kim")
        view = self.run_with(h, lambda o: o["facts"]["collision"].update(t_confidence=0.2))
        self.assert_no_vehicle_use(view)
        rv = view["collision_review"]
        self.assertEqual((rv["needed"], rv["reason"], rv["t_confidence"]), (True, "low_confidence", 0.2))
        self.assertEqual(rv["candidates"][0]["t"], view["event"]["collision_t"])   # 분석기가 후보를 안 주면 그 시각 하나
        self.assertTrue(rv["message"])
        self.assertEqual(view["data_quality"]["sync_reason"], "collision_uncertain")
        self.assertTrue(view["sync"]["reason_text"])
        listed = self.c.get("/api/bb-cases", headers=h).json()[0]
        self.assertTrue(listed["collision_review_needed"])
        # 답을 해도(다시 판정) 표시와 시각 맞추기는 그대로
        r = self.c.put(f"/api/bb-cases/{view['id']}/answers", json={"answers": {"road.signal_present": False}},
                       headers=h).json()
        self.assertTrue(r["collision_review"]["needed"])
        self.assertEqual(r["sync"]["grade"], "none")
        self.assertEqual(r["auto_answers"], [])

    def test_guess_collision(self):
        h = self.login("kim")
        cands = [{"t": 4.0, "frame": 20, "source": "jolt"}, {"t": 7.2, "frame": 36, "source": "stop"}]

        def change(o):
            o["facts"]["collision"]["t_source"] = "guess"
            o["hints"]["collision_candidates"] = cands
        view = self.run_with(h, change)
        self.assert_no_vehicle_use(view)
        self.assertEqual((view["collision_review"]["reason"], view["collision_review"]["candidates"]), ("guess", cands))

    def test_no_record_keeps_reason(self):
        """차량 기록이 없으면 sync reason은 no_vehicle_record 그대로 (앱 "차량 기록 없음")"""
        h = self.login("kim")
        view = self.run_with(h, lambda o: o["facts"]["collision"].update(t_confidence=0.2), veh=False)
        self.assertEqual(view["sync"]["reason"], "no_vehicle_record")
        self.assertTrue(view["collision_review"]["needed"])

    def test_no_collision(self):
        h = self.login("kim")
        cands = [{"t": 11.5, "frame": 57, "source": "video_end", "reason": "never_moving"}]
        view = self.run_with(h, lambda o: o["hints"].update(collision_candidates=cands), scenario="no_collision")
        self.assertEqual(view["status"], "no_collision")
        self.assertEqual(view["sync"]["grade"], "none")
        rv = view["collision_review"]
        self.assertEqual((rv["needed"], rv["reason"], rv["t"], rv["candidates"]), (True, "no_collision", None, cands))
        self.assertTrue(self.c.get("/api/bb-cases", headers=h).json()[0]["collision_review_needed"])

    def test_review_unit(self):
        ok = {"status": "ok", "facts": {"collision": {"t": 3.0, "t_confidence": 0.5}}, "hints": {}}
        self.assertFalse(analyzer.collision_review(ok)["needed"])          # 경계값 0.5는 확인 필요 아님
        failed = {"status": "failed", "facts": None}
        self.assertFalse(analyzer.collision_review(failed)["needed"])


if __name__ == "__main__":
    unittest.main()
