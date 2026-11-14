"""블랙박스 사건 PUT answers·DELETE 시험 (bb-flow 2부 2·3단계, docs/design-blackbox.md 3.2)

  python -m pytest tests/test_bb_answers.py

PUT /api/bb-cases/{id}/answers: 저장한 bb_facts·차량 기록으로 처음부터 다시 판정 (분석기를 다시 부르지 않음),
사용자 답이 차량·영상 값과 다르면 source_conflicts. DELETE: 204, 행·사건 폴더 삭제, 분석 중이면 분석도 멈춤.
"""
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from src.blackbox import api as bb_api
from src.blackbox import fake, store
from test_bb_api import NAME, REVERSE, ApiBase, vehicle, vs


class PutAnswers(ApiBase):
    def put(self, h, cid, answers):
        return self.c.put(f"/api/bb-cases/{cid}/answers", json={"answers": answers}, headers=h)

    def test_answer_rejudges_and_saves(self):
        h = self.login("kim")
        first = self.run_case(h, scenario="right_turn_left_straight")
        r = self.put(h, first["id"], {"road.signal_present": False, "road.center_line": True})
        self.assertEqual(r.status_code, 200, r.text)
        view = r.json()
        self.assertEqual(vs(view["answers"]["road.signal_present"]), {"value": False, "source": "user"})
        self.assertNotIn("road.signal_present", [q["field"] for q in view["remaining"]])
        self.assertGreater(view["updated_at"], first["updated_at"])
        self.assertEqual((view["id"], view["created_at"]), (first["id"], first["created_at"]))
        self.assertEqual(view["analysis"], first["analysis"])
        self.assertEqual(view["sync"], first["sync"])
        self.assertEqual(self.c.get(f"/api/bb-cases/{first['id']}", headers=h).json(), view)
        self.assertEqual(store.get(first["id"])["answers"], {"road.signal_present": False, "road.center_line": True})
        # 통째로 바꿈: 빈 답이면 처음 결과로 돌아감
        back = self.put(h, first["id"], {}).json()
        self.assertEqual(back["remaining"], first["remaining"])

    def test_no_reanalysis(self):
        """영상은 이미 지웠으므로 분석기를 부르지 않음"""
        h = self.login("kim")
        first = self.run_case(h, scenario="right_turn_left_straight")
        with mock.patch.object(bb_api.analyzer, "run", side_effect=AssertionError("다시 분석함")):
            r = self.put(h, first["id"], {"road.signal_present": False})
        self.assertEqual(r.status_code, 200, r.text)

    def test_answer_until_done(self):
        h = self.login("kim")
        view = self.run_case(h, scenario="right_turn_left_straight")
        user = {}
        for _ in range(5):
            if not view["remaining"]:
                break
            user.update({q["field"]: q["model_guess"] if q["model_guess"] is not None else q["options"][-1]
                         for q in view["remaining"]})
            view = self.put(h, view["id"], user).json()
        self.assertEqual((view["status"], view["remaining_count"]), ("done", 0))
        self.assertFalse(view["result"]["provisional"])
        self.assertEqual(view["result"]["rule_id"], "차13-1")

    def test_user_vs_video_conflict(self):
        h = self.login("kim")
        first = self.run_case(h, scenario="right_turn_left_straight")
        view = self.put(h, first["id"], {"parties.other.entry_from": "right"}).json()
        self.assertEqual(vs(view["answers"]["parties.other.entry_from"]), {"value": "right", "source": "user"})
        c = [x for x in view["source_conflicts"] if x["field"] == "parties.other.entry_from"][0]
        self.assertEqual(c["kind"], "user_vs_video")
        self.assertEqual([(o["value"], o["source"]) for o in c["others"]], [("left", "video")])
        self.assertEqual(view["answer_conflicts"], [])          # 차량 명세 v0.3 칸은 user_vs_vehicle만

    def test_user_vs_vehicle_conflict(self):
        h = self.login("kim")
        first = self.run_case(h, scenario="ego_reverse_video_wrong", veh=vehicle(gear=REVERSE, speed=3.0))
        self.assertEqual(first["answers"]["parties.ego.movement"]["source"], "video")
        self.assertEqual([c["kind"] for c in first["source_conflicts"] if c["field"] == "parties.ego.movement"],
                         ["vehicle_vs_video"])
        view = self.put(h, first["id"], {"parties.ego.movement": "straight"}).json()
        self.assertEqual(vs(view["answers"]["parties.ego.movement"]), {"value": "straight", "source": "user"})
        c = [x for x in view["source_conflicts"] if x["field"] == "parties.ego.movement"][0]
        self.assertEqual(c["kind"], "user_vs_vehicle")
        self.assertEqual(c["others"][0]["source"], "vehicle")   # 영상 값(직진)은 사용자 답과 같아 충돌 아님
        self.assertEqual([(a["field"], a["vehicle_value"], a["user_value"]) for a in view["answer_conflicts"]],
                         [("parties.ego.movement", "reverse", "straight")])
        self.assertEqual(view["data_quality"]["vehicle_record"], True)

    def test_errors(self):
        kim, lee = self.login("kim"), self.login("lee")
        view = self.run_case(kim, scenario="right_turn_left_straight")
        cid = view["id"]
        r = self.c.put(f"/api/bb-cases/{cid}/answers", json={"answers": [1]}, headers=kim)
        self.assertEqual((r.status_code, r.json()["error"]), (422, "answers_shape"))
        r = self.c.put(f"/api/bb-cases/{cid}/answers", content=b"{nope", headers=kim)
        self.assertEqual((r.status_code, r.json()["error"]), (422, "request_invalid"))
        r = self.put(kim, cid, {"nope": 1})
        self.assertEqual((r.status_code, r.json()["error"]), (422, "answer_invalid"))
        r = self.put(kim, cid, {"road.signal_present": "maybe"})
        self.assertEqual((r.status_code, r.json()["error"]), (422, "answer_invalid"))
        self.assertEqual(store.get(cid)["view"], view)          # 틀린 답은 저장하지 않음
        r = self.put(lee, cid, {})
        self.assertEqual((r.status_code, r.json()["error"]), (404, "bb_case_not_found"))
        nc = self.run_case(kim, scenario="no_collision")
        r = self.put(kim, nc["id"], {})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "bb_case_not_judged"))
        me = self.c.get("/api/me", headers=kim).json()
        aid = store.create(me["id"], {"filename": NAME}, None)   # 분석 줄에 넣지 않은 analyzing 사건
        r = self.put(kim, aid, {})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "bb_case_analyzing"))


