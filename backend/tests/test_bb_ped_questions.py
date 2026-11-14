"""블랙박스 보행자 장 질문 보완 시험 (2026-11-11)

  python -m pytest tests/test_bb_ped_questions.py

  Order       도표 선택 질문 먼저, 가감 요소 질문(어린이·노인, 보호구역, 밤·시야) 뒤, 운전자 요인은 선택 질문
  Modifiers   가감 요소 답 → 판정 가감이 바뀜 (보행자 시나리오 보13 100:0 → 밤이면 85:15)
  Driver      운전자 요인(휴대전화·과속) → 내 차 가산 (보23 80:20 → 90:10)
  Expressway  고속도로 질문 → 보35·보36, 고속도로면 장소 질문은 빠짐
  Video       영상이 밤을 확실히 내면 밤·시야 질문을 묻지 않음. 사용자가 장소를 고치면 영상 장소를 판정에서 뺌
  Api         PUT answers로 같은 흐름
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
import test_bb_api as bbt
from src.blackbox import adapter, chapter, fake, sync

START = [{"source": "filename", "start_ms": 1_762_666_212_000}]
SCENARIO = "ped_crosswalk_unsignalized"
MODS = [chapter.VULNERABLE_FIELD, chapter.ZONE_FIELD, chapter.VISIBILITY_FIELD]
FAR = {chapter.DIST_FIELD: "no_crosswalk"}
ROAD_CROSSING = {**FAR, chapter.PLACE_FIELD: "road", "parties.other.ped_activity": "crossing"}


def scenario():
    bb = fake.load_scenario(SCENARIO)
    bb.pop("fake")
    return bb


def build(user=None, bb=None):
    bb = bb or scenario()
    return adapter.build(bb, None, sync.sync(START, bb["facts"]["collision"]["t"], None), user or {})["view"]


def fields(view):
    return [q["field"] for q in view["remaining"]]


def mods(view):
    return {m["label"]: m["delta"] for m in view["result"]["modifiers"]}


class Order(unittest.TestCase):
    def test_scenario_asks_modifiers_only(self):
        """횡단보도 위·신호 없음은 영상이 정함 → 가감 요소 질문 셋만 남고, 결과는 임시"""
        v = build()
        self.assertEqual(fields(v), MODS)
        self.assertEqual((v["status"], v["result"]["rule_id"], v["result"]["provisional"]), ("needs_answers", "보13", True))
        self.assertEqual(v["remaining"][0]["choices"][0], "어린이 (만 13세 미만)")

    def test_chart_questions_before_modifiers(self):
        v = build(FAR)
        f = fields(v)
        self.assertEqual(f[:3], [chapter.EXPRESSWAY_FIELD, chapter.PLACE_FIELD, "parties.other.ped_activity"])
        self.assertEqual(f[-3:], MODS)

    def test_driver_factors_optional(self):
        """운전자 요인은 차대차처럼 선택 질문: questions에 있고 remaining에는 없음 (답하지 않아도 done이 됨)"""
        v = build()
        q = next(q for q in v["questions"] if q["field"] == chapter.DRIVER_FIELD)
        self.assertEqual((q["optional"], q["answer_type"], q["model_guess"]), (True, "multi", []))
        self.assertIn("phone", q["options"])
        self.assertNotIn(chapter.DRIVER_FIELD, fields(v))

    def test_all_answered_done(self):
        v = build({chapter.VULNERABLE_FIELD: "none", chapter.ZONE_FIELD: "none", chapter.VISIBILITY_FIELD: "clear"})
        self.assertEqual((v["status"], v["remaining"], v["result"]["provisional"]), ("done", [], False))
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 100, "other": 0})


class Modifiers(unittest.TestCase):
    def test_night_changes_ratio(self):
        before = build()
        after = build({chapter.VISIBILITY_FIELD: "night"})
        self.assertEqual(before["result"]["fault_by_party"], {"ego": 100, "other": 0})
        self.assertEqual(after["result"]["fault_by_party"], {"ego": 85, "other": 15})
        self.assertEqual(mods(after), {"B 야간": 15})
        self.assertEqual(after["result"]["fault_display"]["text"], "보행자 과실 15%")
        self.assertEqual(after["answers"][chapter.VISIBILITY_FIELD]["evidence"], "밤이었어요 (직접 답했어요)")

    def test_view_obstructed(self):
        self.assertEqual(mods(build({chapter.VISIBILITY_FIELD: "obstructed"})), {"B 기타 시야장애": 15})

    def test_child_in_child_zone(self):
        """어린이 + 어린이보호구역(신호 없는 횡단보도): 보호구역 감산 하나만 (어린이 감산과 하나만)"""
        v = build({chapter.VULNERABLE_FIELD: "child", chapter.ZONE_FIELD: "child", chapter.VISIBILITY_FIELD: "night"})
        m = mods(v)
        self.assertEqual(m["B 야간"], 15)
        self.assertEqual(sum(d for k, d in m.items() if k != "B 야간"), -15)
        self.assertEqual(len(m), 2)
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 100, "other": 0})

    def test_elderly_outside_zone(self):
        v = build({**ROAD_CROSSING, chapter.VULNERABLE_FIELD: "elderly", chapter.ZONE_FIELD: "none"})
        self.assertEqual(v["result"]["rule_id"], "보23")
        self.assertEqual(mods(v), {"B 어린이·노인·장애인": -5})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 85, "other": 15})


class Driver(unittest.TestCase):
    def test_phone_and_speed(self):
        base = build(ROAD_CROSSING)
        self.assertEqual((base["result"]["rule_id"], base["result"]["fault_by_party"]), ("보23", {"ego": 80, "other": 20}))
        v = build({**ROAD_CROSSING, chapter.DRIVER_FIELD: ["phone"]})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 90, "other": 10})
        m = next(m for m in v["result"]["modifiers"] if m["party"] == "ego")
        self.assertEqual((m["delta"], m["source"]), (10, "user"))
        # 과속은 인과관계 질문(avoidable_at_limit)까지 답해야 가산됨 → tests/test_bb_priority.py Speed
        v = build({**ROAD_CROSSING, chapter.DRIVER_FIELD: ["drunk_0.03_plus"]})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 100, "other": 0})


class Expressway(unittest.TestCase):
    def test_walk_reason_picks_chart(self):
        v = build({**FAR, chapter.EXPRESSWAY_FIELD: True})
        self.assertEqual(v["result"]["status"], "no_rule")                 # 이유를 모르면 보35·보36 판단 보류
        self.assertEqual(fields(v)[0], chapter.WALK_REASON_FIELD)
        self.assertNotIn(chapter.PLACE_FIELD, fields(v))                    # 고속도로 도표는 장소를 안 읽음
        self.assertIn("parties.other.on_shoulder", fields(v))
        v = build({**FAR, chapter.EXPRESSWAY_FIELD: True, chapter.WALK_REASON_FIELD: "none"})
        self.assertEqual((v["result"]["rule_id"], v["result"]["fault_by_party"]), ("보35", {"ego": 20, "other": 80}))
        self.assertNotIn("road.ped_warning_sign", fields(v))                # 표지 감산은 보36만

    def test_justified_with_shoulder_and_sign(self):
        v = build({**FAR, chapter.EXPRESSWAY_FIELD: True, chapter.WALK_REASON_FIELD: "justified",
                   "parties.other.on_shoulder": True, "road.ped_warning_sign": True})
        self.assertEqual(v["result"]["rule_id"], "보36")
        self.assertEqual(mods(v), {"B 갓길 보행 중 사고": -20, "B 안전표지 설치": -20})
        self.assertEqual(v["result"]["fault_by_party"], {"ego": 80, "other": 20})

    def test_bad_weather_on_expressway(self):
        v = build({**FAR, chapter.EXPRESSWAY_FIELD: True, chapter.WALK_REASON_FIELD: "none",
                   chapter.VISIBILITY_FIELD: "bad_weather"})
        self.assertEqual(mods(v), {"B 악천후 등 시야확보 곤란": 20})

    def test_not_asked_on_crosswalk(self):
        self.assertNotIn(chapter.EXPRESSWAY_FIELD, [q["field"] for q in build()["questions"]])


class Video(unittest.TestCase):
    def test_video_night_skips_visibility(self):
        bb = scenario()
        bb["facts"]["road"]["night"] = {"value": True, "source": "model", "t": 17.0}
        v = build(bb=bb)
        self.assertNotIn(chapter.VISIBILITY_FIELD, fields(v))
        self.assertEqual(mods(v), {"B 야간": 15})
        self.assertEqual(v["answers"][chapter.VISIBILITY_FIELD]["source"], "video")

    def test_video_night_guess_is_model_guess(self):
        bb = scenario()
        bb["facts"]["road"]["night"] = {"value": None, "source": "model", "guess": True}
        q = next(q for q in build(bb=bb)["remaining"] if q["field"] == chapter.VISIBILITY_FIELD)
        self.assertEqual((q["model_guess"], q["guess_source"]), ("night", "video"))

    def test_user_place_replaces_video_place(self):
        """영상은 횡단보도 위(보13). 사용자가 횡단보도 없음이라고만 답하면 영상 장소를 쓰지 않고 판단 보류"""
        v = build(FAR)
        self.assertEqual(v["result"]["status"], "no_rule")
        self.assertEqual(build(ROAD_CROSSING)["result"]["rule_id"], "보23")


class Api(bbt.ApiBase):
    def test_put_answers_changes_result(self):
        h = self.login("ped")
        cid = self.upload(h, SCENARIO).json()["id"]
        view = self.result(h, cid)
        self.assertEqual((view["status"], fields(view), view["remaining_count"]), ("needs_answers", MODS, 3))
        r = self.c.put(f"/api/bb-cases/{cid}/answers", headers=h,
                       json={"answers": {chapter.VULNERABLE_FIELD: "none", chapter.ZONE_FIELD: "none",
                                         chapter.VISIBILITY_FIELD: "night"}})
        self.assertEqual(r.status_code, 200, r.text)
        v = r.json()
        self.assertEqual((v["status"], v["remaining_count"]), ("done", 0))
        self.assertEqual(v["result"]["fault_display"]["text"], "보행자 과실 15%")
        self.assertEqual([q["field"] for q in v["answered"]], MODS)
        bad = self.c.put(f"/api/bb-cases/{cid}/answers", headers=h,
                         json={"answers": {chapter.VISIBILITY_FIELD: "foggy"}})
        self.assertEqual((bad.status_code, bad.json()["error"]), (422, "answer_invalid"))


if __name__ == "__main__":
    unittest.main()
