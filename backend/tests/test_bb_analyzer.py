"""블랙박스 분석기 빈자리 시험 (docs/design-blackbox.md 1절)

  python -m pytest tests/test_bb_analyzer.py

분석기 고르기(HMTM_BB_ANALYZER), mtm 준비 안 됨, 출력 검사(validate_output), 분석기 이름·판.
"""
import copy
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from src.blackbox import analyzer

OK = {
    "schema_version": "bb-0.1", "analyzer": {"name": "t", "version": "1"}, "status": "ok",
    "reason": None, "message": None,
    "video": {"duration_s": 10.0, "fps": 10.0, "frames": 100, "width": 64, "height": 48},
    "clock": {"osd_start_ms": None},
    "facts": {"schema_version": "0.3",
              "collision": {"a": "ego", "b": "other", "t": 6.0, "frame": 60, "zone": "intersection"},
              "parties": {"ego": {"movement": {"value": "right_turn", "source": "model"}},
                          "other": {"cls": {"value": "car", "source": "model"},
                                    "entry_from": {"value": None, "source": "model", "guess": "west"}}},
              "road": {"signal_present": {"value": None, "source": "model", "guess": False}}},
    "ego_motion": {"t": [], "speed_proxy": [], "jolt_t": [6.0]}, "hints": {},
}


def broken(**changes):
    out = copy.deepcopy(OK)
    for path, v in changes.items():
        cur = out
        keys = path.split("__")
        for k in keys[:-1]:
            cur = cur[k]
        if v is KeyError:
            del cur[keys[-1]]
        else:
            cur[keys[-1]] = v
    return out


class Validate(unittest.TestCase):
    def test_ok_passes(self):
        self.assertEqual(analyzer.validate_output(OK), OK)

    def test_bad_outputs_become_failed(self):
        for case in [broken(schema_version="bb-0.0"), broken(status="weird"), broken(analyzer=KeyError),
                     broken(video=None), broken(facts=KeyError),
                     broken(facts__collision__a="1"), broken(facts__collision__t=None),
                     broken(facts__collision__t=99.0),
                     broken(facts__parties={"ego": {}}),
                     broken(facts__parties__ego__movement="right_turn"),            # 값 객체가 아님
                     broken(facts__parties__ego__movement={"value": "fly", "source": "model"}),
                     broken(facts__parties__other__entry_from={"value": "up", "source": "model"}),
                     broken(facts__parties__ego__entry_from={"value": "south", "source": "model"}),
                     broken(facts__road__signal_present={"value": "yes", "source": "model"}),
                     broken(facts__parties__ego__movement={"value": "straight", "source": "model", "confidence": 2}),
                     "not a dict"]:
            out = analyzer.validate_output(case)
            self.assertEqual((out["status"], out["reason"]), ("failed", "analyzer_output_invalid"), case)
            self.assertTrue(out["message"])

    def test_no_collision_and_unsupported(self):
        nc = broken(status="no_collision", facts__collision__t=None, facts__collision__frame=None)
        self.assertEqual(analyzer.validate_output(nc)["status"], "no_collision")
        self.assertEqual(analyzer.validate_output(broken(status="no_collision"))["reason"], "analyzer_output_invalid")
        un = broken(status="unsupported", reason="not_blackbox", facts=None)
        self.assertEqual(analyzer.validate_output(un)["status"], "unsupported")
        self.assertEqual(analyzer.validate_output(broken(status="unsupported"))["reason"], "analyzer_output_invalid")


def _v(x, **kw):
    return {"value": x, "source": "model", **kw}


PED = {"cls": _v("person", confidence=0.93), "ped_place": _v("near_crosswalk"),
       "dist_from_crosswalk_m": _v(20, bin="10_30m", measured=False, confidence=0.7),
       "ped_signal_at_start": _v(None, guess="flashing_green"), "ped_signal_at_impact": _v("red"),
       "ped_activity": _v("crossing"), "ped_factors": _v(["group", "sudden_entry"]), "walk_manner": _v("zigzag"),
       "ped_posture": _v("standing"), "roadway_walk_position": _v("edge_1m")}
BIKE = {"cls": _v("bicycle"), "on_bike_crossing": _v(True), "crossing_road": _v(None, guess=True),
        "bike_lane_type": _v("dedicated_lane"), "user_factors": _v(["no_helmet"]),
        "intersection_entry_speed_kmh": _v(18.5), "approached_right_edge": _v(False)}