class Delete(ApiBase):
    def test_delete(self):
        kim, lee = self.login("kim"), self.login("lee")
        with mock.patch.dict(os.environ, {bb_api.KEEP_ENV: "1"}):
            view = self.run_case(kim, scenario="right_turn_left_straight", veh=vehicle())
        cid = view["id"]
        self.assertTrue(bb_api.video_file(cid))
        r = self.c.delete(f"/api/bb-cases/{cid}", headers=lee)
        self.assertEqual((r.status_code, r.json()["error"]), (404, "bb_case_not_found"))
        r = self.c.delete(f"/api/bb-cases/{cid}", headers=kim)
        self.assertEqual((r.status_code, r.content), (204, b""))
        self.assertIsNone(store.get(cid))
        self.assertFalse(os.path.exists(store.case_dir(cid)))
        r = self.c.get(f"/api/bb-cases/{cid}", headers=kim)
        self.assertEqual((r.status_code, r.json()["error"]), (404, "bb_case_not_found"))
        self.assertEqual(self.c.delete(f"/api/bb-cases/{cid}", headers=kim).status_code, 404)

    def test_delete_while_analyzing_stops_analysis(self):
        """분석 중에 지우면 분석기가 진행률을 알릴 때 멈추고, 행·사건 폴더가 남지 않음"""
        h = self.login("kim")
        slow = fake.load_scenario("right_turn_left_straight")
        slow["fake"]["delay_sec"] = 3.0
        orig = fake.load_scenario
        with mock.patch.object(fake, "load_scenario", lambda n: slow if n == "right_turn_left_straight" else orig(n)):
            r = self.upload(h, "right_turn_left_straight")
            cid = r.json()["id"]
            end = time.time() + 5
            while store.get(cid)["progress"] == 0 and time.time() < end:   # 분석기가 돌기 시작할 때까지
                time.sleep(0.02)
            t0 = time.time()
            self.assertEqual(self.c.delete(f"/api/bb-cases/{cid}", headers=h).status_code, 204)
            self.wait_idle()
        self.assertLess(time.time() - t0, 2.0)                  # 3초 지연을 다 기다리지 않음
        self.assertIsNone(store.get(cid))
        self.assertFalse(os.path.exists(store.case_dir(cid)))
        self.assertFalse(bb_api._cancelled)

    def test_delete_queued_case(self):
        """줄에서 기다리던 사건을 지우면 분석하지 않음"""
        h = self.login("kim")
        me_id = self.c.get("/api/me", headers=h).json()["id"]
        cid = store.create(me_id, {"filename": NAME}, None, "right_turn_left_straight")
        with bb_api._lock:
            bb_api._busy.add(cid)                                # 줄에 들어간 상태 (아직 안 돎)
        self.assertEqual(self.c.delete(f"/api/bb-cases/{cid}", headers=h).status_code, 204)
        with mock.patch.object(bb_api.analyzer, "run", side_effect=AssertionError("분석함")):
            bb_api.enqueue(cid)                                  # 이제 차례가 옴
            self.wait_idle()
        self.assertFalse(bb_api._cancelled)
        self.assertIsNone(store.get(cid))
        self.assertFalse(os.path.exists(store.case_dir(cid)))


if __name__ == "__main__":
    unittest.main()
