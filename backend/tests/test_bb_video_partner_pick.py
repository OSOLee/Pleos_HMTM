"""(MTM tests/test_bb_partner_pick.py 복사본, import만 video_lib로)"""
"""사고 순간을 사용자가 골랐을 때(collision_t, 초) bb_partner — 자동으로 찾는 결과는 그대로"""
import json
import os
import shutil
import tempfile
import unittest

from src.blackbox.video_lib import bb_partner

FPS, N = 30.0, 300


def _rec(f, x, w, h, cls="car"):
    return {"frame": f, "cls": cls, "bbox": [x, 0.4, w, h]}


class PickTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="bb_pick_")
        self.addCleanup(shutil.rmtree, self.d, True)
        ego = {"summary": {"fps": FPS, "frames": N, "jolt_frames": [200],
                           "segments": [{"state": "moving", "from": 0, "to": 195}, {"state": "stopped", "from": 195, "to": N - 1}]}}
        # 상대 차: 프레임 90 근처(3초)에 크게 다가오는 차 / 자동 충격(200) 근처에는 작은 차
        tracks = {"7": [_rec(f, 0.4, 0.05 + 0.002 * (f - 60), 0.05 + 0.002 * (f - 60)) for f in range(60, 91, 3)],
                  "9": [_rec(f, 0.2, 0.05, 0.05) for f in range(170, 201, 3)]}
        for n, o in (("ego_motion.json", ego), ("tracks.json", {"tracks": tracks})):
            with open(os.path.join(self.d, n), "w", encoding="utf-8") as fp:
                json.dump(o, fp)

    def test_without_pick_is_automatic_as_before(self):
        out = bb_partner.run(self.d)
        self.assertEqual((out["impact_frame"], out["impact_source"]), (200, "jolt_near_stop"))
        self.assertEqual(out["partner"]["id"], "9")

    def test_pick_seconds_becomes_impact_frame(self):
        out = bb_partner.run(self.d, collision_t=3.0)
        self.assertEqual((out["impact_frame"], out["impact_source"]), (90, "user_pick"))
        self.assertEqual(out["partner"]["id"], "7")                     # 고른 순간 직전에 다가온 차를 상대로
        with open(os.path.join(self.d, "bb_partner.json"), encoding="utf-8") as fp:
            self.assertEqual(json.load(fp)["impact_frame"], 90)

    def test_pick_zero_is_a_valid_pick(self):
        self.assertEqual(bb_partner.run(self.d, collision_t=0)["impact_frame"], 0)

    def test_pick_past_the_end_is_clamped_to_last_frame(self):
        self.assertEqual(bb_partner.run(self.d, collision_t=999)["impact_frame"], N - 1)

    def test_pick_overrides_even_when_automatic_finds_nothing(self):
        with open(os.path.join(self.d, "ego_motion.json"), "w", encoding="utf-8") as fp:
            json.dump({"summary": {"fps": FPS, "frames": N, "jolt_frames": [],
                                   "segments": [{"state": "stopped", "from": 0, "to": N - 1}]}}, fp)
        self.assertIsNone(bb_partner.run(self.d)["impact_frame"])
        self.assertEqual(bb_partner.run(self.d, collision_t=3.0)["impact_frame"], 90)


if __name__ == "__main__":
    unittest.main()
