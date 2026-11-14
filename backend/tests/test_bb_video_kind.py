"""(MTM tests/test_bb_kind.py 복사본, import만 video_lib로)"""
"""사고 직전 탐지 신호(bb_kind)와 상대 종류 정하기 (bb_facts)"""
import json
import os
import tempfile
import unittest
from unittest import mock

from src.blackbox.video_lib import bb_facts, bb_kind


def _case(hint=None, partner=None, imp=100):
    d = tempfile.mkdtemp()
    json.dump({"summary": {"segments": [{"from": 0, "to": 120, "state": "moving"}], "jolt_frames": []}},
              open(os.path.join(d, "ego_motion.json"), "w"))
    json.dump({"fps": 30.0, "tracks": {}}, open(os.path.join(d, "tracks.json"), "w"))
    json.dump({"impact_frame": imp, "impact_source": "jolt_only", "partner": partner, "alternatives": []},
              open(os.path.join(d, "bb_partner.json"), "w"))
    if hint is not None:
        json.dump(hint, open(os.path.join(d, "bb_kind.json"), "w"))
    return d


def _b_cls(out):
    return out["facts"]["parties"][out["facts"]["collision"]["b"]]["cls"]


class DecideTest(unittest.TestCase):
    def test_needs_enough_frames_and_confidence(self):
        ok = [(0.6, 0.01, f, "person") for f in (10, 13, 16)]
        self.assertEqual(bb_kind.decide(ok), (True, "person", 0.6))
        self.assertFalse(bb_kind.decide(ok[:2])[0])                                   # 2프레임이면 안 됨
        self.assertFalse(bb_kind.decide([(0.3, 0.01, f, "person") for f in (10, 13, 16)])[0])   # 확신도 낮음
        self.assertFalse(bb_kind.decide([(0.9, 0.001, f, "person") for f in (10, 13, 16)])[0])  # 너무 작음

    def test_kind_is_highest_score(self):
        d = [(0.5, 0.01, 10, "person"), (0.9, 0.01, 13, "bicycle"), (0.5, 0.01, 16, "person")]
        self.assertEqual(bb_kind.decide(d)[1], "bicycle")

    def test_model_missing_does_not_break(self):
        d = _case()
        r = bb_kind.run(d, "none.mp4", model_path="models/없는모델.pt")
        self.assertFalse(r["fired"])
        self.assertEqual(r["reason"], "model_missing")
        self.assertTrue(os.path.exists(os.path.join(d, "bb_kind.json")))


class RunSettingsTest(unittest.TestCase):
    """탐지 해상도·확신도를 run 인자로 정할 수 있고, 안 주면 예전과 같은 640·0.1"""

    def _run(self, **kw):
        d = _case(imp=100)
        with tempfile.NamedTemporaryFile(suffix=".pt") as f:
            fake_cap = mock.MagicMock()
            fake_cap.get.side_effect = lambda prop: {7: 300, 3: 1280, 4: 720, 5: 30.0}.get(prop, 0)
            fake_cap.read.return_value = (True, "img")
            res = mock.MagicMock()
            res.boxes.xyxy.tolist.return_value = []
            res.boxes.conf.tolist.return_value = []
            res.boxes.cls.tolist.return_value = []
            yolo = mock.MagicMock()
            yolo.names = {0: "person"}
            yolo.predict.return_value = [res]
            with mock.patch("ultralytics.YOLO", return_value=yolo), mock.patch("cv2.VideoCapture", return_value=fake_cap):
                out = bb_kind.run(d, "v.mp4", model_path=f.name, **kw)
        return out, yolo.predict.call_args.kwargs

    def test_default_settings_unchanged(self):
        out, kw = self._run()
        self.assertEqual((kw["imgsz"], kw["conf"]), (640, 0.1))
        self.assertEqual((out["imgsz"], out["conf"]), (640, 0.1))

    def test_imgsz_and_conf_arguments_are_used(self):
        out, kw = self._run(imgsz=960, conf=0.15)
        self.assertEqual((kw["imgsz"], kw["conf"]), (960, 0.15))
        self.assertEqual((out["imgsz"], out["conf"]), (960, 0.15))


class FactsKindTest(unittest.TestCase):
    def test_no_signal_is_car(self):
        out = bb_facts.run(_case({"fired": False, "kind": None}))
        self.assertEqual(_b_cls(out), "car")
        self.assertIsNone(out["kind_source"])

    def test_signal_sets_partner_kind(self):
        for kind, cls in (("person", "pedestrian"), ("bicycle", "bicycle")):
            out = bb_facts.run(_case({"fired": True, "kind": kind}))
            self.assertEqual(_b_cls(out), cls)
            self.assertEqual(out["kind_source"], "video")

    def test_user_answer_beats_signal(self):
        d = _case({"fired": True, "kind": "person"})
        self.assertEqual(_b_cls(bb_facts.run(d, answers={"partner_kind": "vehicle"})), "car")
        self.assertEqual(_b_cls(bb_facts.run(d, answers={"partner_kind": "bicycle"})), "bicycle")
        self.assertEqual(bb_facts.run(d, answers={"partner_kind": "bicycle"})["kind_source"], "user")

    def test_signal_changes_visible_partner(self):
        p = {"id": 7, "cls": "car", "area": 0.05, "growth": 0.04, "frame": 100, "bbox": [0.4, 0.4, 0.2, 0.25],
             "side": "center", "dets": 6}
        out = bb_facts.run(_case({"fired": True, "kind": "person"}, partner=p))
        self.assertEqual(out["case"], "ego_rear_ends_front")
        self.assertEqual(_b_cls(out), "pedestrian")


if __name__ == "__main__":
    unittest.main()
