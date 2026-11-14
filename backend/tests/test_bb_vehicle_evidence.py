"""차량 기록은 참고 자료 시험 (docs/design-blackbox.md 4.4, 2026-11-10 설계 변경)

  python -m pytest tests/test_bb_vehicle_evidence.py

- 두 번 판정: result(영상·사용자 답·기본값) / result_with_vehicle(+ 차량 기록, 기록이 없으면 null)
- 차량 기록이 답하던 질문도 remaining에 남고 vehicle_hint가 붙음
- vehicle_effects: 차이를 만든 기록 (결과가 같으면 []). coarse/none이면 타이밍 값은 쓰지 않고 applied: false + 이유
- vehicle_timeline: 충돌 전후 속도·지시등·브레이크·기어 요약
- 근거 문장에 필드 이름·영어 값이 나오지 않음 (보행자·자전거 포함)
- 서버 빈틈: 답한 질문 정의(answered), 목록 행의 vehicle_record·fault_display, 내 사건 전체 삭제

시나리오 left_turn_motion: 내 차 좌회전 대 왼쪽 길 직진(차16-1, 기본 60:40). 지시등은 이 도표의 가감 요소
(B 진로변경 시 신호 불이행 +10). 차13-1(우회전 대 왼쪽 직진)에는 지시등 가감 요소가 없다.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
import test_bb_fine as F
from src.blackbox import adapter, analyzer, chapter, evidence, fake
from src.vehicle import adapter as va
from test_bb_api import ApiBase, S0 as API_S0
from test_bb_merge import run as merge_run, vreq as merge_vreq

SCN = "left_turn_motion"
LEFT_6S = 6_000


def samples(bb, turn=None, **kw):
    """영상 움직임을 따라 달린 차량 기록 (test_bb_fine.samples). turn: 충돌 몇 ms 전부터 LEFT"""
    out = F.samples(bb, turn=turn, **kw)
    for s in out:
        if s["turnSignal"] == "RIGHT":
            s["turnSignal"] = "LEFT"
    return out


def build(turn=None, grade=None, user=None, scenario=SCN):
    bb = analyzer.run("none.mp4", scenario=scenario, name="fake")
    s = samples(bb, turn)
    sy = F.do_sync(bb, s)
    if grade:
        sy = dict(sy, grade=grade)
    return adapter.build(bb, F.vreq(s), sy, user or {}), sy


class TwoJudgments(unittest.TestCase):
    def test_scenario_and_variant(self):
        on, off = fake.load_scenario(SCN), fake.load_scenario("left_turn_motion_nosignal")
        self.assertEqual(off["facts"], on["facts"])            # extends: 분석 결과는 같고
        self.assertEqual(off["ego_motion"], on["ego_motion"])
        self.assertEqual((on["fake"]["vehicle_demo"]["turn_signal"], off["fake"]["vehicle_demo"]["turn_signal"]),
                         ("LEFT", None))                      # 데모 차량 기록만 다름
        self.assertEqual(off["fake"]["expect"], on["fake"]["expect"])

    def test_signal_on_no_effect(self):
        """6초 전 LEFT 켬 (fine): 지시등을 켠 것은 가감 요소가 아님 → 결과 같음, effects []"""
        rec, sy = build(LEFT_6S)
        v = rec["view"]
        self.assertEqual(sy["grade"], "fine")
        self.assertEqual((v["result"]["rule_id"], v["result"]["fault_by_party"]), ("차16-1", {"ego": 60, "other": 40}))
        self.assertEqual(v["result_with_vehicle"]["fault_by_party"], {"ego": 60, "other": 40})
        self.assertEqual(v["vehicle_effects"], [])
        q = {x["field"]: x for x in v["remaining"]}["parties.ego.turn_signal_used"]   # 기본 판정은 사용자에게 물음
        self.assertIsNone(q["model_guess"])
        h = q["vehicle_hint"]
        self.assertEqual((h["value"], h["value_label"], h["determined"], h["applied"]), (True, "켬", True, True))
        self.assertEqual(h["text"], "사고 6초 전 왼쪽 지시등 켜짐 (사고 때까지 켜져 있음)")
        self.assertNotIn("parties.ego.turn_signal_used", v["answers"])

    def test_signal_off_changes(self):
        """지시등 안 켬 (fine): 입증하면 내 차 +10 → 70:30, 차이를 만든 기록 하나"""
        rec, _ = build(None)
        v = rec["view"]
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 60, "other": 40})
        self.assertEqual(v["result_with_vehicle"]["fault_by_party"], {"ego": 70, "other": 30})
        self.assertEqual(len(v["vehicle_effects"]), 1)
        e = v["vehicle_effects"][0]
        self.assertEqual((e["field"], e["label"], e["value"], e["value_label"], e["applied"], e["ego_delta"],
                          e["direction"], e["rule"]),
                         ("parties.ego.turn_signal_used", "방향지시등", False, "안 켬", True, 10, "ego_more",
                          "turn_signal_v0"))
        self.assertEqual(e["summary"], "내 차가 방향지시등을 켜지 않았어요")
        self.assertIn("왼쪽 지시등을 켜지 않았어요", e["text"])
        m = [m for m in v["result_with_vehicle"]["modifiers"] if m["facts"] == ["turn_signal_used"]][0]
        self.assertEqual((m["source"], m["needs_proof"]), ("vehicle", False))

    def test_slowed_lowers_my_fault(self):
        """직진 대 직진(차12-1(가)): 진입 전 서행한 기록 (fine) → 입증하면 내 과실 −10 (60 : 40 → 50 : 50)"""
        bb = analyzer.run("none.mp4", scenario="straight_motion_slowed", name="fake")
        s = F.samples(bb)
        sy = F.do_sync(bb, s)
        self.assertEqual(sy["grade"], "fine", sy.get("fine"))
        v = adapter.build(bb, F.vreq(s), sy, {})["view"]
        self.assertEqual((v["result"]["rule_id"], v["result"]["fault_by_party"]), ("차12-1(가)", {"ego": 60, "other": 40}))
        self.assertEqual(v["result_with_vehicle"]["fault_by_party"], {"ego": 50, "other": 50})
        e = v["vehicle_effects"]
        self.assertEqual([(x["field"], x["value"], x["ego_delta"], x["direction"], x["applied"]) for x in e],
                         [("parties.ego.slowed_before_entry", True, -10, "ego_less", True)])
        self.check_no_ident(e[0]["summary"])
        q = {x["field"]: x for x in v["remaining"]}["parties.ego.slowed_before_entry"]
        self.assertEqual((q["vehicle_hint"]["value"], q["vehicle_hint"]["determined"]), (True, True))

    def check_no_ident(self, text):
        self.assertIsNone(IDENT.search(text), text)

    def test_user_answer_beats_record(self):
        """사용자가 '켰음'으로 답하면 두 판정 모두 사용자 답 → 차이 없음 (user_vs_vehicle은 남음)"""
        rec, _ = build(None, user={"parties.ego.turn_signal_used": True})
        v = rec["view"]
        self.assertEqual(v["result"]["fault_by_party"], v["result_with_vehicle"]["fault_by_party"])
        self.assertEqual(v["vehicle_effects"], [])
        self.assertEqual([c["kind"] for c in v["source_conflicts"]], ["user_vs_vehicle"])
        self.assertEqual([a["field"] for a in v["answered"]], ["parties.ego.turn_signal_used"])
        a = v["answered"][0]
        self.assertEqual((a["value"], a["value_choice"], a["vehicle_hint"]["value"]), (True, a["choices"][0], False))

    def test_coarse_not_applied(self):
        """coarse: 지시등은 with_vehicle에도 안 씀. 정확히 맞췄다면 결과가 바뀌므로 applied false + 그때 비율"""
        rec, _ = build(None, grade="coarse")
        v = rec["view"]
        self.assertEqual(v["result_with_vehicle"]["fault_by_party"], {"ego": 60, "other": 40})
        e = v["vehicle_effects"]
        self.assertEqual([(x["field"], x["applied"], x["reason"]) for x in e],
                         [("parties.ego.turn_signal_used", False, "sync_coarse")])
        self.assertEqual(e[0]["fault_by_party_if_applied"], {"ego": 70, "other": 30})
        self.assertIn("대략", e[0]["reason_text"])
        h = {x["field"]: x for x in v["remaining"]}["parties.ego.turn_signal_used"]["vehicle_hint"]
        self.assertEqual((h["applied"], h["reason"]), (False, "sync_coarse"))

    def test_none_start_unreliable(self):
        """수정 시각뿐(none): 차량 기록을 전혀 안 쓰지만, 시각이 맞았다면 바뀌는 기록은 sync_none으로 알림"""
        bb = analyzer.run("none.mp4", scenario=SCN, name="fake")
        s = samples(bb, None)
        sy = F.do_sync(bb, s, start=[{"source": "mtime", "start_ms": F.S0}])
        self.assertEqual(sy["grade"], "fine")      # 수정 시각이어도 속도 모양이 맞으면 fine
        sy = dict(sy, grade="none", reason="start_time_unreliable")
        v = adapter.build(bb, F.vreq(s), sy, {})["view"]
        self.assertEqual(v["result_with_vehicle"]["fault_by_party"], v["result"]["fault_by_party"])
        self.assertEqual([(x["applied"], x["reason"]) for x in v["vehicle_effects"]], [(False, "sync_none")])

    def test_no_vehicle_record(self):
        rec = merge_run("right_turn_left_straight")
        v = rec["view"]
        self.assertIsNone(v["result_with_vehicle"])
        self.assertEqual(v["vehicle_effects"], [])
        self.assertIsNone(v["vehicle_timeline"])
        self.assertTrue(all(q["vehicle_hint"] is None for q in v["remaining"]))
        self.assertIsNone(rec["with_vehicle"])

    def test_no_start_time_no_timeline(self):
        rec = merge_run("ego_reverse_video_wrong", merge_vreq(), start=[])
        v = rec["view"]
        self.assertIsNotNone(v["result_with_vehicle"])
        self.assertEqual(v["vehicle_effects"], [])
        self.assertIsNone(v["vehicle_timeline"])   # 충돌 시각(차량 시계)을 모름


class Timeline(unittest.TestCase):
    def test_shape(self):
        rec, sy = build(LEFT_6S)
        tl = rec["view"]["vehicle_timeline"]
        self.assertEqual((tl["from_s"], tl["to_s"], tl["collision_s"], tl["step_s"]), (-15.0, 5.0, 0.0, 0.2))
        self.assertEqual((tl["sync_grade"], tl["aligned"], tl["t0_ms"]), ("fine", True, sy["t_collision_ms"]))
        self.assertEqual(len(tl["speed"]), 101)
        self.assertEqual(tl["speed"][0][0], -15.0)
        self.assertTrue(all(v is None or v >= 0 for _, v in tl["speed"]))
        self.assertGreater(tl["speed_max"], 30)
        self.assertEqual(tl["turn_signal"], [{"dir": "LEFT", "from": -6.0, "to": 5.0}])
        self.assertEqual(tl["brake"], [{"from": 0.0, "to": 5.0}])
        self.assertEqual(tl["gear"], [{"value": "D", "from": -15.0, "to": 5.0}])
        self.assertEqual(tl["gaps"], [])
        self.assertAlmostEqual(tl["video_collision_t"], 18.2)

    def test_coarse_not_aligned(self):
        rec, _ = build(LEFT_6S, grade="coarse")
        self.assertFalse(rec["view"]["vehicle_timeline"]["aligned"])


IDENT = re.compile(r"parties\.|road\.|scene\.|\b[a-z]{3,}(?:_[a-z]+)*\b")


class NoFieldNames(unittest.TestCase):
    """근거 문장·참고 표시에 필드 이름이나 영어 값이 그대로 나오지 않음"""

    def check(self, text, where):
        self.assertIsInstance(text, str, where)
        self.assertIsNone(IDENT.search(text.replace("km/h", "")), f"{where}: {text}")

    def test_all_scenarios(self):
        for name in fake.scenario_names():
            scn = fake.load_scenario(name)
            if scn.get("status") != "ok" or name == "analyzer_broken":
                continue
            for user in ({}, scn["fake"]["expect"].get("answers") or {}):
                with self.subTest(scenario=name, user=user):
                    v = merge_run(name, user=user)["view"]
                    for f, a in v["answers"].items():
                        self.check(a["evidence"], f"{name} {f}")
                    for q in v["remaining"]:
                        if q.get("guess_evidence"):
                            self.check(q["guess_evidence"], f"{name} {q['field']} guess")

    def test_every_chapter_question_value(self):
        """보행자·자전거 장 질문의 모든 보기로 사용자·영상·기본값 문장"""
        for q in chapter.ped_questions() + chapter.bike_questions():
            for o in q["options"]:
                for s in (evidence.for_user(q["field"], o, q), evidence.for_video(q["field"], o, 3.0),
                          evidence.for_default(q["field"], o, "video", q)):
                    self.check(s, f"{q['field']}={o}")

    def test_analyzer_values(self):
        """분석기가 낼 수 있는 보행자·자전거·도로 값 (질문이 없는 항목 포함)"""
        from src.blackbox import analyzer as an
        for pid in ("ego", "other"):
            for k, vals in an.PARTY_VALUES.items():
                if k in ("cls", "entry_from"):
                    continue
                for v in vals:
                    self.check(evidence.for_video(f"parties.{pid}.{k}", v, None), f"{pid}.{k}={v}")
        for k, vals in an.ROAD_VALUES.items():
            field = {"location": "scene.place", "junction_type": "scene.junction_type"}.get(k, f"road.{k}")
            for v in vals:
                self.check(evidence.for_video(field, v, None), f"{k}={v}")
        for v in (5, 12.5):
            self.check(evidence.for_video("parties.other.dist_from_crosswalk_m", v, None), "dist")
        self.check(evidence.for_video("parties.other.ped_factors", ["group", "sudden_entry"], None), "ped_factors")

    def test_pedestrian_sentences(self):
        self.assertEqual(evidence.for_video("parties.other.ped_place", "crosswalk", 4.0),
                         "상대는 횡단보도 위에 있었어요 (4초)")
        self.assertEqual(evidence.for_video("road.crosswalk_signal", False, None),
                         "횡단보도에 보행자 신호등이 없었어요")
        self.assertEqual(evidence.sentence("parties.other.crosswalk_distance", "within_10m"),
                         "횡단보도에서 10m 안쪽에서 부딪혔어요")
        self.assertEqual(evidence.sentence("parties.other.ped_signal_at_start", "flashing_green"),
                         "건너기 시작할 때 보행자 신호는 초록 점멸이었어요")
        self.assertEqual(evidence.sentence("parties.other.on_bike_crossing", True), "상대가 자전거횡단도로 건너고 있었어요")

    def test_effects_and_hints(self):
        rec, _ = build(None)
        v = rec["view"]
        for e in v["vehicle_effects"]:
            for k in ("label", "value_label", "summary"):
                self.check(e[k], k)
        for q in v["remaining"]:
            if q["vehicle_hint"]:
                self.check(q["vehicle_hint"]["value_label"], q["field"])

    def test_value_label(self):
        self.assertEqual(evidence.value_label("parties.ego.turn_signal_used", False), "안 켬")
        self.assertEqual(evidence.value_label("parties.ego.movement", "reverse"), "후진")
        self.assertEqual(evidence.value_label("parties.ego.slowed_before_entry", True), "속도를 줄임")
        self.assertEqual(evidence.value_label("parties.other.cls", "person"), "보행자")
        self.assertEqual(evidence.value_label("road.night", True), "예")
        self.assertEqual(evidence.value_label("parties.other.something_new", "abc"), "기타")
        self.assertEqual(va.OTHER_CLASSES[-1], "pedestrian")


class Api(ApiBase):
    def veh(self, turn=None):
        bb = analyzer.run(self.video, scenario=SCN, name="fake")
        s = samples(bb, turn, s0=API_S0)
        return {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle": {"cls": "car"}}

    def test_upload_effects_and_list(self):
        h = self.login("kim")
        off = self.run_case(h, scenario=SCN, veh=self.veh(None))
        self.assertEqual(off["sync"]["grade"], "fine", off["sync"]["fine"])
        self.assertEqual(off["result_with_vehicle"]["fault_by_party"], {"ego": 70, "other": 30})
        self.assertEqual([e["field"] for e in off["vehicle_effects"]], ["parties.ego.turn_signal_used"])
        self.assertEqual(off["vehicle_timeline"]["sync_grade"], "fine")
        on = self.run_case(h, scenario=SCN, veh=self.veh(LEFT_6S))
        self.assertEqual(on["vehicle_effects"], [])
        plain = self.run_case(h, scenario=SCN)
        rows = {r["id"]: r for r in self.c.get("/api/bb-cases", headers=h).json()}
        self.assertEqual((rows[off["id"]]["vehicle_record"], rows[off["id"]]["sync_grade"],
                          rows[off["id"]]["vehicle_changes"]), (True, "fine", True))
        self.assertEqual(rows[off["id"]]["fault_display"]["text"], "내 차 60 : 상대 40")
        self.assertEqual(rows[off["id"]]["fault_display_with_vehicle"]["text"], "내 차 70 : 상대 30")
        self.assertEqual((rows[on["id"]]["vehicle_record"], rows[on["id"]]["vehicle_changes"]), (True, False))
        self.assertEqual((rows[plain["id"]]["vehicle_record"], rows[plain["id"]]["fault_display_with_vehicle"]),
                         (False, None))
        # PUT answers: 답한 질문 정의가 응답에 남음 (답변 고치기)
        r = self.c.put(f"/api/bb-cases/{off['id']}/answers", json={"answers": {"road.signal_present": False}},
                       headers=h).json()
        self.assertEqual([(a["field"], a["value"], a["value_choice"]) for a in r["answered"]],
                         [("road.signal_present", False, "없음")])
        self.assertEqual(r["answered"][0]["question"], "이 교차로에 신호등이 있었나요?")
        self.assertNotIn("road.signal_present", [q["field"] for q in r["remaining"]])

    def test_delete_all_mine(self):
        kim, lee = self.login("kim"), self.login("lee")
        for _ in range(2):
            self.run_case(kim, scenario="right_turn_left_straight")
        other = self.run_case(lee, scenario="right_turn_left_straight")
        r = self.c.delete("/api/bb-cases", headers=kim)
        self.assertEqual((r.status_code, r.json()), (200, {"deleted": 2}))
        self.assertEqual(self.c.get("/api/bb-cases", headers=kim).json(), [])
        self.assertEqual(self.c.get(f"/api/bb-cases/{other['id']}", headers=lee).status_code, 200)
        self.assertEqual(self.c.delete("/api/bb-cases", headers=kim).json(), {"deleted": 0})
        self.assertEqual(self.c.delete("/api/bb-cases").status_code, 401)


if __name__ == "__main__":
    unittest.main()
