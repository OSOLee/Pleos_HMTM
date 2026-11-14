"""차량 사건 API 1부 시험: 저장(store), 어댑터(adapter), POST·GET (docs/api-spec.md 2.1, 2.3, 3, 8)

  python -m pytest tests/test_vehicle_api.py

합성 기록(100ms 간격)만 쓴다. 영상·평가 데이터가 없어도 돈다. DB는 임시 폴더에 만든다.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)   # 판정 모듈(backend/judge) 경로가 backend 기준
from src.server import db
from src.vehicle import adapter, store
from src.vehicle.samples import VehicleError, validate

T = 1_762_581_652_300   # 사고 시각 (epoch ms)


def build(start=-12000, end=2000, speed=40.0, gear="D", turn="OFF", brake=False, step=100):
    """T+start ~ T+end를 step ms 간격으로 기록. 각 값은 상수 또는 r(T 기준 ms) → 값 함수"""
    def val(x, r):
        return x(r) if callable(x) else x
    return [{"t": T + r, "speedKmh": val(speed, r), "gear": val(gear, r), "turnSignal": val(turn, r),
             "brake": val(brake, r)} for r in range(start, end + 1, step)]


def body(samples=None, **over):
    """POST 요청 본문. 구간은 T-12초 ~ T+2초"""
    b = {"range": {"from": T - 12000, "to": T + 2000}, "t_event": T, "t_event_source": "hard_brake",
         "samples": build() if samples is None else samples, "vehicle": {"cls": "car"}, "location": None,
         "client": {"app_version": "0.1.0"}}
    b.update(over)
    return b


class TempDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hmtm_vehicle_")
        self._old = db.CASES_DIR, db.DB_PATH
        db.CASES_DIR, db.DB_PATH = self.tmp, os.path.join(self.tmp, "server.db")

    def tearDown(self):
        db.CASES_DIR, db.DB_PATH = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class Store(TempDB):
    RECORD = {"view": {"status": "done", "auto_answers": [], "questions": []},
              "rule_results": [{"field": "parties.ego.movement", "determined": False}],
              "rules": ["movement_v0"], "judge_version": "0.13.1"}

    def test_table_in_same_db_file(self):
        """기존 서버 표와 같은 파일에 vehicle_cases가 생김"""
        db.row("SELECT 1")   # 기존 표 먼저
        with store.connect():
            pass
        con = sqlite3.connect(db.DB_PATH)
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        con.close()
        self.assertTrue({"users", "cases", "vehicle_cases"} <= names)

    def test_create_and_get(self):
        req = {"t_event": T, "samples": build(-3000, 0)}
        view = store.create("u1", req, {}, self.RECORD)
        self.assertEqual(view["status"], "done")
        self.assertEqual(view["created_at"], view["updated_at"])
        row = store.get(view["id"])
        self.assertEqual(row["owner"], "u1")
        self.assertEqual(row["view"], view)
        self.assertEqual(row["request"], req)
        self.assertEqual(row["rules"], ["movement_v0"])
        self.assertEqual(row["judge_version"], "0.13.1")
        self.assertIsNone(store.get("nope"))


SLOW_DOWN = lambda r: 40.0 if r < -3000 else 12.0   # 사고 3초 전부터 12km/h로 줄임 → 서행 true
RIGHT_ON = lambda r: "RIGHT" if r >= -6000 else "OFF"   # 사고 6초 전부터 RIGHT
CROSS = {"parties.other.entry_from": "left", "parties.other.movement": "straight", "parties.other.cls": "car"}


class Adapter(unittest.TestCase):
    def run_case(self, user=None, **kw):
        return adapter.build(validate(body(build(**kw))), user)["view"]

    def test_no_answers(self):
        """답 없이(POST): 자동 답변·추정값과 기본값으로 채운 임시 결과"""
        v = self.run_case(speed=SLOW_DOWN, turn=RIGHT_ON)
        auto = {a["field"]: a for a in v["auto_answers"]}
        self.assertEqual(set(auto), {"parties.ego.slowed_before_entry"})   # 진행 방향이 안 정해져 지시등은 계산 안 함
        a = auto["parties.ego.slowed_before_entry"]
        self.assertEqual((a["value"], a["source"], a["rule"]), (True, "vehicle", "slowed_v0"))
        self.assertEqual(set(a), {"field", "value", "source", "rule", "evidence"})   # 3절 모양만 (차량 기록을 넣은 판정 기준)
        self.assertIn("40km/h → 직전 12km/h", a["evidence"]["text"])
        qs = {q["field"]: q for q in v["questions"]}
        # 차량 기록은 참고 자료 (2026-11-10, design-blackbox 4.4): 자동 답변한 질문도 남고 차량 기록 값은 vehicle_hint로
        # (서행 질문은 진행 방향을 모르는 기본 판정에서는 나오지 않음. 차량 기록을 넣은 판정에서만 자동 답변)
        self.assertNotIn("parties.ego.slowed_before_entry", v["answers"])
        mv = qs["parties.ego.movement"]
        self.assertEqual((mv["model_guess"], mv["guess_source"]), (None, None))
        self.assertEqual((mv["vehicle_hint"]["value"], mv["vehicle_hint"]["determined"]), ("right_turn", False))
        self.assertIn("오른쪽 지시등", mv["vehicle_hint"]["text"])
        self.assertEqual(v["status"], "needs_answers")
        self.assertTrue(v["result"]["provisional"])
        self.assertEqual(v["answers"]["parties.ego.cls"], {"value": "car", "source": "vehicle"})
        self.assertEqual(v["answers"]["road.wider_road"], {"value": "equal", "source": "default"})   # 8.4
        self.assertIn("road.wider_road", v["result"]["auto_filled"])

    def test_question_shape(self):
        """2.6: 영상 전용 키·질문이 없고, 당사자 이름은 내 차/상대, 새 키가 다 있음"""
        v = self.run_case(user={"parties.ego.movement": "left_turn", **CROSS})
        for q in v["questions"]:
            self.assertFalse({"evidence_frame", "image", "light_hints"} & set(q), q["field"])
            self.assertNotIn("lane_marking", q["field"])
            for k in ("model_guess", "guess_source", "guess_evidence", "default", "optional", "group", "depends_on"):
                self.assertIn(k, q, q["field"])
            text = q["question"] + " ".join(map(str, q.get("choices") or []))
            self.assertNotIn("ego번", text)
            self.assertNotIn("other번", text)

    def test_right_turn_vs_left_straight(self):
        """8.4 확인 사례: 내 차 우회전, 상대 왼쪽 길 직진, 도로 폭 답 없음 → equal로 채워 차13-1 60:40"""
        v = self.run_case(user={"parties.ego.movement": "right_turn", **CROSS}, speed=SLOW_DOWN, turn=RIGHT_ON)
        auto = {a["field"]: a["value"] for a in v["auto_answers"]}
        self.assertEqual(auto["parties.ego.turn_signal_used"], True)
        r = v["result"]
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["rule_id"], "차13-1")
        self.assertEqual(r["fault_by_party"], {"ego": 60, "other": 40})
        self.assertEqual(r["base_fault_by_party"], {"ego": 60, "other": 40})
        self.assertTrue(all(u["party"] in ("ego", "other") for u in r["unverifiable_factors"]))
        self.assertEqual(v["answers"]["parties.other.entry_from"], {"value": "left", "source": "user"})
        self.assertEqual(v["parties"]["other"]["cls"], "car")

    def test_vehicle_modifier_needs_no_proof(self):
        """직진 대 직진 동시 진입: 차량 기록의 서행으로 -10, 출처 vehicle, 입증 필요 없음 (2.7, D6)"""
        rec = adapter.build(validate(body(build(speed=SLOW_DOWN))),
                            {"parties.ego.movement": "straight", "intersection_entry_order": "same_time", **CROSS})
        v = rec["with_vehicle"]
        r = v["result"]
        self.assertEqual(r["rule_id"], "차12-1(가)")
        self.assertEqual(r["fault_by_party"], {"ego": 30, "other": 70})
        # 기본 판정(차량 기록 없이)은 40:60, 차이를 만든 기록은 서행
        self.assertEqual(rec["view"]["result"]["fault_by_party"], {"ego": 40, "other": 60})
        self.assertEqual(rec["view"]["result_with_vehicle"], r)
        e = rec["view"]["vehicle_effects"]
        self.assertEqual([(x["field"], x["ego_delta"], x["direction"], x["applied"]) for x in e],
                         [("parties.ego.slowed_before_entry", -10, "ego_less", True)])
        self.assertIn("km/h", e[0]["text"])
        m = next(m for m in r["modifiers"] if "slowed_before_entry" in m["facts"])
        self.assertEqual((m["party"], m["delta"], m["source"], m["needs_proof"]), ("ego", -10, "vehicle", False))

    def test_user_answer_overrides_vehicle(self):
        """사용자 답이 자동 답변과 다르면 사용자 답을 쓰고 answer_conflicts에 남김"""
        v = self.run_case(user={"parties.ego.movement": "straight", "intersection_entry_order": "same_time",
                                "parties.ego.slowed_before_entry": False, **CROSS}, speed=SLOW_DOWN)
        self.assertEqual(v["auto_answers"], [])
        self.assertEqual(v["answers"]["parties.ego.slowed_before_entry"], {"value": False, "source": "user"})
        c = v["answer_conflicts"]
        self.assertEqual([(x["field"], x["vehicle_value"], x["user_value"]) for x in c],
                         [("parties.ego.slowed_before_entry", True, False)])
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 40, "other": 60})

    def test_reverse(self):
        """사고 직전 3초 내내 R → 진행 방향 자동 답변 reverse, 특수 상황 reverse:ego 미리 고름 (4.2)"""
        v = adapter.build(validate(body(build(speed=lambda r: 5.0 if r >= -3000 else 0.0,
                                                gear=lambda r: "R" if r >= -3000 else "D"))))["with_vehicle"]
        auto = {a["field"]: a["value"] for a in v["auto_answers"]}
        self.assertEqual(auto["parties.ego.movement"], "reverse")
        qs = {q["field"]: q for q in v["questions"]}
        self.assertNotIn("parties.ego.movement", qs)
        sp = qs["situation.special"]
        self.assertIn("reverse:ego", sp["model_guess"])
        self.assertEqual(sp["guess_source"], "vehicle")

    def test_entry_conversion(self):
        """자기 차 기준 보기 → 동서남북 (2.6 방위 변환)"""
        self.assertEqual(adapter.to_mtm({"parties.other.entry_from": "right", "road.wider_road": "mine",
                                         "scene.place": "intersection", "road.center_line": True}),
                         {"parties.other.entry_from": "east", "road.wider_road": "north_south", "road.center_line": True})
        # 상대가 오른쪽 길에서 직진, 내 차 우회전 → 왼쪽 길일 때(차13-1)와 다른 도표
        v = self.run_case(user={"parties.ego.movement": "right_turn", **CROSS, "parties.other.entry_from": "right"})
        self.assertNotEqual(v["result"]["rule_id"], "차13-1")

    def test_data_quality(self):
        """빈 곳과 사고 앞 10초 동안 모두 null인 값 (2.5)"""
        rows = [s for s in build(turn=None) if not (T - 9000 < s["t"] < T - 6000)]
        v = adapter.build(validate(body(rows)))["view"]
        self.assertEqual(v["data_quality"]["gaps"], [{"from": T - 9000, "to": T - 6000}])
        self.assertEqual(v["data_quality"]["fields_missing"], ["turnSignal"])
        self.assertEqual(v["data_quality"]["samples"], len(rows))

    def test_bad_answer(self):
        with self.assertRaises(VehicleError) as e:
            self.run_case(user={"parties.other.entry_from": "north"})   # 자기 차 기준 보기가 아님
        self.assertEqual(e.exception.code, "answer_invalid")


class Defaults(unittest.TestCase):
    """2부: 어댑터 기본값의 출처 표시, 신호 유무 질문"""
    DEFAULTED = {"scene.place": "intersection", "scene.junction_type": "cross", "road.signal_present": False,
                 "road.wider_road": "equal"}

    def run_case(self, user=None, **kw):
        return adapter.build(validate(body(build(**kw))), user)["view"]

    def test_default_source(self):
        """장소·교차로 모양·신호·도로 폭: 질문의 추정값 출처와 쓴 답의 출처가 default (vehicle/user와 구분)"""
        v = self.run_case(user={"parties.ego.movement": "right_turn", **CROSS}, speed=SLOW_DOWN, turn=RIGHT_ON)
        qs = {q["field"]: q for q in v["questions"]}
        for f, val in self.DEFAULTED.items():
            self.assertEqual((qs[f]["model_guess"], qs[f]["guess_source"]), (val, "default"), f)
            self.assertEqual(v["answers"][f], {"value": val, "source": "default"}, f)
            self.assertIn(f, v["result"]["auto_filled"])
        self.assertNotIn("parties.ego.turn_signal_used", v["answers"])   # 기본 판정에는 차량 기록을 안 씀
        self.assertEqual(adapter.build(validate(body(build(speed=SLOW_DOWN, turn=RIGHT_ON))),
                                       {"parties.ego.movement": "right_turn", **CROSS})
                         ["with_vehicle"]["answers"]["parties.ego.turn_signal_used"]["source"], "vehicle")
        self.assertEqual(v["answers"]["parties.other.entry_from"]["source"], "user")
        # 사용자가 답하면 출처 user, 질문에서 빠지고 auto_filled에도 없음
        v = self.run_case(user={"parties.ego.movement": "right_turn", **CROSS, "scene.place": "intersection",
                                "road.wider_road": "mine"})
        self.assertEqual(v["answers"]["scene.place"], {"value": "intersection", "source": "user"})
        self.assertEqual(v["answers"]["road.wider_road"], {"value": "mine", "source": "user"})
        self.assertNotIn("road.wider_road", v["result"]["auto_filled"])
        self.assertNotIn("scene.place", {q["field"] for q in v["questions"]})

    def test_signal_question(self):
        """신호 유무는 기본값 질문이 아니라 사용자 질문 (default: false). 답이 없으면 없음 + 출처 default"""
        v = self.run_case(user={"parties.ego.movement": "right_turn", **CROSS}, speed=SLOW_DOWN, turn=RIGHT_ON)
        q = next(q for q in v["questions"] if q["field"] == "road.signal_present")
        self.assertEqual((q["default"], q["optional"], q["options"]), (False, False, [True, False]))
        self.assertEqual(v["status"], "needs_answers")
        auto = {a["field"] for a in v["auto_answers"]}
        self.assertIn("parties.ego.slowed_before_entry", auto)   # 기본값(신호 없음)으로 서행 자동 답변

    def test_signal_answered_present(self):
        """신호 있음으로 답하면: 출처 user, 신호 색 질문이 나오고, 서행 자동 답변(신호 없을 때만, 4.5)은 안 씀"""
        user = {"parties.ego.movement": "straight", **CROSS, "road.signal_present": True}
        v = self.run_case(user=user, speed=SLOW_DOWN)
        self.assertEqual(v["answers"]["road.signal_present"], {"value": True, "source": "user"})
        self.assertNotIn("road.signal_present", v["result"]["auto_filled"])
        fields = {q["field"] for q in v["questions"]}
        self.assertTrue({"parties.ego.signal_at_entry", "parties.other.signal_at_entry"} <= fields)
        self.assertEqual(v["auto_answers"], [])
        self.assertNotIn("parties.ego.slowed_before_entry", v["answers"])
        v = self.run_case(user={**user, "parties.ego.signal_at_entry": "green", "parties.other.signal_at_entry": "red"},
                          speed=SLOW_DOWN)
        self.assertEqual((v["result"]["rule_id"], v["result"]["fault_by_party"]), ("차1-1", {"ego": 0, "other": 100}))

    def test_signal_answered_absent(self):
        """신호 없음으로 답하면 출처 user, 같은 판정 (기본값과 결과가 같음)"""
        user = {"parties.ego.movement": "straight", "intersection_entry_order": "same_time", **CROSS}
        d = self.run_case(user=user, speed=SLOW_DOWN)
        u = self.run_case(user={**user, "road.signal_present": False}, speed=SLOW_DOWN)
        self.assertEqual(u["answers"]["road.signal_present"], {"value": False, "source": "user"})
        self.assertEqual(d["answers"]["road.signal_present"], {"value": False, "source": "default"})
        self.assertEqual((u["result"]["rule_id"], u["result"]["fault_by_party"]),
                         (d["result"]["rule_id"], d["result"]["fault_by_party"]))


class ApiBase(TempDB):
    """서버 시험 공통: 임시 DB, 카카오 로그인 대신"""
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from src.server import app as server, auth
        self.auth = auth
        self._verifiers = dict(auth.VERIFIERS)
        auth.VERIFIERS["kakao"] = lambda token: "kakao-" + token   # 카카오에 묻는 대신
        self.c = TestClient(server.app)

    def tearDown(self):
        self.auth.VERIFIERS.clear()
        self.auth.VERIFIERS.update(self._verifiers)
        super().tearDown()

    def login(self, name, signup=True):
        r = self.c.post("/api/auth/kakao", json={"token": name}).json()
        h = {"Authorization": "Bearer " + r["access"]}
        if signup:
            self.c.put("/api/me", json={"nickname": name, "agree_terms": True}, headers=h)
        return h

    def post(self, b, h):
        return self.c.post("/api/vehicle-cases", json=b, headers=h)


class Api(ApiBase):
    def test_post_then_get(self):
        h = self.login("kim")
        r = self.post(body(build(speed=SLOW_DOWN, turn=RIGHT_ON)), h)
        self.assertEqual(r.status_code, 201, r.text)
        v = r.json()
        self.assertTrue(v["id"])
        self.assertEqual(v["status"], "needs_answers")
        self.assertEqual(v["event"], {"t_event": T, "t_event_source": "hard_brake",
                                      "range": {"from": T - 12000, "to": T + 2000}})
        self.assertEqual([(a["field"], a["value"], a["rule"]) for a in v["auto_answers"]],
                         [("parties.ego.slowed_before_entry", True, "slowed_v0")])
        mv = next(q for q in v["questions"] if q["field"] == "parties.ego.movement")
        self.assertEqual(mv["vehicle_hint"]["value"], "right_turn")
        self.assertEqual(v["vehicle_timeline"]["turn_signal"][0]["dir"], "RIGHT")
        self.assertTrue(v["result"]["provisional"])
        self.assertIn(v["result"]["status"], ("ok", "no_rule"))
        self.assertTrue(v["judge_version"])
        g = self.c.get(f"/api/vehicle-cases/{v['id']}", headers=h)
        self.assertEqual(g.status_code, 200)
        self.assertEqual(g.json(), v)
        # 저장한 행에는 요청 원본(samples 포함)과 규칙 결과·버전이 남음 (8.6)
        row = store.get(v["id"])
        self.assertEqual(len(row["request"]["samples"]), v["data_quality"]["samples"])
        self.assertIn("slowed_v0", row["rules"])
        self.assertTrue(any("params" in x for x in row["rule_results"]))

    def test_get_not_found_and_others_case(self):
        h = self.login("kim")
        v = self.post(body(), h).json()
        other = self.login("lee")
        for hh, cid in ((other, v["id"]), (h, "nope")):
            r = self.c.get(f"/api/vehicle-cases/{cid}", headers=hh)
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json()["error"], "vehicle_case_not_found")

    def test_auth(self):
        self.assertEqual(self.post(body(), {}).json()["error"], "login_required")
        self.assertEqual(self.c.get("/api/vehicle-cases/x").status_code, 401)
        r = self.post(body(), self.login("park", signup=False))
        self.assertEqual((r.status_code, r.json()["error"]), (403, "signup_required"))

    def test_errors(self):
        h = self.login("kim")
        rows = build()
        cases = [
            ([1, 2], "request_invalid"),
            (body(t_event_source="crash"), "request_invalid"),
            (body(samples={}), "request_invalid"),
            (body(vehicle={"cls": "tank"}), "request_invalid"),
            (body(range={"from": T, "to": T - 1}), "range_invalid"),
            (body(range={"from": T - 130000, "to": T}), "range_invalid"),
            (body(t_event=T - 11000), "t_event_out_of_range"),
            (body(samples=[]), "samples_empty"),
            (body(samples=[rows[0]] * 20001), "samples_too_many"),
            (body(samples=[rows[1], rows[0]]), "samples_unsorted"),
            (body(samples=[dict(rows[0], gear="X")]), "sample_invalid"),
            (body(samples=[dict(rows[0], brake="true")]), "sample_invalid"),
            (body(samples=[dict(rows[0], t=T + 5000)]), "sample_invalid"),
            (body(location={"lat": 37.5}), "location_unsupported"),
        ]
        for b, code in cases:
            r = self.post(b, h)
            self.assertEqual((r.status_code, r.json()["error"]), (422, code), (code, r.text[:200]))
            self.assertTrue(r.json()["message"])
        r = self.c.post("/api/vehicle-cases", content=b"{not json", headers={**h, "Content-Type": "application/json"})
        self.assertEqual((r.status_code, r.json()["error"]), (422, "request_invalid"))
        r = self.post(body(samples=[rows[0], dict(rows[1], speedKmh=-3)]), h)
        self.assertIn("samples[1]", r.json()["message"])
        with store.connect() as con:   # 잘못된 요청은 저장하지 않음
            self.assertEqual(con.execute("SELECT COUNT(*) FROM vehicle_cases").fetchone()[0], 0)


class Answers(ApiBase):
    """2부: PUT /api/vehicle-cases/{id}/answers (2.2)"""

    def put(self, cid, answers, h):
        return self.c.put(f"/api/vehicle-cases/{cid}/answers", json={"answers": answers}, headers=h)

    def test_put_recomputes(self):
        """답하면 다시 계산: 진행 방향 답으로 지시등 자동 답변이 생기고, GET은 PUT 결과와 같음"""
        h = self.login("kim")
        v = self.post(body(build(speed=SLOW_DOWN, turn=RIGHT_ON)), h).json()
        user = {"parties.ego.movement": "right_turn", **CROSS}
        r = self.put(v["id"], user, h)
        self.assertEqual(r.status_code, 200, r.text)
        p = r.json()
        self.assertEqual((p["id"], p["created_at"]), (v["id"], v["created_at"]))
        self.assertGreaterEqual(p["updated_at"], v["updated_at"])
        auto = {a["field"]: a["value"] for a in p["auto_answers"]}
        self.assertEqual(auto["parties.ego.turn_signal_used"], True)
        self.assertEqual(p["answers"]["parties.ego.movement"], {"value": "right_turn", "source": "user"})
        self.assertEqual((p["result"]["rule_id"], p["result"]["fault_by_party"]), ("차13-1", {"ego": 60, "other": 40}))
        self.assertEqual(self.c.get(f"/api/vehicle-cases/{v['id']}", headers=h).json(), p)
        row = store.get(v["id"])
        self.assertEqual(row["answers"], user)
        self.assertEqual(row["status"], p["status"])
        self.assertIn("turn_signal_v0", row["rules"])
        # 답을 다시 보내면 (빈 답) 처음 상태로 돌아감: 지난 답은 남지 않음
        q = self.put(v["id"], {}, h).json()
        self.assertEqual(q["auto_answers"], v["auto_answers"])
        self.assertEqual(store.get(v["id"])["answers"], {})

    def test_conflict(self):
        """차량 기록(서행 true)과 다르게 답하면 사용자 답 우선 + answer_conflicts (D9)"""
        h = self.login("kim")
        v = self.post(body(build(speed=SLOW_DOWN)), h).json()
        p = self.put(v["id"], {"parties.ego.movement": "straight", "intersection_entry_order": "same_time",
                               "parties.ego.slowed_before_entry": False, **CROSS}, h).json()
        self.assertEqual([(c["field"], c["vehicle_value"], c["user_value"]) for c in p["answer_conflicts"]],
                         [("parties.ego.slowed_before_entry", True, False)])
        self.assertTrue(p["answer_conflicts"][0]["evidence"]["text"])
        self.assertEqual(p["answers"]["parties.ego.slowed_before_entry"], {"value": False, "source": "user"})
        self.assertEqual(p["result"]["fault_by_party"], {"ego": 40, "other": 60})

    def test_stale_answer_accepted(self):
        """앞 답을 바꿔 사라진 질문의 답(진입 순서를 same_time으로 바꾼 뒤의 intersection_entry_clear)은 받음"""
        h = self.login("kim")
        v = self.post(body(), h).json()
        r = self.put(v["id"], {"parties.ego.movement": "straight", "intersection_entry_order": "same_time",
                               "intersection_entry_clear": True, **CROSS}, h)
        self.assertEqual(r.status_code, 200, r.text)

    def test_put_errors(self):
        h = self.login("kim")
        v = self.post(body(), h).json()
        url = f"/api/vehicle-cases/{v['id']}/answers"
        for b in ([1], {"answers": [1]}, {}, {"answers": None}):
            r = self.c.put(url, json=b, headers=h)
            self.assertEqual((r.status_code, r.json()["error"]), (422, "answers_shape"), b)
        r = self.c.put(url, content=b"{x", headers={**h, "Content-Type": "application/json"})
        self.assertEqual((r.status_code, r.json()["error"]), (422, "request_invalid"))
        for answers, word in (({"parties.other.entry_from": "north"}, "parties.other.entry_from"),
                              ({"road.signal_present": "yes"}, "road.signal_present"),
                              ({"foo": 1}, "foo"), ({"parties.third.movement": "straight"}, "parties.third")):
            r = self.put(v["id"], answers, h)
            self.assertEqual((r.status_code, r.json()["error"]), (422, "answer_invalid"), answers)
            self.assertIn(word, r.json()["message"])
        self.assertEqual(store.get(v["id"])["view"], v)   # 잘못된 답은 저장하지 않음
        for hh, cid in ((self.login("lee"), v["id"]), (h, "nope")):
            r = self.put(cid, {}, hh)
            self.assertEqual((r.status_code, r.json()["error"]), (404, "vehicle_case_not_found"))
        self.assertEqual(self.c.put(url, json={"answers": {}}).status_code, 401)


class Delete(ApiBase):
    """2부: DELETE /api/vehicle-cases/{id} (2.4)"""

    def test_delete(self):
        h = self.login("kim")
        v = self.post(body(), h).json()
        keep = self.post(body(), h).json()
        r = self.c.delete(f"/api/vehicle-cases/{v['id']}", headers=h)
        self.assertEqual((r.status_code, r.content), (204, b""))
        self.assertIsNone(store.get(v["id"]))   # samples가 든 행이 없어짐
        with store.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM vehicle_cases WHERE id = ?", (v["id"],)).fetchone()[0], 0)
        self.assertEqual(self.c.get(f"/api/vehicle-cases/{v['id']}", headers=h).status_code, 404)
        self.assertEqual(self.c.delete(f"/api/vehicle-cases/{v['id']}", headers=h).status_code, 404)   # 두 번째
        self.assertIsNotNone(store.get(keep["id"]))   # 다른 사건은 그대로

    def test_delete_others_case(self):
        h = self.login("kim")
        v = self.post(body(), h).json()
        r = self.c.delete(f"/api/vehicle-cases/{v['id']}", headers=self.login("lee"))
        self.assertEqual((r.status_code, r.json()["error"]), (404, "vehicle_case_not_found"))
        self.assertIsNotNone(store.get(v["id"]))
        self.assertEqual(self.c.delete(f"/api/vehicle-cases/{v['id']}").status_code, 401)


class Withdraw(ApiBase):
    """2부: 탈퇴(DELETE /api/me) 때 차량 사건도 삭제 (8.5, install(app)의 미들웨어)"""

    def test_withdraw_deletes_vehicle_cases(self):
        h, other = self.login("kim"), self.login("lee")
        mine = [self.post(body(), h).json()["id"] for _ in range(2)]
        keep = self.post(body(), other).json()["id"]
        r = self.c.delete("/api/me", headers=h)
        self.assertEqual(r.status_code, 204, r.text)
        for cid in mine:
            self.assertIsNone(store.get(cid))
        self.assertIsNotNone(store.get(keep))   # 남의 사건은 그대로

    def test_failed_withdraw_keeps_cases(self):
        h = self.login("kim")
        cid = self.post(body(), h).json()["id"]
        for hh in ({}, {"Authorization": "Bearer nope"}):
            self.assertEqual(self.c.delete("/api/me", headers=hh).status_code, 401)
        self.assertIsNotNone(store.get(cid))

    def test_withdraw_before_signup(self):
        """가입(닉네임·약관) 전 회원도 탈퇴할 수 있음 (me_any). 차량 사건이 없어도 그대로 204"""
        r = self.c.delete("/api/me", headers=self.login("park", signup=False))
        self.assertEqual(r.status_code, 204)


if __name__ == "__main__":
    unittest.main()
