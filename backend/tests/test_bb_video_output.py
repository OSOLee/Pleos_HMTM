"""(MTM tests/test_bb_output.py 복사본, import만 video_lib로. 출력 검사는 HMTM 자신의 analyzer를 씀)"""
"""블랙박스 분석 결과 → HMTM 분석기 출력(bb-0.2): HMTM의 출력 검사(validate_output)를 통과하는지"""
import json
import os
import tempfile
import unittest
from unittest import mock

from src.blackbox.video_lib import bb_output
from src.blackbox import analyzer as hm

VIDEO = {"duration_s": 10.0, "fps": 15.0, "frames": 150, "width": 1280, "height": 720}


def _dump(o, p):
    with open(p, "w") as fp:
        json.dump(o, fp)


def _case(partner=None, hint=None, imp=100, source="jolt_near_stop", moving_to=120):
    d = tempfile.mkdtemp()
    frames = [{"frame": i, "mag": 1.0 + i / 100, "tx": 0.1, "ty": 0.0, "scale": 0.01, "n": 100, "ok": True} for i in range(150)]
    segs = [{"state": "moving", "from": 0, "to": moving_to}, {"state": "stopped", "from": moving_to + 1, "to": 149}]
    _dump({"params": {}, "summary": {"frames": 150, "fps": 15.0, "segments": segs, "jolt_frames": [imp]}, "frames": frames},
          os.path.join(d, "ego_motion.json"))
    _dump({"fps": 15.0, "tracks": {}}, os.path.join(d, "tracks.json"))
    _dump({"impact_frame": imp, "impact_source": source, "partner": partner, "alternatives": []}, os.path.join(d, "bb_partner.json"))
    if hint is not None:
        _dump(hint, os.path.join(d, "bb_kind.json"))
    return d


def _convert(d, **kw):
    with mock.patch.object(bb_output, "_video_info", return_value=VIDEO):
        return bb_output.to_bb02(d, "x.mp4", **kw)


FRONT = {"id": "7", "cls": "car", "area": 0.1, "growth": 0.08, "frame": 99, "bbox": [0.4, 0.4, 0.3, 0.3], "side": "center", "dets": 9}
SIDE = {**FRONT, "side": "left", "bbox": [0.0, 0.4, 0.2, 0.3]}


