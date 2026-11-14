"""(MTM tests/test_bb_scene_crosswalk.py 복사본, import만 video_lib로)"""
"""장면(M6)·횡단보도(M5) 신호 실행부 — 모델은 가짜로 대신 (B의 참고 구현 scene_crosswalk를 우리 영상·사고 순간에 붙이는 부분)"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

from src.blackbox.video_lib import bb_crosswalk, bb_scene

FPS, W, H = 15.0, 160, 120


class T:
    """텐서 흉내: .cpu().numpy() / .tolist()"""
    def __init__(self, a):
        self.a = np.asarray(a)

    def cpu(self):
        return self

    def numpy(self):
        return self.a

    def tolist(self):
        return self.a.tolist()


class ClsModel:
    names = {0: "cross_signal", 1: "cross_nosignal", 2: "t_junction", 3: "straight"}

    def __init__(self, probs):
        self.probs = probs
        self.calls = []

    def predict(self, imgs, imgsz=384, verbose=False):
        self.calls.append(len(imgs))

        class P:
            pass
        out = []
        for _ in imgs:
            r = P()
            r.names = self.names
            r.probs = P()
            r.probs.data = T(self.probs)
            out.append(r)
        return out


class CwModel:
    def __init__(self, boxes):
        self.boxes_xyxy = boxes          # 모든 프레임에 같은 횡단보도 박스
        self.confs = []                  # predict에 넘어온 conf

    def predict(self, imgs, imgsz=960, conf=0.25, verbose=False):
        self.confs.append(conf)

        class P:
            pass
        out = []
        for _ in imgs:
            r = P()
            r.names = {0: "crosswalk"}
            r.boxes = P()
            r.boxes.cls = T([0] * len(self.boxes_xyxy))
            r.boxes.conf = T([0.9] * len(self.boxes_xyxy))
            r.boxes.xyxy = T(np.array(self.boxes_xyxy, dtype=float).reshape(-1, 4))
            out.append(r)
        return out


def make_video(path, n=75):
    import cv2
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(n):
        vw.write(np.full((H, W, 3), (i * 3) % 255, dtype=np.uint8))
    vw.release()
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bb_sc_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.video = make_video(os.path.join(self.tmp, "v.mp4"))
        self.model = os.path.join(self.tmp, "m.pt")
        open(self.model, "w").close()
        self.case = os.path.join(self.tmp, "case")
        os.makedirs(self.case)
        self.dump("bb_partner.json", {"impact_frame": 60, "impact_source": "jolt_only", "partner": None, "alternatives": []})
        self.dump("ego_motion.json", {"summary": {"segments": [{"state": "moving", "from": 0, "to": 70}]}})

    def dump(self, name, obj):
        with open(os.path.join(self.case, name), "w", encoding="utf-8") as fp:
            json.dump(obj, fp)


class SceneTest(Base):
    def run_scene(self, probs, model_path=None):
        with mock.patch("ultralytics.YOLO", lambda p: ClsModel(probs)):
            return bb_scene.run(self.case, self.video, model_path=model_path or self.model)

    def test_label_and_confidence_are_averaged_and_guess(self):
        out = self.run_scene([0.05, 0.05, 0.85, 0.05])
        self.assertEqual(out["label"], "t_junction")
        self.assertAlmostEqual(out["confidence"], 0.85, places=3)
        self.assertTrue(out["guess"])
        self.assertGreaterEqual(out["frames"], 3)
        self.assertTrue(os.path.exists(os.path.join(self.case, "bb_scene.json")))

    def test_model_missing(self):
        out = bb_scene.run(self.case, self.video, model_path=os.path.join(self.tmp, "없음.pt"))
        self.assertIsNone(out["label"])
        self.assertEqual(out["reason"], "model_missing")

    def test_uses_five_frames_just_before_impact(self):
        """충돌 직전 5장면(0.5초 간격, 2초 전 ~ 충돌 순간)을 평균낸다 (예전엔 3초 전부터 최대 7장)"""
        model = ClsModel([0.05, 0.05, 0.85, 0.05])
        with mock.patch("ultralytics.YOLO", lambda p: model):
            out = bb_scene.run(self.case, self.video, model_path=self.model)
        self.assertEqual(out["frames"], 5)
        self.assertEqual(model.calls, [5])

    def test_never_more_than_five_even_if_window_is_wider(self):
        from src.blackbox.video_lib import scene_crosswalk as sc
        model = ClsModel([0.05, 0.05, 0.85, 0.05])
        frames = [(i * 0.5, np.zeros((H, W, 3), dtype=np.uint8)) for i in range(0, 9)]     # 0 ~ 4.0초
        with mock.patch.object(sc, "SCENE_WINDOW", (-4.0, 0.0)):
            facts = sc.classify_scene(model, frames, 4.0)
        self.assertEqual(model.calls, [5])
        self.assertEqual(next(iter(facts.values())).hints["frames"], 5)


class CrosswalkTest(Base):
    def kind(self, fired=True, kind="person", feet_box=(60, 40, 80, 100)):
        self.dump("bb_kind.json", {"fired": fired, "kind": kind, "score": 0.8, "impact_frame": 60, "fps": FPS,
                                   "person_boxes": [{"frame": f, "box": list(feet_box) + [0.8]} for f in range(46, 63, 3)]})

    def run_cw(self, boxes):
        with mock.patch("ultralytics.YOLO", lambda p: CwModel(boxes)):
            return bb_crosswalk.run(self.case, self.video, model_path=self.model)

    def test_crosswalk_model_gets_conf_015_by_default_and_can_be_changed(self):
        """conf를 넘기지 않으면 ultralytics 기본 0.25로 돌아가던 것을 0.15로 (B 요청)"""
        self.kind()
        model = CwModel([(20, 80, 140, 115)])
        with mock.patch("ultralytics.YOLO", lambda p: model):
            bb_crosswalk.run(self.case, self.video, model_path=self.model)
            bb_crosswalk.run(self.case, self.video, model_path=self.model, conf=0.3)
        self.assertEqual(model.confs, [0.15, 0.3])

    def test_on_crosswalk(self):
        self.kind()                                           # 발 (70, 100)
        out = self.run_cw([(20, 80, 140, 115)])               # 발이 박스 안 (높이 35)
        self.assertEqual(out["ped_place"]["value"], "crosswalk")
        self.assertFalse(out["ped_place"]["guess"])

    def test_near_crosswalk_is_guess(self):
        self.kind(feet_box=(60, 10, 80, 40))                  # 발 (70, 40)
        out = self.run_cw([(20, 60, 140, 75)])                # 박스 위쪽에서 떨어져 있음
        self.assertEqual(out["ped_place"]["value"], "near_crosswalk")
        self.assertTrue(out["ped_place"]["guess"])

    def test_no_crosswalk_seen_gives_nothing(self):
        self.kind()
        out = self.run_cw([])
        self.assertIsNone(out["ped_place"])
        self.assertEqual(out["reason"], "crosswalk_unclear")

    def test_skipped_without_pedestrian_signal(self):
        self.kind(fired=False, kind=None)
        out = self.run_cw([(20, 80, 140, 115)])
        self.assertIsNone(out["ped_place"])
        self.assertEqual(out["reason"], "no_pedestrian")

    def test_skipped_for_bicycle(self):
        self.kind(kind="bicycle")
        self.assertEqual(self.run_cw([(20, 80, 140, 115)])["reason"], "no_pedestrian")

    def test_model_missing(self):
        self.kind()
        out = bb_crosswalk.run(self.case, self.video, model_path=os.path.join(self.tmp, "없음.pt"))
        self.assertEqual(out["reason"], "model_missing")


if __name__ == "__main__":
    unittest.main()
