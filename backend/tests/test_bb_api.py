"""블랙박스 사건 API 시험 (docs/design-blackbox.md 3절)

  python -m pytest tests/test_bb_api.py

POST /api/bb-cases(multipart) → 분석 스레드 → GET. 시나리오별 업로드 → 판정, 차량 기록 있음/없음,
분석 뒤 영상 삭제(HMTM_KEEP_VIDEO=1이면 보관), 인증·오류, 탈퇴, 서버 재시작 때 다시 분석.
시험 영상은 테스트 안에서 OpenCV로 만든다. DB·사건 폴더는 임시 폴더.
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from bb_common import make_video
from src.blackbox import api as bb_api
from src.blackbox import fake, store
from src.server import db

KST = dt.timezone(dt.timedelta(hours=9))
NAME = "20261109_143012_F.mp4"
S0 = int(dt.datetime(2026, 11, 9, 14, 30, 12, tzinfo=KST).timestamp() * 1000)
DURATION = 12.0                       # 시험 영상 길이 (초)
K = DURATION / 30.0                   # 시나리오(30초) → 시험 영상 시각 비율
T = S0 + int(round(18.2 * K * 1000))  # 충돌 시각 (차량 시계, offset 0)


def samples(start=-12000, end=2000, speed=40.0, gear="D", turn="OFF", brake=False, step=100):
    def val(x, r):
        return x(r) if callable(x) else x
    return [{"t": T + r, "speedKmh": val(speed, r), "gear": val(gear, r), "turnSignal": val(turn, r),
             "brake": val(brake, r)} for r in range(start, end + 1, step)]


def vehicle(**kw):
    s = samples(**kw)
    return {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle": {"cls": "car"},
            "location": None, "client": {"app_version": "0.1.0"}}


REVERSE = lambda r: "R" if r >= -2500 else "D"



def vs(answer):
    """answers[키]에서 값·출처만 (2부에서 evidence가 더해짐)"""
    return {"value": answer["value"], "source": answer["source"]}

class ApiBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vtmp = tempfile.mkdtemp(prefix="hmtm_bbvid_")
        cls.video = make_video(os.path.join(cls.vtmp, NAME), seconds=DURATION, fps=5.0)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.vtmp, ignore_errors=True)

    def setUp(self):
        from fastapi.testclient import TestClient
        from src.server import app as server, auth
        self.tmp = tempfile.mkdtemp(prefix="hmtm_bbapi_")
        self._old = db.CASES_DIR, db.DB_PATH, store.BB_DIR
        db.CASES_DIR, db.DB_PATH = self.tmp, os.path.join(self.tmp, "server.db")
        store.BB_DIR = os.path.join(self.tmp, "bb_cases")
        self.auth = auth
        self._verifiers = dict(auth.VERIFIERS)
        auth.VERIFIERS["kakao"] = lambda token: "kakao-" + token
        self.c = TestClient(server.app)
        self.env = mock.patch.dict(os.environ, {"HMTM_BB_ANALYZER": "fake", bb_api.KEEP_ENV: ""})
        self.env.start()

    def tearDown(self):
        self.wait_idle()
        self.env.stop()
        self.auth.VERIFIERS.clear()
        self.auth.VERIFIERS.update(self._verifiers)
        db.CASES_DIR, db.DB_PATH, store.BB_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def login(self, name, signup=True):
        r = self.c.post("/api/auth/kakao", json={"token": name}).json()
        h = {"Authorization": "Bearer " + r["access"]}
        if signup:
            self.c.put("/api/me", json={"nickname": name, "agree_terms": True}, headers=h)
        return h

    def upload(self, h, scenario=None, veh=None, meta=None, name=NAME, path=None):
        data = {}
        if scenario is not None:
            data["scenario"] = scenario
        if veh is not None:
            data["vehicle"] = veh if isinstance(veh, str) else json.dumps(veh)
        if meta is not None:
            data["meta"] = meta if isinstance(meta, str) else json.dumps(meta)
        with open(path or self.video, "rb") as f:
            return self.c.post("/api/bb-cases", files={"video": (name, f, "video/mp4")}, data=data, headers=h)

    @staticmethod
    def wait_idle(timeout=20):
        end = time.time() + timeout
        while not bb_api.idle():
            if time.time() > end:
                raise AssertionError("분석이 끝나지 않았어요")
            time.sleep(0.02)

    def result(self, h, cid):
        self.wait_idle()
        r = self.c.get(f"/api/bb-cases/{cid}", headers=h)
        self.assertEqual(r.status_code, 200)
        return r.json()

    def run_case(self, h, **kw):
        r = self.upload(h, **kw)
        self.assertEqual(r.status_code, 202, r.text)
        return self.result(h, r.json()["id"])


class Api(ApiBase):
    def test_post_then_get(self):
        h = self.login("kim")
        r = self.upload(h, "right_turn_left_straight")
        self.assertEqual(r.status_code, 202)
        first = r.json()
        self.assertEqual(first["status"], "analyzing")
        self.assertTrue(first["id"])
        view = self.result(h, first["id"])
        self.assertEqual(view["status"], "needs_answers")
        self.assertEqual(view["id"], first["id"])
        self.assertEqual(view["analysis"]["analyzer"], {"name": "fake", "version": fake.VERSION})
        self.assertAlmostEqual(view["analysis"]["video"]["duration_s"], DURATION, places=2)
        self.assertEqual(view["sync"]["start_source"], "filename")
        self.assertEqual(view["sync"]["start_ms"], S0)
        row = store.get(first["id"])
        self.assertEqual((row["analyzer_name"], row["analyzer_version"]), ("fake", fake.VERSION))
        self.assertEqual(row["bb_facts"]["schema_version"], "bb-0.2")

    def test_video_deleted_after_analysis(self):
        """확정 Q13: 분석이 끝나면 원본 영상 삭제, bb_facts·판정만 남음.
        no_collision은 예외로 사용자가 사고 순간을 고를 때까지 둠 (test_bb_pick)"""
        h = self.login("kim")
        for scn in ("right_turn_left_straight", "unsupported", "analyzer_broken"):
            view = self.run_case(h, scenario=scn)
            self.assertIsNone(bb_api.video_file(view["id"]), scn)
            row = store.get(view["id"])
            self.assertFalse(row["video_kept"])
            self.assertIsNotNone(row["bb_facts"])
            self.assertFalse([n for n in os.listdir(store.case_dir(view["id"])) if n.startswith("video")])

    def test_keep_video_env(self):
        h = self.login("kim")
        with mock.patch.dict(os.environ, {bb_api.KEEP_ENV: "1"}):
            view = self.run_case(h, scenario="right_turn_left_straight")
        path = bb_api.video_file(view["id"])
        self.assertTrue(path and os.path.getsize(path) > 0)
        self.assertTrue(store.get(view["id"])["video_kept"])

    def test_auth_and_not_found(self):
        r = self.upload({})
        self.assertEqual(r.status_code, 401)
        kim, lee = self.login("kim"), self.login("lee")
        view = self.run_case(kim, scenario="right_turn_left_straight")
        r = self.c.get(f"/api/bb-cases/{view['id']}", headers=lee)
        self.assertEqual((r.status_code, r.json()["error"]), (404, "bb_case_not_found"))
        r = self.c.get("/api/bb-cases/nope", headers=kim)
        self.assertEqual((r.status_code, r.json()["error"]), (404, "bb_case_not_found"))

    def test_bad_requests_make_no_case(self):
        h = self.login("kim")
        empty = os.path.join(self.tmp, "empty.mp4")
        open(empty, "wb").close()
        long_range = vehicle()
        long_range["range"]["from"] = long_range["range"]["to"] - 301_000
        unsorted = vehicle()
        unsorted["samples"][3]["t"] = unsorted["samples"][1]["t"] - 1
        cases = [
            (dict(meta="{nope"), 422, "request_invalid"),
            (dict(meta="[1]"), 422, "request_invalid"),
            (dict(veh="{nope"), 422, "request_invalid"),
            (dict(veh=long_range), 422, "range_invalid"),
            (dict(veh=unsorted), 422, "samples_unsorted"),
            (dict(veh=dict(vehicle(), samples=[])), 422, "samples_empty"),
            (dict(veh=dict(vehicle(), location={"lat": 1})), 422, "location_unsupported"),
            (dict(scenario="nope"), 422, "scenario_unknown"),
            (dict(path=empty), 422, "video_empty"),
        ]
        for kw, status, code in cases:
            r = self.upload(h, **kw)
            self.assertEqual((r.status_code, r.json()["error"]), (status, code), code)
        r = self.c.post("/api/bb-cases", data={"scenario": "unsupported"}, headers=h)
        self.assertEqual(r.status_code, 422)                       # 영상 칸 없음 (FastAPI 검사)
        with store.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM bb_cases").fetchone()[0], 0)

    def test_mtm_analyzer_not_ready(self):
        h = self.login("kim")
        with mock.patch.dict(os.environ, {"HMTM_BB_ANALYZER": "mtm"}):
            r = self.upload(h)
        self.assertEqual((r.status_code, r.json()["error"]), (503, "analyzer_not_ready"))

    def test_withdraw_deletes_bb_cases(self):
        h = self.login("kim")
        with mock.patch.dict(os.environ, {bb_api.KEEP_ENV: "1"}):
            view = self.run_case(h, scenario="right_turn_left_straight")
        self.assertEqual(self.c.delete("/api/me", headers=h).status_code, 204)
        self.assertIsNone(store.get(view["id"]))
        self.assertFalse(os.path.exists(store.case_dir(view["id"])))

    def test_resume_on_start(self):
        """서버가 분석 중에 꺼졌다면: 켤 때 analyzing 사건을 다시 넣어 끝냄"""
        cid = store.create("u1", {"filename": NAME}, None, "rear_end_lead")
        shutil.copy(self.video, os.path.join(store.case_dir(cid), "video.mp4"))
        bb_api.resume()
        self.wait_idle()
        row = store.get(cid)
        self.assertEqual(row["status"], "needs_answers")
        self.assertIsNone(bb_api.video_file(cid))

    def test_analysis_error_becomes_failed(self):
        h = self.login("kim")
        with mock.patch.object(bb_api.adapter, "build", side_effect=RuntimeError("boom")):
            view = self.run_case(h, scenario="right_turn_left_straight")
        self.assertEqual((view["status"], view["analysis"]["reason"]), ("failed", "server_error"))

    def test_scenario_from_filename(self):
        h = self.login("kim")
        view = self.run_case(h, name="20261109_143012_F__scn-rear_end_lead.mp4")
        self.assertEqual(view["analysis"]["scenario"]["scenario"], "rear_end_lead")
        self.assertEqual(view["analysis"]["scenario"]["chosen_by"], "filename")
        self.assertEqual(view["sync"]["start_ms"], S0)


class Scenarios(ApiBase):
    """시나리오별 업로드 → 판정. 차량 기록 없음 / 있음"""

    def test_each_scenario_without_vehicle(self):
        h = self.login("kim")
        for name in fake.scenario_names():
            exp = fake.load_scenario(name)["fake"]["expect"]
            view = self.run_case(h, scenario=name)
            self.assertEqual(view["data_quality"]["vehicle_record"] if "data_quality" in view else False, False)
            if "rule_id" not in exp:
                self.assertEqual((view["status"], view["analysis"]["reason"]), (exp["status"], exp["reason"]), name)
                self.assertNotIn("result", view)
                continue
            self.assertEqual(view["sync"]["grade"], "none")
            self.assertEqual(view["sync"]["reason"], "no_vehicle_record")
            if not exp["answers"]:
                self.assertEqual(view["status"], exp["status"], name)
                got = (view["result"]["status"], view["result"]["rule_id"], view["result"]["fault_by_party"])
                self.assertEqual(got, (exp["judge_status"], exp["rule_id"], exp["fault_by_party"]), name)

    def test_each_scenario_with_vehicle(self):
        """차량 기록(40km/h 직진, 지시등 없음)을 붙이면 coarse로 합쳐지고, 판정은 시나리오 값대로 나옴"""
        h = self.login("kim")
        for name in fake.scenario_names():
            exp = fake.load_scenario(name)["fake"]["expect"]
            view = self.run_case(h, scenario=name, veh=vehicle())
            if "rule_id" not in exp:
                self.assertEqual(view["status"], exp["status"], name)
                self.assertTrue(store.get(view["id"])["vehicle"])
                continue
            self.assertEqual((view["sync"]["grade"], view["data_quality"]["vehicle_record"]), ("coarse", True), name)
            self.assertEqual(vs(view["answers"]["parties.ego.cls"]), {"value": "car", "source": "vehicle"}, name)
            self.assertEqual(view["event"]["t_event"], T, name)
            self.assertEqual(view["data_quality"]["samples"], len(vehicle()["samples"]), name)
            if not exp["answers"]:
                self.assertEqual(view["result"]["rule_id"], exp["rule_id"], name)

    def test_reverse_vehicle_beats_video(self):
        h = self.login("kim")
        view = self.run_case(h, scenario="ego_reverse_video_wrong", veh=vehicle(gear=REVERSE, speed=3.0))
        # 차량 기록은 참고 자료 (4.4): 기본 판정은 영상 값, 차량 기록(후진)은 result_with_vehicle·vehicle_effects로
        self.assertEqual(vs(view["answers"]["parties.ego.movement"]), {"value": "straight", "source": "video"})
        self.assertEqual(view["vehicle_effects"], [])   # 아직 둘 다 도표를 못 정함 (진입 순서 질문이 남음)
        r = self.c.put(f"/api/bb-cases/{view['id']}/answers", json={"answers": {"intersection_entry_order": "same_time"}},
                       headers=h).json()
        e = {x["field"]: x for x in r["vehicle_effects"]}["parties.ego.movement"]
        self.assertEqual((e["value"], e["applied"], e["value_label"]), ("reverse", True, "후진"))
        self.assertEqual((r["result"]["rule_id"], r["result_with_vehicle"]["status"]), ("차12-1(가)", "no_rule"))
        kinds = {c["field"]: c["kind"] for c in view["source_conflicts"]}
        self.assertEqual(kinds["parties.ego.movement"], "vehicle_vs_video")
        self.assertEqual([a["field"] for a in view["auto_answers"]], ["parties.ego.movement"])
        # 차량 기록 없이 올리면 영상 값(직진)
        view = self.run_case(h, scenario="ego_reverse_video_wrong")
        self.assertEqual(vs(view["answers"]["parties.ego.movement"]), {"value": "straight", "source": "video"})

    def test_vehicle_without_start_time_is_none(self):
        """파일 이름에 시각이 없고 meta도 없으면 차량 기록을 붙여도 규칙을 쓰지 않음 (none)"""
        h = self.login("kim")
        view = self.run_case(h, scenario="ego_reverse_video_wrong", veh=vehicle(gear=REVERSE), name="clip.mp4")
        self.assertEqual((view["sync"]["grade"], view["sync"]["reason"]), ("none", "no_start_time"))
        self.assertEqual(view["answers"]["parties.ego.movement"]["source"], "video")

    def test_app_start_time_candidate(self):
        """앱이 meta.recorded_at으로 보낸 시각(파일 이름 시각이 없을 때)으로도 coarse"""
        h = self.login("kim")
        meta = {"recorded_at": [{"source": "metadata", "start_ms": S0}], "mtime_ms": S0 + 12_000}
        view = self.run_case(h, scenario="ego_reverse_video_wrong", veh=vehicle(gear=REVERSE, speed=3.0),
                             name="clip.mp4", meta=meta)
        self.assertEqual((view["sync"]["grade"], view["sync"]["start_source"]), ("coarse", "metadata"))
        self.assertEqual([c["source"] for c in view["sync"]["candidates"]], ["metadata", "mtime"])
        self.assertIn("vehicle_vs_video", [c["kind"] for c in view["source_conflicts"]])   # 차량 기록(후진)을 씀

    def test_vehicle_cropped_to_video_window(self):
        """차량 기록은 [S0 − 15초, S0 + 길이 + 15초]로 잘라 씀 (Q12)"""
        h = self.login("kim")
        s = samples(start=-60_000, end=60_000, step=500)
        veh = {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle": {"cls": "truck"}}
        view = self.run_case(h, scenario="right_turn_left_straight", veh=veh)
        w = {"from": S0 - 15_000, "to": S0 + int(DURATION * 1000) + 15_000}
        self.assertEqual(view["event"]["range"], w)
        self.assertEqual(view["data_quality"]["samples"], len([x for x in s if w["from"] <= x["t"] <= w["to"]]))
        self.assertEqual(view["parties"]["ego"]["cls"], "truck")
        self.assertEqual(len(store.get(view["id"])["vehicle"]["samples"]), len(s))   # 원본은 그대로 저장


if __name__ == "__main__":
    unittest.main()


class ListCases(ApiBase):
    """GET /api/bb-cases: 내 사건 목록 (지난 분석 화면)"""

    def test_list_newest_first_and_paging(self):
        h = self.login("kim")
        ids = [self.run_case(h, scenario=n)["id"] for n in
               ("right_turn_left_straight", "ped_crosswalk_unsignalized", "unsupported")]
        other = self.login("lee")
        self.run_case(other, scenario="bike_crossing_side")
        r = self.c.get("/api/bb-cases", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()
        self.assertEqual([x["id"] for x in items], ids[::-1])      # 남의 사건은 안 보임, 최근 것부터
        un, ped, car = items
        self.assertEqual((un["status"], un["reason"], un["rule_id"]), ("unsupported", "not_blackbox", None))
        self.assertEqual((ped["status"], ped["rule_id"], ped["chapter"]), ("needs_answers", "보13", "car_pedestrian"))
        self.assertEqual(ped["fault_display"]["kind"], "pedestrian_only")
        self.assertEqual(ped["other_cls"], {"value": "pedestrian", "label": "보행자", "source": "video"})
        detail = self.c.get(f"/api/bb-cases/{car['id']}", headers=h).json()
        self.assertEqual((car["rule_id"], car["fault_by_party"], car["remaining_count"], car["provisional"]),
                         ("차13-1", {"ego": 60, "other": 40}, detail["remaining_count"], True))
        self.assertEqual(car["filename"], NAME)
        self.assertIsNone(car["reason"])
        page = self.c.get("/api/bb-cases", params={"limit": 2}, headers=h).json()
        self.assertEqual([x["id"] for x in page], ids[:0:-1])
        rest = self.c.get("/api/bb-cases", params={"limit": 2, "before": page[-1]["created_at"]}, headers=h).json()
        self.assertEqual([x["id"] for x in rest], [x["id"] for x in items if x["created_at"] < page[-1]["created_at"]])

    def test_list_empty_and_auth(self):
        h = self.login("park")
        self.assertEqual(self.c.get("/api/bb-cases", headers=h).json(), [])
        self.assertEqual(self.c.get("/api/bb-cases").status_code, 401)