class ContractTest(unittest.TestCase):
    def check(self, out):
        """HMTM 출력 검사를 통과하면(틀리면 status가 failed로 바뀜) 그대로 돌려준다"""
        checked = hm.validate_output(out)
        self.assertEqual(checked["status"], out["status"], checked.get("message"))
        return out

    def test_rear_ended(self):
        out = self.check(_convert(_case()))
        o = out["facts"]["parties"]["other"]
        self.assertEqual(out["facts"]["collision"]["contact"], "rear")
        self.assertEqual(o["cls"]["guess"], "car")             # 안 보이는 상대: 추정 → HMTM이 종류를 물음
        self.assertIsNone(o["cls"]["value"])
        self.assertEqual(o["lead_order"]["value"], "following")
        self.assertEqual(o["entry_from"]["value"], "south")

    def test_rear_ends_front(self):
        out = self.check(_convert(_case(partner=FRONT)))
        o = out["facts"]["parties"]["other"]
        self.assertEqual(out["facts"]["collision"]["contact"], "front")
        self.assertEqual(o["cls"]["value"], "car")
        self.assertEqual(o["lead_order"]["value"], "leading")

    def test_cut_in_is_guess(self):
        out = self.check(_convert(_case(partner=SIDE)))
        m = out["facts"]["parties"]["other"]["movement"]
        self.assertIsNone(m["value"])
        self.assertEqual(m["guess"], "lane_change")

    def test_kind_signal_sure_and_guess(self):
        sure = self.check(_convert(_case(hint={"fired": True, "kind": "person", "score": 0.85, "impact_frame": 100})))
        self.assertEqual(sure["facts"]["parties"]["other"]["cls"]["value"], "person")
        weak = self.check(_convert(_case(partner=FRONT, hint={"fired": True, "kind": "bicycle", "score": 0.5, "impact_frame": 100})))
        c = weak["facts"]["parties"]["other"]["cls"]
        self.assertIsNone(c["value"])
        self.assertEqual(c["guess"], "bicycle")

    def test_user_kind_answer(self):
        out = self.check(_convert(_case(), answers={"partner_kind": "bicycle"}))
        self.assertEqual(out["facts"]["parties"]["other"]["cls"]["guess"], "bicycle")

    def test_ego_motion_matches_spec(self):
        em = _convert(_case())["ego_motion"]
        n = len(em["t"])
        self.assertTrue(n == len(em["speed_proxy"]) == len(em["moving"]) == len(em["yaw_proxy"]))
        self.assertEqual(em["jolt_t"], [round(100 / 15.0, 3)])

    def test_scene_table_is_always_guess(self):
        """M6는 영상 단위 정확도 66%라 자동 결정에 쓰지 않는다 (B 평가 기록): 확신도가 높아도 추정으로 낸다"""
        cases = {"cross_signal": ("intersection", "cross", True), "cross_nosignal": ("intersection", "cross", False),
                 "t_junction": ("intersection", "t", None), "straight": ("straight", None, None)}
        for label, (loc, junction, signal) in cases.items():
            d = _case()
            _dump({"label": label, "confidence": 0.97, "guess": True}, os.path.join(d, "bb_scene.json"))
            road = self.check(_convert(d))["facts"]["road"]
            self.assertIsNone(road["location"]["value"], label)
            self.assertEqual(road["location"]["guess"], loc)
            self.assertEqual(road.get("junction_type", {}).get("guess"), junction)
            self.assertEqual(road.get("signal_present", {}).get("guess"), signal)
            self.assertIsNone(road.get("signal_present", {}).get("value"))

    def test_t_junction_gives_no_signal(self):
        d = _case()
        _dump({"label": "t_junction", "confidence": 0.8, "guess": True}, os.path.join(d, "bb_scene.json"))
        self.assertNotIn("signal_present", self.check(_convert(d))["facts"]["road"])

    def test_scene_auto_switch(self):
        """SCENE_AUTO를 켜고 확신도가 기준 이상이면 확정, 미만이면 추정"""
        with mock.patch.object(bb_output, "SCENE_AUTO", True):
            d = _case()
            _dump({"label": "cross_signal", "confidence": 0.95}, os.path.join(d, "bb_scene.json"))
            self.assertEqual(self.check(_convert(d))["facts"]["road"]["location"]["value"], "intersection")
            d = _case()
            _dump({"label": "cross_signal", "confidence": 0.8}, os.path.join(d, "bb_scene.json"))
            self.assertIsNone(self.check(_convert(d))["facts"]["road"]["location"]["value"])

    def test_unknown_scene_label_ignored(self):
        d = _case()
        _dump({"label": None, "confidence": None, "reason": "no_frames_or_unsupported_place"}, os.path.join(d, "bb_scene.json"))
        road = self.check(_convert(d))["facts"]["road"]
        self.assertEqual(road["location"]["guess"], "straight")

    def test_no_scene_keeps_straight_guess(self):
        road = _convert(_case())["facts"]["road"]
        self.assertEqual(road["location"]["guess"], "straight")
        self.assertNotIn("junction_type", road)

    def test_crosswalk_values(self):
        person = {"fired": True, "kind": "person", "score": 0.85, "impact_frame": 100}
        d = _case(hint=person)
        _dump({"ped_place": {"value": "crosswalk", "confidence": 0.8, "guess": False}}, os.path.join(d, "bb_crosswalk.json"))
        o = self.check(_convert(d))["facts"]["parties"]["other"]
        self.assertEqual(o["ped_place"]["value"], "crosswalk")           # 발이 박스 안: 확정
        d = _case(hint=person)
        _dump({"ped_place": {"value": "near_crosswalk", "confidence": 0.7, "guess": True},
               "dist_from_crosswalk_m": {"value": 5, "confidence": 0.7, "guess": True}}, os.path.join(d, "bb_crosswalk.json"))
        o = self.check(_convert(d))["facts"]["parties"]["other"]
        self.assertIsNone(o["ped_place"]["value"])
        self.assertEqual(o["ped_place"]["guess"], "near_crosswalk")      # 부근: 추정
        self.assertEqual(o["dist_from_crosswalk_m"]["guess"], 5)

    def test_crosswalk_empty_keeps_questions(self):
        person = {"fired": True, "kind": "person", "score": 0.85, "impact_frame": 100}
        d = _case(hint=person)
        _dump({"ped_place": None, "dist_from_crosswalk_m": None, "reason": "crosswalk_unclear"}, os.path.join(d, "bb_crosswalk.json"))
        o = self.check(_convert(d))["facts"]["parties"]["other"]
        self.assertNotIn("ped_place", o)
        self.assertNotIn("dist_from_crosswalk_m", o)

    def test_crosswalk_ignored_for_vehicle(self):
        d = _case(partner=FRONT)
        _dump({"ped_place": {"value": "crosswalk", "confidence": 0.9, "guess": False}}, os.path.join(d, "bb_crosswalk.json"))
        self.assertNotIn("ped_place", self.check(_convert(d))["facts"]["parties"]["other"])

    def test_validator_rejects_bad_output(self):
        """검사가 실제로 거르는지: 내부 id나 값 객체가 아닌 값을 넣으면 failed"""
        out = _convert(_case(partner=FRONT))
        bad = json.loads(json.dumps(out))
        bad["facts"]["parties"]["other"]["cls"] = "car"                       # 값 객체가 아님
        self.assertEqual(hm.validate_output(bad)["status"], "failed")
        bad = json.loads(json.dumps(out))
        bad["facts"]["parties"] = {"0": bad["facts"]["parties"]["ego"], "7": bad["facts"]["parties"]["other"]}   # 내부 id
        self.assertEqual(hm.validate_output(bad)["status"], "failed")

    def test_no_internal_ids(self):
        out = _convert(_case(partner=FRONT))
        self.assertEqual(set(out["facts"]["parties"]), {"ego", "other"})
        self.assertEqual((out["facts"]["collision"]["a"], out["facts"]["collision"]["b"]), ("ego", "other"))


if __name__ == "__main__":
    unittest.main()