class Bb02(unittest.TestCase):
    """bb-0.2 (8.3.1~8.3.3): 보행자·자전거 항목, 신호 이름은 판정 엔진 이름, bb-0.1도 받음"""

    def test_versions(self):
        self.assertEqual(analyzer.SCHEMA_VERSION, "bb-0.2")
        for ver in ("bb-0.1", "bb-0.2"):
            self.assertEqual(analyzer.validate_output(broken(schema_version=ver))["status"], "ok", ver)

    def test_ped_and_bike_fields_pass(self):
        road = {"crosswalk_signal": _v(False), "sidewalk_separated": _v(True), "crossing_prohibition": _v("sign"),
                "protection_zone": _v("child"), "bad_weather": _v(False), "lanes_two_plus": _v(True),
                "dashed_bike_lane_border": _v(None, guess=False)}
        ego = {"movement": _v("straight"), "impact_after_intersection": _v(True), "passed_crosswalk": _v(False),
               "right_turn_signal": _v("none"), "riding_on_crosswalk": _v(False)}
        for other in (PED, BIKE):
            out = broken(schema_version="bb-0.2", facts__parties={"ego": ego, "other": other}, facts__road=road)
            self.assertEqual(analyzer.validate_output(out)["status"], "ok", other["cls"])

    def test_bad_ped_bike_values(self):
        bad = [("ped_place", _v("on_crosswalk")), ("ped_signal_at_impact", _v("green_flashing")),
               ("dist_from_crosswalk_m", _v(-1)), ("dist_from_crosswalk_m", _v("20m")),
               ("dist_from_crosswalk_m", _v(20, bin="near")), ("dist_from_crosswalk_m", _v(20, measured="yes")),
               ("ped_factors", _v("group")), ("ped_factors", _v(["running"])), ("user_factors", _v([1])),
               ("bike_lane_type", _v("lane")), ("on_bike_crossing", _v("yes")), ("cls", _v("pedestrian"))]
        for k, v in bad:
            out = broken(**{f"facts__parties__other__{k}": v})
            self.assertEqual(analyzer.validate_output(out)["reason"], "analyzer_output_invalid", (k, v))
        out = broken(facts__road__crossing_prohibition=_v("fence"))
        self.assertEqual(analyzer.validate_output(out)["reason"], "analyzer_output_invalid")

    def test_signal_names_are_engine_names(self):
        """내 차 신호는 판정 엔진 이름(green_arrow, none). 옛 이름(green_left, red_left, off)은 막음"""
        from src.analyze.build_facts import SIGNALS
        self.assertEqual(set(analyzer.SIGNALS), set(SIGNALS))
        for sig in SIGNALS:
            out = broken(facts__parties__ego__signal_at_entry=_v(sig))
            self.assertEqual(analyzer.validate_output(out)["status"], "ok", sig)
        for sig in ("green_left", "red_left", "off"):
            out = broken(facts__parties__ego__signal_at_entry=_v(sig))
            self.assertEqual(analyzer.validate_output(out)["reason"], "analyzer_output_invalid", sig)


class Choose(unittest.TestCase):
    def test_env_selects_mtm_not_ready(self):
        with mock.patch.dict(os.environ, {analyzer.ENV: "MTM"}):
            with self.assertRaises(analyzer.AnalyzerNotReady) as e:
                analyzer.get_analyzer()
            self.assertIn("준비", e.exception.message)
        with self.assertRaises(analyzer.AnalyzerNotReady):
            analyzer.get_analyzer("nope")

    def test_run_mtm_not_ready_is_failed(self):
        out = analyzer.run("x.mp4", name="mtm")
        self.assertEqual((out["status"], out["reason"]), ("failed", "analyzer_not_ready"))
        self.assertEqual(out["analyzer"]["name"], "mtm")

    def test_run_stamps_name_and_catches_errors(self):
        class Good:
            name, version = "good", "9.9"

            def analyze(self, path, start_time=None, **kw):
                return broken(analyzer={"name": "other", "version": "0"})

        class Bad(Good):
            def analyze(self, path, start_time=None, **kw):
                raise RuntimeError("boom")

        with mock.patch.object(analyzer, "get_analyzer", lambda name=None: Good()):
            out = analyzer.run("x.mp4")
        self.assertEqual((out["status"], out["analyzer"]), ("ok", {"name": "good", "version": "9.9"}))
        with mock.patch.object(analyzer, "get_analyzer", lambda name=None: Bad()):
            out = analyzer.run("x.mp4")
        self.assertEqual((out["status"], out["reason"], out["analyzer"]["name"]), ("failed", "server_error", "good"))


if __name__ == "__main__":
    unittest.main()
