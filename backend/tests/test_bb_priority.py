"""과속 인과관계 질문, 정보 우선순위(확정 Q9) 시험 (2026-11-11)

  python -m pytest tests/test_bb_priority.py

  Speed      운전자 요인에서 과속을 고르면 "제한속도를 지켰다면 사고를 피할 수 있었나요?"(avoidable_at_limit)를 이어서 물음.
             예면 엔진의 속도위반 가산이 붙음 (차대차·보행자 둘 다, 두 당사자)
  SameKey    영상 확정값과 같은 질문 키로 사용자가 다르게 답하면 사용자 답으로 판정, source_conflicts에 user_vs_video
  Scene      답 키가 다른 장면 값(보행자 밤·시야 ↔ road.night, 차대차 특수 상황 "밤이었음" ↔ road.night)도 사용자 답이 이김
  Multi      여러 개 고르기: 고른 보기만 사용자 답, 안 고른 보기는 답 없음(영상 → 기본값), "해당 없음"만 전부 아니요
  Api        PUT answers로 같은 흐름

"사용자 답이 이긴다"는 같은 답을 영상 값 없이 넣은 판정과 결과(도표·비율·가감)가 같은지로 확인한다.
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
import test_bb_api as bbt
from src.blackbox import adapter, chapter, fake, sync
from src.vehicle.samples import VehicleError

START = [{"source": "filename", "start_ms": 1_762_666_212_000}]
ROAD_CROSSING = {chapter.DIST_FIELD: "no_crosswalk", chapter.PLACE_FIELD: "road", "parties.other.ped_activity": "crossing"}
EGO_DF, OTHER_DF = "parties.ego.driver_factors", "parties.other.driver_factors"
EGO_AV, OTHER_AV = "parties.ego.avoidable_at_limit", "parties.other.avoidable_at_limit"


def load(name):
    bb = fake.load_scenario(name)
    bb.pop("fake")
    return bb


def build(bb, user=None):
    return adapter.build(bb, None, sync.sync(START, bb["facts"]["collision"]["t"], None), user or {})["view"]


def fields(view):
    return [q["field"] for q in view["remaining"]]


def outcome(view):
    r = view["result"]
    return (r["status"], r["rule_id"], r["fault_by_party"], sorted((m["label"], m["delta"]) for m in r["modifiers"]))


def without(bb, where, key):
    """영상 값을 지운 사본 (where: "ego"/"other"/"road")"""
    bb = copy.deepcopy(bb)
    box = bb["facts"]["road"] if where == "road" else bb["facts"]["parties"][where]
    box.pop(key, None)
    return bb


def conflict(view, field):
    return next((c for c in view["source_conflicts"] if c["field"] == field), None)


class Speed(unittest.TestCase):
    def test_ped_followup_only_when_speeding(self):
        ped = load("ped_crosswalk_unsignalized")
        self.assertNotIn(EGO_AV, fields(build(ped, ROAD_CROSSING)))
        self.assertNotIn(EGO_AV, fields(build(ped, {**ROAD_CROSSING, EGO_DF: ["phone"]})))
        v = build(ped, {**ROAD_CROSSING, EGO_DF: ["phone", "speed_20plus"]})
        self.assertEqual(fields(v)[-1], EGO_AV)
        q = v["remaining"][-1]
        self.assertEqual((q["question"], q["options"]), ("내 차가 제한속도를 지켰다면 사고를 피할 수 있었나요?", [True, False]))
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 90, "other": 10})       # 휴대전화만 (+10)

    def test_ped_speeding_applies_with_causation(self):
        ped = load("ped_crosswalk_unsignalized")
        base = {**ROAD_CROSSING, EGO_DF: ["speed_20plus"]}
        self.assertEqual(build(ped, base)["result"]["fault_by_party"], {"ego": 80, "other": 20})   # 보23 그대로
        v = build(ped, {**base, EGO_AV: True})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 100, "other": 0})
        m, = v["result"]["modifiers"]
        self.assertEqual((m["label"], m["delta"], m["party"], m["source"]), ("A 제한속도 위반 (시속 20km 이상)", 20, "ego", "user"))
        self.assertNotIn(EGO_AV, fields(v))
        self.assertEqual(v["answers"][EGO_AV]["evidence"], "내 차가 제한속도를 지켰다면 사고를 피할 수 있었어요 (직접 답했어요)")
        self.assertEqual(build(ped, {**base, EGO_AV: False})["result"]["fault_by_party"], {"ego": 80, "other": 20})
        v = build(ped, {**ROAD_CROSSING, EGO_DF: ["speed_under20"], EGO_AV: True})       # 이 장은 10~20km/h +10
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 90, "other": 10})

    def test_car_both_parties(self):
        car = load("right_turn_left_straight")
        self.assertEqual(build(car)["result"]["fault_by_party"], {"ego": 60, "other": 40})
        v = build(car, {EGO_DF: ["speed_20plus"], OTHER_DF: ["speed_under20"]})
        self.assertEqual(fields(v)[-2:], [EGO_AV, OTHER_AV])
        self.assertTrue(v["remaining"][-1]["question"].startswith("상대 차가"))
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 60, "other": 40})
        v = build(car, {EGO_DF: ["speed_20plus"], EGO_AV: True})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 80, "other": 20})
        v = build(car, {OTHER_DF: ["speed_under20"], OTHER_AV: True})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 50, "other": 50})
        self.assertEqual([(m["party"], m["delta"], m["source"]) for m in v["result"]["modifiers"]], [("other", 10, "user")])

    def test_bad_answer(self):
        with self.assertRaises(VehicleError):
            build(load("right_turn_left_straight"), {EGO_DF: ["speed_20plus"], EGO_AV: "maybe"})


class SameKey(unittest.TestCase):
    """영상 확정값과 같은 질문 키로 다른 답 → 사용자 답, user_vs_video, 영상 값이 없던 것과 같은 판정"""
    CASES = [  # (시나리오, 영상 값 위치, 엔진 키, 질문 키, 사용자 답)
        ("right_turn_left_straight", "ego", "movement", "parties.ego.movement", "straight"),
        ("right_turn_left_straight", "other", "entry_from", "parties.other.entry_from", "right"),
        ("straight_same_time", "road", "signal_present", "road.signal_present", True),
        ("ped_crosswalk_unsignalized", "road", "crosswalk_signal", "road.crosswalk_signal", True),
        ("ped_crosswalk_unsignalized", "other", "ped_place", chapter.DIST_FIELD, "within_10m"),
        ("bike_crossing_side", "other", "on_bike_crossing", "parties.other.on_bike_crossing", False),
    ]

    def test_user_beats_video(self):
        for name, where, key, field, answer in self.CASES:
            with self.subTest(f"{name} {field}"):
                bb = load(name)
                before = build(bb)
                self.assertEqual(before["answers"][field]["source"], "video")
                self.assertNotEqual(before["answers"][field]["value"], answer)
                v = build(bb, {field: answer})
                self.assertEqual((v["answers"][field]["value"], v["answers"][field]["source"]), (answer, "user"))
                c = conflict(v, field)
                self.assertEqual((c["kind"], c["used"], c["others"][0]["source"]),
                                 ("user_vs_video", {"value": answer, "source": "user"}, "video"))
                self.assertEqual(c["others"][0]["value"], before["answers"][field]["value"])
                self.assertEqual(outcome(v), outcome(build(without(bb, where, key), {field: answer})))

    def test_answer_changes_result(self):
        """판정이 실제로 바뀌는 예: 신호 있는 횡단보도라고 답하면 보13 → 보행자 신호 질문"""
        v = build(load("ped_crosswalk_unsignalized"), {"road.crosswalk_signal": True})
        self.assertNotEqual(v["result"]["rule_id"], "보13")
        self.assertIn("parties.other.ped_signal_at_start", fields(v))


class Scene(unittest.TestCase):
    """답 키가 다른 장면 값. 전에는 영상 road.night가 facts에 남아 사용자 답을 이겼음"""

    def night(self, name, value):
        bb = load(name)
        bb["facts"]["road"]["night"] = {"value": value, "source": "model", "t": 17.0}
        return bb

    def test_ped_user_night_beats_video_day(self):
        bb = self.night("ped_crosswalk_unsignalized", False)
        v = build(bb, {chapter.VISIBILITY_FIELD: "night"})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 85, "other": 15})
        m, = v["result"]["modifiers"]
        self.assertEqual((m["label"], m["source"]), ("B 야간", "user"))
        c = conflict(v, "road.night")
        self.assertEqual((c["kind"], c["used"], c["others"][0]["value"]), ("user_vs_video", {"value": True, "source": "user"}, False))
        self.assertNotIn("road.night", v["answers"])                   # 판정에 안 쓴 영상 값은 answers에 없음
        self.assertEqual(outcome(v), outcome(build(without(bb, "road", "night"), {chapter.VISIBILITY_FIELD: "night"})))

    def test_ped_user_clear_beats_video_night(self):
        bb = self.night("ped_crosswalk_unsignalized", True)
        self.assertEqual(build(bb)["result"]["fault_by_party"], {"ego": 85, "other": 15})   # 답 없으면 영상 값
        v = build(bb, {chapter.VISIBILITY_FIELD: "clear"})
        self.assertEqual((v["result"]["fault_by_party"], v["result"]["modifiers"]), ({"ego": 100, "other": 0}, []))
        self.assertEqual([c["field"] for c in v["source_conflicts"]], [chapter.VISIBILITY_FIELD])   # 같은 내용은 하나만
        self.assertEqual(conflict(v, chapter.VISIBILITY_FIELD)["others"][0]["value"], "night")

    def test_car_special_night(self):
        bb = self.night("right_turn_left_straight", False)
        v = build(bb, {"situation.special": ["night"]})
        c = conflict(v, "road.night")
        self.assertEqual((c["kind"], c["used"]["value"], c["others"][0]["value"]), ("user_vs_video", True, False))
        self.assertEqual(outcome(v), outcome(build(without(bb, "road", "night"), {"situation.special": ["night"]})))
        self.assertNotIn(chapter.VISIBILITY_FIELD, build(bb)["answers"])   # 보행자 질문 값은 다른 장에 안 나옴

    def test_no_answer_keeps_video(self):
        v = build(self.night("right_turn_left_straight", True))
        self.assertEqual((v["answers"]["road.night"]["source"], v["source_conflicts"]), ("video", []))


class Multi(unittest.TestCase):
    """여러 개 고르기: 고른 보기만 사용자 답, 안 고른 보기는 답 없음(영상 → 기본값), "해당 없음"만 전부 아니요.
    자전거 거42-1은 야간 가산(자전거 쪽 +5)이 있음"""

    def bike(self, user=None, night=True, other=None):
        bb = load("bike_crossing_side")
        if night is not None:
            bb["facts"]["road"]["night"] = {"value": night, "source": "model", "t": 17.0}
        bb["facts"]["parties"]["other"].update(other or {})
        return build(bb, user)

    def night_mod(self, v):
        return [(m["delta"], m["source"]) for m in v["result"]["modifiers"] if m["label"].endswith("야간")]

    def test_none_option_added(self):
        v = self.bike()
        for f in ("situation.special", EGO_DF, OTHER_DF):
            q = next(q for q in v["questions"] if q["field"] == f)
            self.assertEqual((q["options"][-1], q["choices"][-1]), ("none", "해당 없음 (모두 아니요)"), f)
        q = next(q for q in v["questions"] if q["field"] == "situation.special")
        self.assertEqual(len(q["option_groups"]), len(q["options"]))

    def test_unchosen_night_keeps_video_night(self):
        """"밤이었음"을 안 고르고 영상이 밤이면 밤 가산이 붙음 (전에는 안 고른 보기 = 아니요라 빠졌음)"""
        expect = self.bike()
        self.assertEqual(self.night_mod(expect), [(5, "video")])
        for answer in ([], ["evasive:ego"], ["low_vis"]):
            with self.subTest(answer):
                v = self.bike({"situation.special": answer})
                self.assertEqual(self.night_mod(v), [(5, "video")])
                self.assertNotIn("road.night", [c["field"] for c in v["source_conflicts"]])
                self.assertEqual(v["answers"]["road.night"]["source"], "video")

    def test_explicit_none_says_no(self):
        v = self.bike({"situation.special": ["none"]})
        self.assertEqual(self.night_mod(v), [])
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 100, "other": 0})
        c = conflict(v, "road.night")
        self.assertEqual((c["kind"], c["used"], c["others"][0]["value"]), ("user_vs_video", {"value": False, "source": "user"}, True))

    def test_chosen_night_beats_video_day(self):
        v = self.bike({"situation.special": ["night"]}, night=False)
        self.assertEqual(self.night_mod(v), [(5, "user")])
        self.assertEqual(conflict(v, "road.night")["used"]["value"], True)
        self.assertEqual(self.night_mod(self.bike({"situation.special": ["night"]}, night=None)), [(5, "user")])

    def test_unchosen_without_video_is_default(self):
        """영상 값도 없으면 기본값 (밤 아님으로 정하지 않고 비워 둠 → 야간 가산 없음)"""
        v = self.bike({"situation.special": ["evasive:ego"]}, night=None)
        self.assertEqual((self.night_mod(v), v["source_conflicts"]), ([], []))

    def test_none_with_others_invalid(self):
        with self.assertRaises(VehicleError):
            self.bike({"situation.special": ["none", "night"]})
        with self.assertRaises(VehicleError):
            self.bike({EGO_DF: ["none", "phone"]})

    def test_driver_factors_keep_video(self):
        """운전자 요인: 고른 것 + 영상이 낸 것. "해당 없음"이면 영상 값도 아니요"""
        drunk = {"user_factors": {"value": ["drunk_0.03_plus"], "source": "model"}}
        base = self.bike(night=None, other=drunk)
        self.assertEqual(base["result"]["fault_by_party"], {"ego": 90, "other": 10})
        v = self.bike({OTHER_DF: ["phone"]}, night=None, other=drunk)
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 90, "other": 10})     # 음주가 안 빠짐
        self.assertEqual(conflict(v, "parties.other.user_factors")["used"]["value"], ["phone", "drunk_0.03_plus"])
        v = self.bike({OTHER_DF: ["none"]}, night=None, other=drunk)
        self.assertEqual((v["result"]["fault_by_party"], v["result"]["modifiers"]), ({"ego": 100, "other": 0}, []))
        self.assertEqual(conflict(v, "parties.other.user_factors")["used"]["value"], [])
        v = self.bike({OTHER_DF: []}, night=None, other=drunk)                          # 빈 목록 = 답 없음
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 90, "other": 10})

    def test_ped_driver_none_and_speed(self):
        """보행자 장 운전자 요인에도 "해당 없음". 과속을 고르면 인과관계 질문은 그대로"""
        ped = load("ped_crosswalk_unsignalized")
        q = next(q for q in build(ped)["questions"] if q["field"] == EGO_DF)
        self.assertEqual(q["options"][-1], "none")
        self.assertNotIn(EGO_AV, fields(build(ped, {**ROAD_CROSSING, EGO_DF: ["none"]})))
        self.assertIn(EGO_AV, fields(build(ped, {**ROAD_CROSSING, EGO_DF: ["speed_20plus"]})))


class Api(bbt.ApiBase):
    def test_put_user_beats_video(self):
        h = self.login("prio")
        cid = self.upload(h, "ped_crosswalk_unsignalized").json()["id"]
        before = self.result(h, cid)
        self.assertEqual(before["answers"]["road.crosswalk_signal"]["source"], "video")
        v = self.c.put(f"/api/bb-cases/{cid}/answers", headers=h,
                       json={"answers": {"road.crosswalk_signal": True}}).json()
        self.assertEqual(v["answers"]["road.crosswalk_signal"], {**v["answers"]["road.crosswalk_signal"],
                                                                 "value": True, "source": "user"})
        self.assertEqual(conflict(v, "road.crosswalk_signal")["kind"], "user_vs_video")
        self.assertNotEqual(v["result"]["rule_id"], before["result"]["rule_id"])
        v = self.c.put(f"/api/bb-cases/{cid}/answers", headers=h,
                       json={"answers": {EGO_DF: ["speed_20plus"]}}).json()
        self.assertIn(EGO_AV, [q["field"] for q in v["remaining"]])


if __name__ == "__main__":
    unittest.main()
