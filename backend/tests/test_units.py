"""빠른 단위 시험 (영상·YOLO 없이 몇 초)

  python -m unittest discover tests            # 전체
  python -m unittest tests.test_units -v       # 이 파일만

지금까지 고친 버그가 다시 생기지 않는지 본다. 각 시험의 설명에 어떤 영상에서 생긴 문제였는지 적어 둠.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.analyze import detect_collision, stabilize, zone_events
from src.analyze.build_facts import entry_order, pair_motion, zone_movement
from src.app import answers, chapters, signals, situation, tap_track
from tools.evaluate.gt_answer import path_facts

FPS = 15


def recs(points, h=0.1, start=0):
    """[(x, y), ...] → 프레임순 궤적 기록. pos는 박스 아래 가운데"""
    return [{"frame": start + i, "pos": [x, y], "bbox": [x - h / 4, y - h, h / 2, h]} for i, (x, y) in enumerate(points)]


class ZoneMovement(unittest.TestCase):
    def test_turns(self):
        self.assertEqual(zone_movement("south", "north"), "straight")
        self.assertEqual(zone_movement("south", "east"), "right_turn")
        self.assertEqual(zone_movement("south", "west"), "left_turn")
        self.assertEqual(zone_movement("south", "south"), "u_turn")
        self.assertIsNone(zone_movement("south", None))


class EntryOrder(unittest.TestCase):
    def entry(self, f):
        return {"frame": f, "frame_outer": f - 1, "frame_inner": f + 1}

    def test_same_time_under_one_second(self):
        r = entry_order({"1": self.entry(30), "2": self.entry(40)}, "1", "2", FPS)
        self.assertEqual(r["first"], "same_time")

    def test_clear_lead(self):
        r = entry_order({"1": self.entry(30), "2": self.entry(60)}, "1", "2", FPS)
        self.assertEqual(r["first"], "1")
        self.assertTrue(r["robust"])

    def test_missing_entry(self):
        self.assertIsNone(entry_order({"1": self.entry(30), "2": "unknown"}, "1", "2", FPS))


class AnswerCheck(unittest.TestCase):
    facts = {"unknowns": [
        {"field": "parties.1.movement", "answer_type": "choice", "options": ["straight", "left_turn"]},
        {"field": "collision.parties", "answer_type": "pair", "options": [["1", "2"], ["1", "3"]]},
    ]}

    def test_ok(self):
        answers.check(self.facts, {"parties.1.movement": "straight", "collision.parties": ["2", "1"]}, 100)

    def test_option_not_in_list(self):
        with self.assertRaises(ValueError):
            answers.check(self.facts, {"parties.1.movement": "fly"}, 100)

    def test_pair_not_in_list(self):
        with self.assertRaises(ValueError):
            answers.check(self.facts, {"collision.parties": ["2", "3"]}, 100)

    def test_frame_out_of_range(self):
        # 질문이 없어도 진입 프레임 답은 판정에 넘어가므로 범위를 봄
        with self.assertRaises(ValueError):
            answers.check(self.facts, {"parties.7.intersection_entry": 150}, 100)
        with self.assertRaises(ValueError):
            answers.check(self.facts, {"parties.7.intersection_entry": "abc"}, 100)


class PairMotion(unittest.TestCase):
    """같은 방향 관계 (lead_order, side_in_pair, stop_state)"""

    def tracks(self, a_pts, b_pts, h=0.1):
        return {"1": {"frames": recs(a_pts, h)}, "2": {"frames": recs(b_pts, h)}}

    def test_same_direction_lead(self):
        a = [(0.1 + 0.01 * i, 0.50) for i in range(40)]   # 둘 다 오른쪽으로, 2번이 앞
        b = [(0.3 + 0.01 * i, 0.52) for i in range(40)]
        out = pair_motion(self.tracks(a, b), "1", "2", 39, FPS)
        self.assertEqual((out["1"]["lead_order"], out["2"]["lead_order"]), ("following", "leading"))
        self.assertEqual(out["1"]["stop_state"], "driving")

    def test_crossing_has_no_lead(self):
        a = [(0.1 + 0.01 * i, 0.5) for i in range(40)]    # 오른쪽으로
        b = [(0.5, 0.1 + 0.01 * i) for i in range(40)]    # 아래로
        out = pair_motion(self.tracks(a, b), "1", "2", 39, FPS)
        self.assertFalse(out["1"]["same_direction"])
        self.assertIsNone(out["1"]["lead_order"])

    def test_rear_end_into_parked_car(self):
        a = [(0.1 + 0.01 * i, 0.5) for i in range(40)]    # 달려와서
        b = [(0.52, 0.5)] * 40                             # 처음부터 서 있던 차 (같은 줄 앞)
        out = pair_motion(self.tracks(a, b), "1", "2", 30, FPS)
        self.assertEqual((out["1"]["lead_order"], out["2"]["lead_order"]), ("following", "leading"))
        self.assertIsNone(out["2"]["stop_state"])          # 왜 서 있었는지는 질문
        self.assertTrue(out["2"]["stopped_before_collision"])
        self.assertTrue(out["2"]["stationary_at_collision"])     # B 수정요소 "정지"
        self.assertFalse(out["1"]["stationary_at_collision"])

    def test_creeping_truck_is_not_a_direction(self):
        # cc_200511: 거의 서 있는 트럭의 느린 밀림을 방향으로 써서 정면 충돌이 같은 방향으로 잡혔음
        a = [(0.6 - 0.0003 * i, 0.5) for i in range(40)]
        b = [(0.3 + 0.008 * i, 0.8 - 0.008 * i) for i in range(40)]
        out = pair_motion(self.tracks(a, b, 0.1), "1", "2", 39, FPS)
        self.assertNotEqual(out["1"]["same_direction"], True)


class Situation(unittest.TestCase):
    def facts(self, mv_a="straight", mv_b="straight", came=("north", "east"), cls=("car", "car"), **pa):
        p = lambda mv, c, k: {"movement": mv, "movement_guess": None, "entry_from": c, "cls": k}
        f = {"collision": {"a": "1", "b": "2", "frame": 50}, "road": {"location": "intersection"}, "fps": FPS,
             "parties": {"1": p(mv_a, came[0], cls[0]), "2": p(mv_b, came[1], cls[1])}}
        f["parties"]["1"].update(pa)
        return f

    def fields(self, f, user=None):
        return [q["field"] for q in situation.questions(f, user or {})]

    def test_crossing_asks_only_stop_sign(self):
        self.assertEqual(self.fields(self.facts()),
                         ["road.stop_sign_side", "parties.1.slowed_before_entry", "parties.1.lane_marking",
                          "parties.2.slowed_before_entry", "parties.2.lane_marking",
                          "intersection_entry_clear", "situation.special",
                          "parties.1.driver_factors", "parties.2.driver_factors"])   # 운전자 요인은 늘 (선택 질문)

    def test_special_options_follow_context(self):
        special = lambda f, user=None: next(u for u in situation.questions(f, user or {})
                                            if u["field"] == "situation.special")["options"]
        crossing = self.facts(same_direction=False)
        self.assertNotIn("cut_in:1", special(crossing))
        self.assertNotIn("center:1", special(crossing))
        same_road = self.facts(came=("north", "north"))
        self.assertIn("cut_in:1", special(same_road))
        self.assertNotIn("center:1", special(same_road))
        opposite = self.facts(opposite_direction=True, same_direction=False)
        self.assertIn("wrong_way:2", special(opposite))

    def test_follow_up_questions(self):
        f = self.facts(came=("north", "north"))
        user = {"situation.special": ["lane_change:1", "overtake:2"]}
        fields = self.fields(f, user)
        self.assertIn("parties.1.lane_change_dir", fields)     # 차로 변경을 골랐으니 방향
        self.assertIn("parties.2.overtake_type", fields)       # 앞지르기를 골랐으니 유형
        both_u = self.fields(self.facts("u_turn", "u_turn"))
        self.assertIn("pair.u_turn_timing", both_u)

    def test_special_false_only_for_shown(self):
        f = self.facts(same_direction=False)
        f["unknowns"] = situation.questions(f, {})
        asm = answers.to_assumptions(f, {"situation.special": ["off_road:2"]})
        self.assertTrue(asm["parties"]["2"]["from_off_road"])
        self.assertFalse(asm["parties"]["1"]["from_off_road"])
        self.assertNotIn("cut_in", asm["parties"]["1"])          # 교차 사고라 안 보여 준 보기는 넘기지 않음
        # 상황이 바뀌어 지금 안 보이는 보기라도 전에 고른 답은 틀린 답이 아님
        answers.check({"unknowns": f["unknowns"]}, {"situation.special": ["cut_in:1"]}, 100)

    def test_second_batch_assumptions(self):
        f = self.facts()
        asm = answers.to_assumptions(f, {"pair.u_turn_timing": "sudden", "parties.1.lane_marking": "unknown",
                                         "parties.2.lane_marking": "left_only", "road.center_line_rule_not_applied": True,
                                         "situation.special": ["reverse:1"]})
        self.assertEqual(asm["parties"]["1"]["u_turn_timing"], "sudden")
        self.assertNotIn("lane_marking", asm["parties"]["1"])
        self.assertEqual(asm["parties"]["2"]["lane_marking"], "left_only")
        self.assertTrue(asm["scene"]["center_line_rule_not_applied"])
        self.assertEqual(asm["parties"]["1"]["movement"], "reverse")

    def test_turn_specific(self):
        self.assertIn("parties.1.unprotected_left_sign", self.fields(self.facts("left_turn")))
        self.assertIn("parties.2.u_turn_type", self.fields(self.facts(mv_b="u_turn")))

    def test_same_road_asks_lead_then_lane(self):
        f = self.facts("left_turn", "straight", ("north", "north"))
        self.assertIn("pair.lead_order", self.fields(f))
        user = {"pair.lead_order": "1"}
        # 답한 질문도 목록에는 남고(답 검사용), 화면에 보일 질문은 answers.remaining이 고름
        after = [u["field"] for u in answers.remaining({"unknowns": situation.questions(f, user)}, user)]
        self.assertNotIn("pair.lead_order", after)
        self.assertIn("road.lane_fits_two", after)

    def test_stopped_only_matters_same_direction(self):
        crossing = self.facts(stopped_before_collision=True, stop_state=None)
        self.assertNotIn("parties.1.stop_state", self.fields(crossing))
        same = self.facts(came=("north", "north"), stopped_before_collision=True, stop_state=None)
        self.assertIn("parties.1.stop_state", self.fields(same))

    def test_not_for_pedestrian_or_bicycle(self):
        self.assertEqual(self.fields(self.facts(cls=("car", "bicycle"))), [])

    def test_entry_lead_follows_judge_threshold(self):
        # cc_180629: "먼저"를 1초로 올려 보내서 B의 명확한 선진입(1초, 임시값)에 늘 걸렸음
        f = self.facts()
        f["judge_thresholds"] = {"clear_lead_sec": 1.5}
        lead = lambda extra: answers.to_assumptions(f, dict({"intersection_entry_order": "1"}, **extra))["parties"]["1"]["entry_lead_sec"]
        self.assertEqual(lead({}), 0.75)                                   # 답이 없으면 명확하지 않음
        self.assertEqual(lead({"intersection_entry_clear": True}), 1.5)    # B 기준값을 따름
        self.assertEqual(lead({"intersection_entry_clear": False}), 0.75)

    def test_special_situation(self):
        f = self.facts()
        q = next(u for u in situation.questions(f, {}) if u["field"] == "situation.special")
        self.assertTrue(q["optional"])
        answers.check({"unknowns": [q]}, {"situation.special": ["emergency:2", "highway"]}, 100)
        with self.assertRaises(ValueError):
            answers.check({"unknowns": [q]}, {"situation.special": ["meteor:1"]}, 100)
        asm = answers.to_assumptions(f, {"situation.special": ["emergency:2", "highway"]})
        self.assertTrue(asm["parties"]["2"]["is_emergency"])
        self.assertFalse(asm["parties"]["1"]["is_emergency"])
        self.assertFalse(asm["parties"]["1"]["door_opening"])
        self.assertEqual(asm["scene"]["road_type"], "highway")

    def test_large_vehicle(self):
        f = self.facts()
        f["parties"]["2"]["cls"] = "truck"
        q = next(u for u in situation.questions(f, {}) if u["field"] == "situation.special")
        self.assertEqual(q["model_guess"], ["large:2"])   # 트럭·버스는 미리 골라 둠
        user = {"situation.special": ["large:2"]}
        self.assertIn("parties.2.damage_enlarged", [u["field"] for u in situation.questions(f, user)])
        self.assertNotIn("parties.1.damage_enlarged", [u["field"] for u in situation.questions(f, user)])
        asm = answers.to_assumptions(f, dict(user, **{"parties.2.damage_enlarged": True}))
        self.assertTrue(asm["parties"]["2"]["is_large"])
        self.assertFalse(asm["parties"]["1"]["is_large"])
        self.assertTrue(asm["parties"]["2"]["damage_enlarged"])

    def test_driver_factors(self):
        f = self.facts(cls=("car", "two_wheeler"))
        fields = [u["field"] for u in situation.questions(f, {})]
        self.assertIn("parties.1.driver_factors", fields)
        self.assertNotIn("parties.1.damage_severity", fields)   # 승용차는 피해 정도를 안 물음
        self.assertIn("parties.2.damage_severity", fields)      # 이륜차는 감산 때문에 물음
        q = next(u for u in situation.questions(f, {}) if u["field"] == "parties.1.driver_factors")
        self.assertTrue(q["optional"])
        asm = answers.to_assumptions(f, {"parties.1.driver_factors": ["drunk_0.03_plus", "speed_under20", "speed_20plus"],
                                         "parties.2.driver_factors": [], "parties.2.damage_severity": "severe"})
        self.assertEqual(asm["parties"]["1"]["user_factors"], ["drunk_0.03_plus"])
        self.assertEqual(asm["parties"]["1"]["speed_over_limit_kmh"], 25)   # 둘 다 고르면 큰 쪽
        self.assertEqual(asm["parties"]["2"]["user_factors"], [])
        self.assertNotIn("speed_over_limit_kmh", asm["parties"]["2"])
        self.assertEqual(asm["parties"]["2"]["damage_severity"], "severe")

    def test_slowdown_guess(self):
        """서행 추정은 확실할 때만: 멈췄으면 줄였음, 진입 직전에 빨라졌으면 안 줄였음, 나머지는 모름"""
        from src.app import slowdown
        corners = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
        self.assertTrue(slowdown.guess({"stopped_before_entry": True}, {}, corners, 30, 60))
        # 왼쪽에서 오른쪽으로 오는 차: 진입(60프레임, x=0.2) 전 30프레임은 천천히, 그 전 30프레임은 더 천천히 → 빨라짐
        speed_up = {f: (0.02 + f * 0.001, 0.5) if f < 30 else (0.05 + (f - 30) * 0.005, 0.5) for f in range(0, 61)}
        self.assertFalse(slowdown.guess({}, speed_up, corners, 30, 60))
        steady = {f: (f * 0.003, 0.5) for f in range(0, 61)}
        self.assertIsNone(slowdown.guess({}, steady, corners, 30, 60))
        self.assertIsNone(slowdown.guess({}, {}, corners, 30, None))

    def test_party_context_options(self):
        """당사자별 상황 보기는 그 당사자에게만 (좌회전한 1번만 좌회전 금지, 문 연 차의 상대만 예측 가능)"""
        f = self.facts(mv_a="left_turn", mv_b="straight")
        opts = lambda user=None: next(u for u in situation.questions(f, user or {})
                                      if u["field"] == "situation.special")["options"]
        self.assertIn("left_banned:1", opts())
        self.assertNotIn("left_banned:2", opts())
        self.assertNotIn("door_traffic:1", opts())
        user = {"situation.special": ["door:1"]}
        self.assertIn("door_traffic:1", opts(user))
        self.assertIn("door_foresee:2", opts(user))
        self.assertNotIn("door_foresee:1", opts(user))
        # 방향지시등은 회전한 1번에게만
        fields = [u["field"] for u in situation.questions(f, {})]
        self.assertIn("parties.1.turn_signal_used", fields)
        self.assertNotIn("parties.2.turn_signal_used", fields)
        asm = answers.to_assumptions(f, {"situation.special": ["left_banned:1"], "parties.1.turn_signal_used": False})
        self.assertTrue(asm["parties"]["1"]["left_turn_prohibited_violation"])
        self.assertFalse(asm["parties"]["1"]["turn_signal_used"])

    def test_special_scene_options(self):
        f = self.facts()
        asm = answers.to_assumptions(f, {"situation.special": ["night", "side_street"]})
        self.assertTrue(asm["scene"]["night"])
        self.assertFalse(asm["scene"]["low_visibility"])
        self.assertEqual(asm["scene"]["road_class"], "side_street")
        # 골목길을 안 고르면 road_class를 안 넘김 (중앙선 답이 정한 값을 덮지 않게)
        asm = answers.to_assumptions(f, {"situation.special": [], "road.center_line": False})
        self.assertEqual(asm["scene"]["road_class"], "side_street")

    def test_answers_to_assumptions(self):
        f = self.facts()
        asm = answers.to_assumptions(f, {"road.stop_sign_side": "2", "pair.lead_order": "1",
                                         "road.lane_fits_two": True, "parties.1.u_turn_type": "signal"})
        self.assertEqual(asm["parties"]["1"], {"stop_sign": False, "lead_order": "leading", "u_turn_type": "signal"})
        self.assertEqual(asm["parties"]["2"], {"stop_sign": True, "lead_order": "following"})
        self.assertTrue(asm["scene"]["lane_fits_two"])


class Chapters(unittest.TestCase):
    """인정기준 장: 이륜차는 자동차 장, 농기계는 자전거 장"""

    def test_chapter(self):
        self.assertEqual(chapters.chapter(["car", "two_wheeler"]), "vehicle")
        self.assertEqual(chapters.chapter(["truck", "farm_machine"]), "bicycle")
        self.assertEqual(chapters.chapter(["bicycle", "car"]), "bicycle")
        self.assertEqual(chapters.chapter(["pedestrian", "bicycle"]), "pedestrian")

    def test_ped_signal_only_on_crosswalk(self):
        facts = {"unknowns": chapters.questions("5", 10)}
        left = lambda a: [u["field"] for u in answers.remaining(facts, a)]
        self.assertEqual(left({}), ["parties.5.crossing_place"])
        on = {"road.signal_present": True, "parties.5.crossing_place": "near_crosswalk"}
        self.assertEqual(left(on), ["parties.5.ped_signal_at_crossing"])
        self.assertEqual(left(dict(on, **{"parties.5.crossing_place": "sidewalk"})), [])
        self.assertEqual(left(dict(on, **{"road.signal_present": False})), [])

    def test_assumptions(self):
        facts = {"fps": FPS, "parties": {}, "collision": {"a": "5", "b": "6"}}
        asm = answers.to_assumptions(facts, {"parties.5.crossing_place": "on_crosswalk",
                                             "parties.5.ped_signal_at_crossing": "red"})
        self.assertEqual(asm["parties"]["5"], {"crossing_place": "on_crosswalk", "crossing_on_crosswalk": True,
                                               "ped_signal_at_crossing": "red"})


class TapCheck(unittest.TestCase):
    def tap(self, **kw):
        t = {"frame": 10, "bbox": [0.4, 0.4, 0.1, 0.1], "cls": "car"}
        t.update(kw)
        return {"9001": t}

    def test_ok(self):
        tap_track.check(self.tap(), 100)
        tap_track.check(self.tap(cls="farm_machine"), 100)   # 농기계는 탐지로 못 잡아서 직접 표시로 받음

    def test_bad(self):
        for bad in (self.tap(frame=100), self.tap(frame="3"), self.tap(cls="plane"),
                    self.tap(bbox=[0.5, 0.5, -0.1, 2]), {"12": self.tap()["9001"]}):
            with self.assertRaises(ValueError, msg=str(bad)):
                tap_track.check(bad, 100)


class StopBeforeEntry(unittest.TestCase):
    """cc_200711: 주차장 안쪽(진입점에서 박스 높이 4배 넘게)에 서 있던 차가 진입 전 정지로 잡혀 서행 −10을 받았음"""

    def path(self, stop_at):
        pts = [(0.5, 0.2)] * 20 if stop_at == "far" else []
        pts += [(0.5, 0.2 + 0.01 * i) for i in range(1, 41)]   # 아래로 0.4 이동
        if stop_at == "near":
            pts += [pts[-1]] * 20
        pts += [(0.5, pts[-1][1] + 0.01)]
        return recs(pts, h=0.08)

    def test_far_stop_not_counted(self):
        r = self.path("far")
        self.assertFalse(zone_events.stopped_in(r, 0, r[-1]["frame"], FPS))

    def test_near_stop_counted(self):
        r = self.path("near")
        self.assertTrue(zone_events.stopped_in(r, 0, r[-1]["frame"], FPS))


class StabilizeJump(unittest.TestCase):
    def test_small_shake_ok(self):
        H = np.array([[1, 0, 3], [0, 1, 2], [0, 0, 1]], float)
        self.assertLessEqual(stabilize._jump(H, np.eye(3)), stabilize.JUMP_MAX)

    def test_unverified_ranges(self):
        # 회전·줌하는 CCTV(cc_171218, 220103): 이어 붙인 프레임의 정렬 점수가 3번 넘게 낮으면 확인 못 한 구간
        a = stabilize.ALIGN_MIN
        log = [{"frame": f, "aligned": s} for f, s in
               enumerate([50, a - 1, a - 1, 50, 0, 0, 0, 0, 50, 0, 0, 0], start=1)]
        self.assertEqual(stabilize.unverified_ranges(log), [[5, 8], [10, 12]])

    def test_broken_transform_rejected(self):
        # cc_160726: 큰 차가 화면을 가려 변환이 크게 틀어짐
        H = np.array([[0.4, 0.3, 300], [-0.2, 0.5, 200], [0, 0.001, 1]], float)
        self.assertGreater(stabilize._jump(H, np.eye(3)), stabilize.JUMP_MAX)


class GtAnswerPath(unittest.TestCase):
    """cc_190106: 정답 라벨이 교차로 안에서 시작해서, 나간 뒤의 길이 들어온 길로 잡혔음"""
    scene = {"zones": [
        {"id": "intersection", "type": "intersection", "polygon": [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]},
        {"id": "appr_n", "type": "approach", "direction": "north", "polygon": [[0.4, 0], [0.6, 0], [0.6, 0.4], [0.4, 0.4]]},
        {"id": "appr_s", "type": "approach", "direction": "south", "polygon": [[0.4, 0.6], [0.6, 0.6], [0.6, 1], [0.4, 1]]},
        {"id": "appr_w", "type": "approach", "direction": "west", "polygon": [[0, 0.4], [0.4, 0.4], [0.4, 0.6], [0, 0.6]]},
        {"id": "appr_e", "type": "approach", "direction": "east", "polygon": [[0.6, 0.4], [1, 0.4], [1, 0.6], [0.6, 0.6]]},
    ]}

    def test_full_path(self):
        p = [(f, [0.5, 0.1 + 0.05 * f]) for f in range(17)]          # 북쪽에서 내려와 남쪽으로
        r = path_facts(self.scene, p, FPS)
        self.assertEqual((r["entry_from"], r["movement"]), ("north", "straight"))

    def test_starts_inside_unknown(self):
        p = [(f, [0.5, 0.45 + 0.05 * f]) for f in range(8)]         # 교차로 안에서 시작해 남쪽으로 나감
        r = path_facts(self.scene, p, FPS)
        self.assertIsNone(r["entry_from"])
        self.assertIsNone(r["movement"])


class Collision(unittest.TestCase):
    """두 차가 다가와 닿고 멈추면 충돌, 서 있는 두 차는 충돌 아님"""

    def run_tracks(self, tracks):
        with tempfile.TemporaryDirectory() as d:
            data = {"fps": FPS, "source": "test", "video": "test.mp4", "tracks": tracks}
            with open(os.path.join(d, "tracks_final.json"), "w") as f:
                json.dump(data, f)
            with contextlib.redirect_stdout(io.StringIO()):
                detect_collision.run(d)
            with open(os.path.join(d, "collision.json")) as f:
                return json.load(f)

    def car(self, pts, moving=True):
        return {"cls": "car", "moving": moving, "frames": recs(pts)}

    def test_crash_detected(self):
        a = [(0.2 + 0.01 * i, 0.5) for i in range(25)] + [(0.45, 0.5)] * 15     # 오른쪽으로 가다 멈춤
        b = [(0.7 - 0.01 * i, 0.5) for i in range(25)] + [(0.47, 0.5)] * 15     # 왼쪽으로 가다 멈춤
        col = self.run_tracks({"1": self.car(a), "2": self.car(b)})
        self.assertTrue(col["events"])
        self.assertEqual(sorted([col["events"][0]["a"], col["events"][0]["b"]]), ["1", "2"])
        self.assertTrue(col["events"][0]["confirmed"])

    def test_parked_cars_not_collision(self):
        col = self.run_tracks({"1": self.car([(0.45, 0.5)] * 40, False), "2": self.car([(0.47, 0.5)] * 40, False)})
        self.assertFalse(col["events"])


class Signals(unittest.TestCase):
    """신호등 ↔ 진입로 연결과 연결된 신호등 색으로 당사자 신호 색 추정 (src/app/signals.py)"""
    def facts(self, states):
        return {"collision": {"a": "1", "b": "2", "frame": 60},
                "parties": {"1": {"intersection_entry": {"frame": 20}}, "2": {"intersection_entry": None}},
                "traffic_light_states": states}

    def st(self, colors, start=0, step=3, p=0.9):
        return [{"frame": start + i * step, "color": c, "p": p} for i, c in enumerate(colors)]

    def test_questions_only_lights_with_enough_records(self):
        f = self.facts({"7": self.st(["red"] * 10), "8": self.st(["red"] * 2)})
        qs = signals.questions(f, closed="west")
        self.assertEqual([q["field"] for q in qs], ["lights.7.approach"])
        self.assertNotIn("west", qs[0]["options"])   # 삼거리 길 없는 쪽은 보기에서 뺌
        self.assertTrue(qs[0]["optional"])

    def test_color_at(self):
        self.assertEqual(signals.color_at(self.st(["green"] * 20), 30)[0], "green")
        self.assertIsNone(signals.color_at(self.st(["etc"] * 20), 30))            # 노랑인지 꺼짐인지 모름
        self.assertIsNone(signals.color_at(self.st(["red", "green"] * 10), 30))   # 다수결이 갈림
        self.assertIsNone(signals.color_at(self.st(["green"] * 20, p=0.3), 30))   # 확신 낮음
        self.assertEqual(signals.color_at(self.st(["red", "etc"] * 10), 30)[0], "flashing_red")

    def test_guesses_follow_mapping(self):
        # 7번 신호등: 30프레임까지 초록, 그 뒤 빨강 → 1번 차 진입(20) 초록, 충돌(60) 빨강
        f = self.facts({"7": self.st(["green"] * 11 + ["red"] * 15)})
        self.assertEqual(signals.guesses(f, {}, {"1": "north"}), {})   # 연결 답이 없으면 추정 안 함
        g = signals.guesses(f, {"lights.7.approach": "north"}, {"1": "north", "2": "east"})
        self.assertEqual(g["parties.1.signal_at_entry"][0], "green")
        self.assertEqual(g["parties.1.signal_at_collision"][0], "red")
        self.assertNotIn("parties.2.signal_at_entry", g)   # 2번 차 쪽 신호등은 연결 안 됨
        # 진입이 색이 바뀌는 순간(30)이면 앞뒤 색이 갈려서 모름 → 질문으로
        f["parties"]["1"]["intersection_entry"] = {"frame": 30}
        self.assertNotIn("parties.1.signal_at_entry", signals.guesses(f, {"lights.7.approach": "north"}, {"1": "north"}))
        f["parties"]["1"]["intersection_entry"] = {"frame": 20}
        # 같은 길에 연결한 신호등끼리 색이 다르면 모름 (화살표 신호 등)
        f["traffic_light_states"]["9"] = self.st(["red"] * 26)
        g = signals.guesses(f, {"lights.7.approach": "north", "lights.9.approach": "north"}, {"1": "north"})
        self.assertNotIn("parties.1.signal_at_entry", g)

    def test_late_red(self):
        """진입(20) 때 초록, 1초 안에 빨강 → 적신호 직전 진입. 진입 때 이미 빨강이거나 한참 뒤 빨강이면 아님"""
        f = self.facts({"7": self.st(["green"] * 9 + ["red"] * 20)})   # 27프레임부터 빨강
        f["fps"] = 30
        user = {"lights.7.approach": "north"}
        self.assertEqual(signals.late_red(f, user, {"1": "north"}), ["1"])
        self.assertEqual(signals.late_red(f, {}, {"1": "north"}), [])   # 연결 안 함
        f["traffic_light_states"]["7"] = self.st(["green"] * 29)          # 계속 초록
        self.assertEqual(signals.late_red(f, user, {"1": "north"}), [])

    def test_guess_becomes_judge_fact(self):
        facts = {"collision": {"a": "1", "b": "2"}, "parties": {"1": {}, "2": {}}, "road": {}}
        left = [{"field": "parties.1.signal_at_entry", "model_guess": "green"}]
        jf, filled = answers.fill_guesses(facts, left)
        self.assertEqual(jf["parties"]["1"]["signal_at_entry"], "green")
        self.assertEqual(filled, ["parties.1.signal_at_entry"])


if __name__ == "__main__":
    unittest.main()
