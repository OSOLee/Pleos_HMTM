"""블랙박스 정보 합치기·판정 시험 (docs/design-blackbox.md 4절, 3.3 합치기)

  python -m pytest tests/test_bb_merge.py

user > vehicle > video > default, 출처 표시(video), source_conflicts, 시각 맞추기 coarse/none에서 차량 값 빼기,
시나리오 expect(차량 기록 없이 답만 넣은 판정)와 같은지.
영상 파일은 쓰지 않는다 (가짜 분석기가 못 읽으면 시나리오 값 그대로: 영상 30초, 충돌 18.2초).
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from src.blackbox import adapter, analyzer, fake, merge, sync

S0 = 1_762_666_212_000                  # 영상 시작 (파일 이름 시각)
T = S0 + 18_200                         # 영상 충돌 18.2초
START = [{"source": "filename", "start_ms": S0}]


def samples(start=-12000, end=2000, speed=40.0, gear="D", turn="OFF", brake=False, step=100):
    def val(x, r):
        return x(r) if callable(x) else x
    return [{"t": T + r, "speedKmh": val(speed, r), "gear": val(gear, r), "turnSignal": val(turn, r),
             "brake": val(brake, r)} for r in range(start, end + 1, step)]


def vreq(**kw):
    s = samples(**kw)
    return {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle_cls": "car", "client": {}}


def run(scenario, vehicle=None, user=None, grade=None, start=START):
    bb = analyzer.run("none.mp4", scenario=scenario, name="fake")
    s = sync.sync(start, bb["facts"]["collision"]["t"], vehicle["range"] if vehicle else None)
    if grade:
        s["grade"] = grade
    return adapter.build(bb, vehicle, s, user or {})


def fields(view):
    return [q["field"] for q in view["questions"]]


REVERSE = lambda r: "R" if r >= -2500 else "D"
RIGHT_ON = lambda r: "RIGHT" if r >= -6000 else "OFF"
LEFT_ON = lambda r: "LEFT" if -7000 <= r < -3000 else "OFF"



def vs(answer):
    """answers[키]에서 값·출처만 (2부에서 evidence가 더해짐)"""
    return {"value": answer["value"], "source": answer["source"]}

class Merge(unittest.TestCase):
    def test_priority(self):
        d, g, c = merge.merge({"a": 1}, {"a": {"value": 2, "evidence": "v"}, "b": {"value": 3, "evidence": "v"}},
                              {"a": {"value": 1, "evidence": "w"}, "b": {"value": 4, "evidence": "w"},
                               "c": {"value": 5, "evidence": "w"}})
        self.assertEqual({k: (x["value"], x["source"]) for k, x in d.items()},
                         {"a": (1, "user"), "b": (3, "vehicle"), "c": (5, "video")})
        self.assertEqual([(x["field"], x["kind"]) for x in c], [("a", "user_vs_vehicle"), ("b", "vehicle_vs_video")])
        a = c[0]
        self.assertEqual([o["source"] for o in a["others"]], ["vehicle"])   # 영상은 user와 같아 충돌 아님

    def test_guesses(self):
        d, g, c = merge.merge({}, {}, {}, {"x": {"guess": 1, "evidence": "차"}, "y": {"guess": 1, "evidence": "차"}},
                              {"x": {"guess": 1, "evidence": "영"}, "y": {"guess": 2, "evidence": "영"},
                               "z": {"guess": 3, "evidence": "영"}})
        self.assertEqual((g["x"]["model_guess"], g["x"]["guess_source"]), (1, "vehicle"))
        self.assertEqual((g["y"]["model_guess"], g["y"]["guess_source"]), (None, None))
        self.assertIn("차", g["y"]["guess_evidence"])
        self.assertIn("영", g["y"]["guess_evidence"])
        self.assertEqual((g["z"]["model_guess"], g["z"]["guess_source"]), (3, "video"))
        self.assertEqual([(x["field"], x["kind"]) for x in c], [("y", "guess_mismatch")])

    def test_definite_beats_guess(self):
        d, g, _ = merge.merge({}, {}, {"m": {"value": "right_turn", "evidence": "영"}},
                              {"m": {"guess": "left_turn", "evidence": "차"}})
        self.assertEqual(d["m"]["source"], "video")
        self.assertNotIn("m", g)

    def test_video_values(self):
        bb = analyzer.run("none.mp4", scenario="right_turn_left_straight", name="fake")
        d, g, extra = merge.video_values(bb["facts"])
        self.assertEqual(d["parties.other.entry_from"]["value"], "left")     # west → 내 차 기준 왼쪽
        self.assertEqual(d["scene.place"]["value"], "intersection")
        self.assertEqual(g["road.signal_present"]["guess"], False)
        self.assertIn("17.5초", d["parties.ego.movement"]["evidence"])

    def test_source_of(self):
        self.assertEqual(merge.source_of({"video", "vehicle"}), "vehicle")
        self.assertEqual(merge.source_of({"video", None}), "video")
        self.assertEqual(merge.source_of({None}), "default")


class Expect(unittest.TestCase):
    def test_scenarios_match_expect(self):
        """시나리오 expect: 차량 기록 없이 expect.answers만 넣은 판정"""
        for name in fake.scenario_names():
            exp = fake.load_scenario(name)["fake"]["expect"]
            if "rule_id" not in exp:
                continue
            view = run(name, user=exp["answers"])["view"]
            got = {"status": view["status"], "judge_status": view["result"]["status"],
                   "rule_id": view["result"]["rule_id"], "fault_by_party": view["result"]["fault_by_party"]}
            self.assertEqual(got, {k: exp[k] for k in got}, name)


class WithoutVehicle(unittest.TestCase):
    def test_video_values_used_with_source_video(self):
        view = run("right_turn_left_straight")["view"]
        a = view["answers"]
        self.assertEqual(vs(a["parties.ego.movement"]), {"value": "right_turn", "source": "video"})
        self.assertEqual(vs(a["parties.other.entry_from"]), {"value": "left", "source": "video"})
        self.assertEqual(vs(a["parties.ego.cls"]), {"value": "car", "source": "default"})
        self.assertNotIn("parties.ego.movement", fields(view))           # 영상이 정한 질문은 안 물음
        self.assertNotIn("parties.other.entry_from", fields(view))
        q = {x["field"]: x for x in view["questions"]}["road.signal_present"]
        self.assertEqual((q["model_guess"], q["guess_source"]), (False, "video"))
        self.assertEqual(view["data_quality"]["sync_grade"], "none")
        self.assertEqual(view["data_quality"]["sync_reason"], "no_vehicle_record")
        self.assertEqual(view["auto_answers"], [])
        self.assertEqual(view["event"]["t_event_source"], "video")

    def test_user_beats_video(self):
        view = run("right_turn_left_straight", user={"parties.other.entry_from": "right"})["view"]
        self.assertEqual(vs(view["answers"]["parties.other.entry_from"]), {"value": "right", "source": "user"})
        c = [x for x in view["source_conflicts"] if x["field"] == "parties.other.entry_from"]
        self.assertEqual((c[0]["kind"], c[0]["others"][0]["value"]), ("user_vs_video", "left"))
        self.assertEqual(view["answer_conflicts"], [])

    def test_modifier_source_video(self):
        """영상 값으로 적용된 가감 요소의 출처는 video, "입증 필요" 없음 (확정 Q15). 사용자 답이면 user + 입증 필요"""
        bb = analyzer.run("none.mp4", scenario="straight_same_time", name="fake")
        bb["facts"]["parties"]["ego"]["slowed_before_entry"] = {"value": True, "source": "model"}
        view = adapter.build(bb, None, sync.sync(START, 18.2), {})["view"]
        m = [m for m in view["result"]["modifiers"] if m["facts"] == ["slowed_before_entry"]][0]
        self.assertEqual((m["party"], m["source"], m["needs_proof"]), ("ego", "video", False))
        view = run("straight_same_time", user={"parties.ego.slowed_before_entry": True})["view"]
        m = [m for m in view["result"]["modifiers"] if m["facts"] == ["slowed_before_entry"]][0]
        self.assertEqual((m["source"], m["needs_proof"]), ("user", True))

    def test_answer_check(self):
        from src.vehicle.samples import VehicleError
        with self.assertRaises(VehicleError) as e:
            run("right_turn_left_straight", user={"road.signal_present": "maybe"})
        self.assertEqual(e.exception.code, "answer_invalid")
        with self.assertRaises(VehicleError):
            run("right_turn_left_straight", user={"nope": 1})

    def test_rear_end_lead_order_pair(self):
        view = run("rear_end_lead")["view"]
        self.assertIn("parties.other.stop_state", fields(view))
        self.assertEqual(vs(view["answers"]["parties.other.lead_order"]), {"value": "leading", "source": "video"})


class WithVehicle(unittest.TestCase):
    """차량 기록을 넣은 판정(with_vehicle)의 합치기 규칙. 차량 기록 없는 base 판정은 test_bb_vehicle_evidence.py"""

    def test_vehicle_beats_video(self):
        """영상은 직진, 차량 기록은 후진 → 후진(vehicle), vehicle_vs_video 충돌 (시나리오 ego_reverse_video_wrong)"""
        rec = run("ego_reverse_video_wrong", vreq(gear=REVERSE, speed=3.0))
        view = rec["with_vehicle"]   # 차량 기록을 넣은 판정 (4.4: result_with_vehicle)
        self.assertEqual(vs(rec["view"]["answers"]["parties.ego.movement"]), {"value": "straight", "source": "video"})
        self.assertEqual(view["data_quality"]["sync_grade"], "coarse")
        self.assertEqual(vs(view["answers"]["parties.ego.movement"]), {"value": "reverse", "source": "vehicle"})
        c = [x for x in view["source_conflicts"] if x["field"] == "parties.ego.movement"][0]
        self.assertEqual(c["kind"], "vehicle_vs_video")
        self.assertEqual(c["others"][0], {"value": "straight", "source": "video", "evidence": "내 차가 직진했어요 (17초)"})
        self.assertIn("R(후진)", c["evidence"])
        self.assertEqual([a["field"] for a in view["auto_answers"]], ["parties.ego.movement"])
        sp = {x["field"]: x for x in view["questions"]}.get("situation.special")
        self.assertIn("reverse:ego", sp["model_guess"])
        self.assertEqual(view["event"]["t_event"], T)
        self.assertIn("reverse_v0", rec["rules"])
        self.assertEqual(vs(view["answers"]["parties.ego.cls"]), {"value": "car", "source": "vehicle"})

    def test_coarse_timing_rules_only_guess(self):
        """coarse: 지시등은 자동 답변하지 않고 추정값으로만 (5.3 표)"""
        view = run("right_turn_left_straight", vreq(turn=RIGHT_ON))["with_vehicle"]
        self.assertEqual(view["data_quality"]["sync_grade"], "coarse")
        q = {x["field"]: x for x in view["questions"]}["parties.ego.turn_signal_used"]
        self.assertEqual((q["model_guess"], q["guess_source"]), (True, "vehicle"))
        self.assertIn("대략", q["guess_evidence"])
        self.assertNotIn("parties.ego.turn_signal_used", view["answers"])
        self.assertEqual(view["auto_answers"], [])

    def test_fine_uses_timing_rules(self):
        """같은 기록이라도 등급이 fine이면(2부의 정밀 맞추기) 지시등 자동 답변. 회전은 영상 값으로 계산"""
        view = run("right_turn_left_straight", vreq(turn=RIGHT_ON), grade="fine")["with_vehicle"]
        self.assertEqual(vs(view["answers"]["parties.ego.turn_signal_used"]), {"value": True, "source": "vehicle"})
        self.assertNotIn("parties.ego.turn_signal_used", fields(view))
        self.assertIn("parties.ego.turn_signal_used", [a["field"] for a in view["auto_answers"]])

    def test_vehicle_modifier_no_proof(self):
        """fine에서 차량 기록 서행 → 가감 요소 출처 vehicle, 입증 필요 없음"""
        view = run("straight_same_time", vreq(speed=lambda r: 40.0 if r < -3000 else 10.0), grade="fine")["with_vehicle"]
        m = [m for m in view["result"]["modifiers"] if m["facts"] == ["slowed_before_entry"]][0]
        self.assertEqual((m["source"], m["needs_proof"]), ("vehicle", False))
        # 같은 기록이 coarse면 서행은 추정값으로만: 질문이 남고, 답이 없는 동안 추정값으로 채운 임시 판정(출처 default)
        view = run("straight_same_time", vreq(speed=lambda r: 40.0 if r < -3000 else 10.0))["with_vehicle"]
        m = [m for m in view["result"]["modifiers"] if m["facts"] == ["slowed_before_entry"]][0]
        self.assertEqual((m["source"], m["needs_proof"]), ("default", False))
        self.assertTrue(view["result"]["provisional"])
        q = {x["field"]: x for x in view["questions"]}["parties.ego.slowed_before_entry"]
        self.assertEqual((q["model_guess"], q["guess_source"]), (True, "vehicle"))

    def test_none_ignores_vehicle(self):
        """시작 시각을 모르면(none) 차량 기록이 있어도 규칙을 돌리지 않음"""
        rec = run("ego_reverse_video_wrong", vreq(gear=REVERSE, speed=3.0), start=[])
        self.assertEqual(rec["rule_results"], [])
        view = rec["view"]
        self.assertEqual((view["data_quality"]["sync_grade"], view["data_quality"]["sync_reason"]),
                         ("none", "no_start_time"))
        self.assertEqual(vs(view["answers"]["parties.ego.movement"]), {"value": "straight", "source": "video"})
        self.assertTrue(view["data_quality"]["vehicle_record"])

    def test_not_covering_is_none(self):
        rec = run("ego_reverse_video_wrong", vreq(start=-1000, gear=REVERSE))
        self.assertEqual(rec["view"]["data_quality"]["sync_reason"], "vehicle_record_not_covering")
        self.assertEqual(rec["rule_results"], [])

    def test_user_beats_vehicle(self):
        view = run("ego_reverse_video_wrong", vreq(gear=REVERSE, speed=3.0),
                   user={"parties.ego.movement": "straight"})["view"]
        self.assertEqual(vs(view["answers"]["parties.ego.movement"]), {"value": "straight", "source": "user"})
        self.assertEqual(view["answer_conflicts"][0]["vehicle_value"], "reverse")
        c = [x for x in view["source_conflicts"] if x["field"] == "parties.ego.movement"][0]
        self.assertEqual(c["kind"], "user_vs_vehicle")

    def test_guess_mismatch(self):
        """영상은 직진 추정, 차량은 좌회전 추정(LEFT 지시등) → 미리 고르지 않음"""
        view = run("mostly_unknown", vreq(turn=LEFT_ON))["with_vehicle"]
        q = {x["field"]: x for x in view["questions"]}["parties.ego.movement"]
        self.assertIsNone(q["model_guess"])
        self.assertIn("왼쪽 지시등", q["guess_evidence"])
        self.assertIn("영상", q["guess_evidence"])
        self.assertEqual([c["kind"] for c in view["source_conflicts"]], ["guess_mismatch"])

    def test_stationary_fact_from_vehicle_in_coarse(self):
        """서 있었음(movement_v0 4번)은 시각에 덜 민감해 coarse에서도 씀"""
        view = run("rear_end_lead", vreq(speed=0.0, gear="D"))["with_vehicle"]
        self.assertEqual(vs(view["answers"]["parties.ego.stationary_at_collision"]), {"value": True, "source": "vehicle"})
        self.assertFalse(view["data_quality"]["sync_suspect"])


if __name__ == "__main__":
    unittest.main()
