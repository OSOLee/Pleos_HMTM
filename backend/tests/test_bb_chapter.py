"""블랙박스 사건의 사고 장(상대 종류)과 장별 질문 시험 (docs/design-blackbox.md 2.4, 8.3.1, src/blackbox/chapter.py)

  python -m pytest tests/test_bb_chapter.py

  ClsSource   상대 종류: 확실하면 묻지 않음 / 확신도 낮거나 추정뿐이면 맨 앞에 물음 / 사용자가 바꾸면 그 장으로 다시 판정,
              결과 응답 other_cls(값·출처·장)
  Questions   보행자·자전거 장의 질문이 remaining에 나옴, 차대차 전용 질문은 보행자 장에서 빠짐
  Distance    횡단보도 거리 4구간 → 대표 거리(5/20/40m)로 보14~보23이 판단 보류로 남지 않음
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from src.blackbox import adapter, chapter, fake, sync

START = [{"source": "filename", "start_ms": 1_762_666_212_000}]
# 보행자 장 가감 요소 질문 (2026-11-11, 늘 묻고 도표 질문 뒤에 옴). 자세한 시험은 tests/test_bb_ped_questions.py
PED_MODS = ["parties.other.vulnerable_type", "road.protection_zone", "road.ped_visibility"]


def V(x, **kw):
    return {"value": x, "source": "model", **kw}


def bb_with(other, road=None, ego=None):
    bb = fake.load_scenario("right_turn_left_straight")
    bb.pop("fake")
    bb["facts"]["parties"]["other"] = other
    bb["facts"]["parties"]["ego"] = ego if ego is not None else {"movement": V("straight")}
    bb["facts"]["road"] = road if road is not None else {"location": V("straight")}
    return bb


def build(bb, user=None):
    s = sync.sync(START, bb["facts"]["collision"]["t"], None)
    return adapter.build(copy.deepcopy(bb), None, s, user or {})["view"]


def fields(view):
    return [q["field"] for q in view["remaining"]]


PED_SURE = bb_with({"cls": V("person", confidence=0.93), "ped_place": V("crosswalk")},
                   {"location": V("straight"), "crosswalk_signal": V(False)})


class ClsSource(unittest.TestCase):
    def test_sure_cls_not_asked(self):
        v = build(PED_SURE)
        self.assertNotIn(chapter.CLS_FIELD, fields(v))
        self.assertEqual({k: v["other_cls"][k] for k in ("value", "source", "chapter", "low_confidence")},
                         {"value": "pedestrian", "source": "video", "chapter": "car_pedestrian",
                          "low_confidence": False})
        self.assertEqual(v["other_cls"]["confidence"], 0.93)
        self.assertEqual(v["parties"]["other"]["cls"], "pedestrian")
        self.assertEqual(v["answers"][chapter.CLS_FIELD]["source"], "video")

    def test_no_confidence_is_sure(self):
        """confidence가 없으면 분석기의 value/guess 구분을 그대로 믿음 (bb-0.1 시나리오와 같음)"""
        v = build(bb_with({"cls": V("car"), "movement": V("straight"), "entry_from": V("west")}))
        self.assertNotIn(chapter.CLS_FIELD, fields(v))
        self.assertEqual((v["other_cls"]["source"], v["other_cls"]["chapter"]), ("video", "car_car"))

    def test_low_confidence_asked_first(self):
        bb = copy.deepcopy(PED_SURE)
        bb["facts"]["parties"]["other"]["cls"]["confidence"] = chapter.CLS_MIN_CONF - 0.15
        v = build(bb)
        self.assertEqual(fields(v)[0], chapter.CLS_FIELD)
        self.assertEqual(v["remaining"][0]["model_guess"], "pedestrian")
        self.assertEqual(v["remaining"][0]["guess_source"], "video")
        self.assertIn("확신도", v["remaining"][0]["guess_evidence"])
        self.assertEqual(v["status"], "needs_answers")
        self.assertTrue(v["result"]["provisional"])
        # 추정 종류로 임시 판정: 보행자 장
        self.assertEqual((v["result"]["rule_id"], v["other_cls"]["source"], v["other_cls"]["low_confidence"]),
                         ("보13", "guess", True))

    def test_guess_only_asked_first(self):
        bb = bb_with({"cls": V(None, guess="bicycle", confidence=0.5), "on_bike_crossing": V(True),
                      "movement": V("straight"), "entry_from": V("west")})
        v = build(bb)
        self.assertEqual(fields(v)[0], chapter.CLS_FIELD)
        self.assertEqual(v["other_cls"]["chapter"], "car_bicycle")
        self.assertEqual(v["result"]["rule_id"], "거42-1")
        self.assertEqual(chapter.CLS_MIN_CONF, 0.7)

    def test_user_changes_cls_rejudges(self):
        """C: 사용자가 상대 종류를 바꾸면 저장된 bb_facts로 그 장에서 다시 판정"""
        car = bb_with({"cls": V("car", confidence=0.95), "movement": V("straight"), "entry_from": V("west")},
                      {"location": V("straight"), "crosswalk_signal": V(False)})
        v = build(car)
        self.assertEqual(v["other_cls"]["chapter"], "car_car")
        v = build(car, {chapter.CLS_FIELD: "pedestrian", "parties.other.crosswalk_distance": "on"})
        self.assertEqual({k: v["other_cls"][k] for k in ("value", "source", "chapter")},
                         {"value": "pedestrian", "source": "user", "chapter": "car_pedestrian"})
        self.assertEqual(v["result"]["rule_id"], "보13")
        self.assertIn("user_vs_video", [c["kind"] for c in v["source_conflicts"] if c["field"] == chapter.CLS_FIELD])
        # 확실한 영상 값도 사용자가 바꿀 수 있음 (보행자 → 자전거)
        v = build(PED_SURE, {chapter.CLS_FIELD: "bicycle", "parties.other.on_bike_crossing": True})
        self.assertEqual(v["other_cls"]["chapter"], "car_bicycle")
        self.assertIn("parties.other.movement", fields(v))     # 자전거 장은 상대 진행 방향이 있어야 역할을 정함
        v = build(PED_SURE, {chapter.CLS_FIELD: "bicycle", "parties.other.on_bike_crossing": True,
                             "parties.other.movement": "straight", "parties.other.entry_from": "left"})
        self.assertEqual(v["result"]["rule_id"], "거42-1")

    def test_user_answer_person_name(self):
        """분석기 이름 person으로 답해도 보행자로 받음"""
        v = build(PED_SURE, {chapter.CLS_FIELD: "person"})
        self.assertEqual((v["other_cls"]["value"], v["other_cls"]["source"]), ("pedestrian", "user"))

    def test_bad_cls_answer(self):
        from src.vehicle.samples import VehicleError
        with self.assertRaises(VehicleError):
            build(PED_SURE, {chapter.CLS_FIELD: "dog"})


class Questions(unittest.TestCase):
    def test_ped_chapter_questions(self):
        v = build(bb_with({"cls": V("person", confidence=0.9)}))
        f = fields(v)
        self.assertIn("parties.other.crosswalk_distance", f)
        for vehicle_only in ("parties.other.movement", "parties.other.entry_from", "road.wider_road",
                             "intersection_entry_order"):
            self.assertNotIn(vehicle_only, [q["field"] for q in v["questions"]])
        self.assertNotIn("road.wider_road", v["answers"])
        # 신호 있는 횡단보도 위 → 보행자 신호 두 시점, 내 차 신호, 교차로 통과 여부를 물음
        v = build(bb_with({"cls": V("person", confidence=0.9)}),
                  {"parties.other.crosswalk_distance": "on", "road.crosswalk_signal": True})
        self.assertEqual(set(fields(v)), {"parties.other.ped_signal_at_start", "parties.other.ped_signal_at_impact",
                                          "parties.ego.signal_at_entry", "parties.ego.impact_after_intersection"}
                         | set(PED_MODS))
        self.assertEqual(fields(v)[-3:], PED_MODS)              # 가감 요소 질문은 도표 선택 질문 뒤
        v = build(bb_with({"cls": V("person", confidence=0.9)}),
                  {"parties.other.crosswalk_distance": "on", "road.crosswalk_signal": True,
                   "parties.other.ped_signal_at_start": "green", "parties.other.ped_signal_at_impact": "red",
                   "parties.ego.signal_at_entry": "green", "parties.ego.impact_after_intersection": False})
        self.assertEqual((v["status"], v["result"]["rule_id"], fields(v)), ("needs_answers", "보11(가)", PED_MODS))

    def test_ped_video_values_skip_questions(self):
        """영상이 정한 보행자 항목은 묻지 않음 (질문 키가 엔진 이름 그대로)"""
        bb = bb_with({"cls": V("person", confidence=0.9), "ped_place": V("crosswalk"),
                      "ped_signal_at_start": V("green"), "ped_signal_at_impact": V(None, guess="red")},
                     {"location": V("straight"), "crosswalk_signal": V(True)})
        v = build(bb)
        f = fields(v)
        self.assertNotIn("parties.other.crosswalk_distance", f)
        self.assertNotIn("parties.other.ped_signal_at_start", f)
        q = next(q for q in v["remaining"] if q["field"] == "parties.other.ped_signal_at_impact")
        self.assertEqual((q["model_guess"], q["guess_source"]), ("red", "video"))

    def test_ped_place_other(self):
        bb = bb_with({"cls": V("person", confidence=0.9)})
        v = build(bb, {"parties.other.crosswalk_distance": "no_crosswalk"})
        self.assertEqual(fields(v)[:2], ["road.expressway", "parties.other.ped_place_other"])
        v = build(bb, {"parties.other.crosswalk_distance": "no_crosswalk", "parties.other.ped_place_other": "sidewalk"})
        self.assertEqual(v["result"]["rule_id"], "보24")
        v = build(bb, {"parties.other.crosswalk_distance": "no_crosswalk", "parties.other.ped_place_other": "roadway"})
        self.assertIn("road.sidewalk_separated", fields(v))
        self.assertIn("parties.other.roadway_walk_position", fields(v))

    def test_bike_chapter_questions(self):
        bb = bb_with({"cls": V("bicycle", confidence=0.9), "movement": V("straight"), "entry_from": V("west")})
        v = build(bb)
        f = [q["field"] for q in v["questions"]]
        self.assertIn("parties.other.on_bike_crossing", f)
        # 자전거는 차대차 상황 질문(일시정지 표지 등)도 받음: 교차로면 stop_sign_side
        bb["facts"]["road"] = {"location": V("intersection"), "junction_type": V("cross"),
                               "signal_present": V(False)}
        v = build(bb)
        self.assertIn("road.stop_sign_side", [q["field"] for q in v["questions"]])
        v = build(bb, {"parties.other.on_bike_crossing": False})
        self.assertIn("parties.other.crossing_road", [q["field"] for q in v["questions"]])

    def test_car_chapter_unchanged(self):
        v = build(bb_with({"cls": V("car"), "movement": V("straight"), "entry_from": V("west")}))
        f = [q["field"] for q in v["questions"]]
        self.assertNotIn("parties.other.crosswalk_distance", f)
        self.assertNotIn("parties.other.on_bike_crossing", f)


class Distance(unittest.TestCase):
    """횡단보도 거리 4구간 (A_REQUESTS 1. "횡단보도 거리는 도표가 4구간을 쓴다")"""
    PED = bb_with({"cls": V("person", confidence=0.9)}, {"location": V("straight")})

    def test_bins_pick_charts(self):
        base = {"road.crosswalk_signal": False}
        cases = {"on": ("보13", {"ego": 100, "other": 0}),
                 "within_10m": ("보20", {"ego": 80, "other": 20}),
                 "10_30m": ("보20", {"ego": 70, "other": 30})}        # 10~30m: 보행자 +10 (ped_near_10_30m)
        for b, (rule, fault) in cases.items():
            with self.subTest(b):
                v = build(self.PED, {**base, "parties.other.crosswalk_distance": b})
                self.assertEqual((v["result"]["rule_id"], v["result"]["fault_by_party"]), (rule, fault))
        v = build(self.PED, {"parties.other.crosswalk_distance": "over_30m", "parties.other.ped_activity": "crossing"})
        self.assertEqual(v["result"]["rule_id"], "보23")
        self.assertNotIn("road.crosswalk_signal", [q["field"] for q in v["questions"]])

    def test_engine_values(self):
        for b, m in chapter.BIN_M.items():
            p, _ = chapter.engine_values(chapter.CAR_PED, {chapter.DIST_FIELD: b})
            self.assertEqual(p["other"], {"ped_place": "near_crosswalk", "dist_from_crosswalk_m": m})
        p, _ = chapter.engine_values(chapter.CAR_PED, {chapter.DIST_FIELD: "no_crosswalk",
                                                       chapter.PLACE_FIELD: "near_overpass",
                                                       chapter.OVERPASS_FIELD: "10_30m"})
        self.assertEqual(p["other"], {"ped_place": "near_overpass", "dist_from_crosswalk_m": 20})
        self.assertEqual(chapter.BIN_M, {"within_10m": 5, "10_30m": 20, "over_30m": 40})

    def test_video_distance_to_bin(self):
        """분석기 거리(값 객체) → 4구간 질문 키. 잰 값이면 확실한 값, 대표값 추정이면 추정값"""
        bb = bb_with({"cls": V("person", confidence=0.9), "ped_place": V("near_crosswalk"),
                      "dist_from_crosswalk_m": V(18.0, bin="10_30m", measured=True)},
                     {"location": V("straight"), "crosswalk_signal": V(False)})
        v = build(bb)
        self.assertEqual(v["answers"]["parties.other.crosswalk_distance"]["value"], "10_30m")
        self.assertEqual(v["result"]["rule_id"], "보20")
        bb["facts"]["parties"]["other"]["dist_from_crosswalk_m"] = V(None, guess=5, bin="within_10m")
        v = build(bb)
        q = next(q for q in v["remaining"] if q["field"] == "parties.other.crosswalk_distance")
        self.assertEqual(q["model_guess"], "within_10m")
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 80, "other": 20})


if __name__ == "__main__":
    unittest.main()


class Scenarios(unittest.TestCase):
    """가짜 분석기 보행자·자전거 시나리오 (설계 2.4). cls를 확실하게 낸 그대로와 guess만 낸 경우"""
    NAMES = ("ped_crosswalk_unsignalized", "bike_crossing_side")

    def load(self, name):
        bb = fake.load_scenario(name)
        return bb, bb.pop("fake")["expect"]

    def check(self, view, exp, name):
        got = {"status": view["status"], "judge_status": view["result"]["status"],
               "rule_id": view["result"]["rule_id"], "fault_by_party": view["result"]["fault_by_party"],
               "chapter": view["other_cls"]["chapter"]}
        self.assertEqual(got, {k: exp[k] for k in got}, name)

    def test_sure_cls(self):
        for name in self.NAMES:
            with self.subTest(name):
                bb, exp = self.load(name)
                v = build(bb)
                self.check(v, exp, name)
                self.assertEqual(v["other_cls"]["source"], "video")
                self.assertNotIn(chapter.CLS_FIELD, fields(v))
        v = build(self.load("ped_crosswalk_unsignalized")[0])
        # 도표 질문은 영상이 다 정함. 가감 요소 질문(어린이·노인, 보호구역, 밤·시야)만 남음 (2026-11-11)
        self.assertEqual((fields(v), v["result"]["provisional"]), (PED_MODS, True))

    def test_guess_only_cls(self):
        """같은 시나리오에서 cls만 guess로: 같은 장으로 임시 판정, 상대 종류 질문이 맨 앞, 답하면 확실한 경우와 같음"""
        for name in self.NAMES:
            with self.subTest(name):
                bb, exp = self.load(name)
                c = bb["facts"]["parties"]["other"]["cls"]
                bb["facts"]["parties"]["other"]["cls"] = {"value": None, "source": "model", "guess": c["value"],
                                                          "confidence": 0.5}
                v = build(bb)
                self.assertEqual(fields(v)[0], chapter.CLS_FIELD)
                self.assertEqual(v["remaining"][0]["model_guess"], chapter.to_answer_cls(c["value"]))
                self.assertEqual((v["status"], v["result"]["provisional"]), ("needs_answers", True))
                self.assertEqual((v["other_cls"]["source"], v["result"]["rule_id"]), ("guess", exp["rule_id"]))
                v = build(bb, {chapter.CLS_FIELD: chapter.to_answer_cls(c["value"])})
                self.check(v, exp, name)
                self.assertEqual(v["other_cls"]["source"], "user")


class FaultDisplay(unittest.TestCase):
    """결과 비율 표기 (설계 3.6): 차대보행자는 보행자 과실만, 나머지는 내 차 : 상대"""

    def test_pedestrian_only(self):
        v = build(PED_SURE, {"road.crosswalk_signal": False, "parties.other.crosswalk_distance": "10_30m"})
        r = v["result"]
        self.assertEqual((r["chapter"], r["fault_by_party"]), ("car_pedestrian", {"ego": 70, "other": 30}))
        self.assertEqual({k: r["fault_display"][k] for k in ("kind", "party", "value", "text")},
                         {"kind": "pedestrian_only", "party": "other", "value": 30, "text": "보행자 과실 30%"})
        self.assertIn("70%", r["fault_display"]["note"])
        self.assertEqual(sum(r["fault_by_party"].values()), 100)

    def test_ratio_for_other_chapters(self):
        bb, _ = Scenarios().load("bike_crossing_side")
        r = build(bb)["result"]
        self.assertEqual((r["chapter"], r["fault_display"]["kind"], r["fault_display"]["text"]),
                         ("car_bicycle", "ratio", "내 차 100 : 상대 0"))
        r = build(fake_car())["result"]
        self.assertEqual((r["chapter"], r["fault_display"]["text"]), ("car_car", "내 차 60 : 상대 40"))

    def test_no_rule_has_no_display(self):
        r = build(bb_with({"cls": V("person", confidence=0.9)}))["result"]
        self.assertEqual((r["status"], r["fault_display"], r["chapter"]), ("no_rule", None, "car_pedestrian"))


def fake_car():
    bb = fake.load_scenario("right_turn_left_straight")
    bb.pop("fake")
    return bb
