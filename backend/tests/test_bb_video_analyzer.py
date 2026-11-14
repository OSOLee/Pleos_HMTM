"""MTM 분석기 (src/blackbox/video_analyzer.py, video_lib/) — 무거운 단계(탐지·추적)는 대신 돌려 시험한다

진짜 영상·가중치로 하는 시험은 tests/test_blackbox_contract.py (HMTM_BB_CONTRACT_ANALYZER=mtm).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from bb_common import make_video
from src.blackbox import analyzer, video_analyzer as mtm
from src.blackbox.video_lib import bb_output


def _write(d, name, obj):
    with open(os.path.join(d, name), "w", encoding="utf-8") as fp:
        json.dump(obj, fp)


def fake_track(video, out_dir, **kw):
    """track_video.run 대신: 탐지 없이 빈 추적 결과만 남긴다"""
    _write(out_dir, "tracks.json", {"fps": 5.0, "tracks": {}})
    if kw.get("progress"):
        kw["progress"](50, 100)        # 실제 track_video.run처럼 (처리한 프레임 수, 전체 프레임 수) 두 인자로 부른다
        kw["progress"](100, 100)


def fake_ego(video, out_dir, **kw):
    frames = [{"frame": i, "mag": 1.0, "tx": 0.0, "ty": 0.0, "scale": 0.0, "n": 50, "ok": True} for i in range(60)]
    segs = [{"state": "moving", "from": 0, "to": 40}, {"state": "stopped", "from": 41, "to": 59}]
    _write(out_dir, "ego_motion.json", {"params": {}, "frames": frames,
                                        "summary": {"frames": 60, "fps": 5.0, "segments": segs, "jolt_frames": [38]}})


class Ready(unittest.TestCase):
    def test_not_ready_without_model(self):
        with mock.patch.object(mtm, "BB_MODEL", "models/없는모델.pt"):
            with mock.patch.dict(os.environ, {analyzer.ENV: "mtm"}):
                with self.assertRaises(analyzer.AnalyzerNotReady) as e:
                    analyzer.get_analyzer()
        self.assertIn("탐지 모델", e.exception.message)

    def test_ready_with_model_file(self):
        with tempfile.NamedTemporaryFile(suffix=".pt") as f, mock.patch.object(mtm, "BB_MODEL", f.name), \
                mock.patch.dict(os.environ, {"HMTM_BB_MODEL_CHECK": "0"}):   # 빈 대역 파일이라 가중치 목록 대조는 끔 (test_bb_models)
            an = analyzer.get_analyzer("mtm")
        self.assertEqual((an.name, an.version), ("mtm", mtm.VERSION))


class Analyze(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hmtm_mtm_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.video = make_video(os.path.join(self.tmp, "v.mp4"), seconds=12.0, fps=5.0)

    def run_analyze(self, **kw):
        from src.analyze import ego_motion, track_video
        with mock.patch.object(track_video, "run", fake_track), mock.patch.object(ego_motion, "run", fake_ego), \
                mock.patch.object(mtm.os.path, "exists", wraps=os.path.exists):
            return mtm.analyze(self.video, None, **kw)

    def test_output_passes_validation(self):
        out = self.run_analyze()
        checked = analyzer.validate_output(out)
        self.assertEqual(checked["status"], "ok", checked.get("message"))
        self.assertEqual(set(out["facts"]["parties"]), {"ego", "other"})
        self.assertEqual(out["schema_version"], "bb-0.2")

    def test_unfound_impact_becomes_no_collision(self):
        """촬영 차가 처음부터 서 있어 사고 순간을 못 찾으면 no_collision + collision.t null, 영상 끝은 후보로만, 상대 값은 guess"""
        from src.analyze import ego_motion, track_video

        def still_ego(video, out_dir, **kw):
            frames = [{"frame": i, "mag": 0.0, "tx": 0.0, "ty": 0.0, "scale": 0.0, "n": 50, "ok": True} for i in range(60)]
            _write(out_dir, "ego_motion.json", {"params": {}, "frames": frames, "summary": {
                "frames": 60, "fps": 5.0, "segments": [{"state": "stopped", "from": 0, "to": 59}], "jolt_frames": []}})
        with mock.patch.object(track_video, "run", fake_track), mock.patch.object(ego_motion, "run", still_ego):
            out = mtm.analyze(self.video, None)
        checked = analyzer.validate_output(out)
        self.assertEqual(checked["status"], "no_collision", checked.get("message"))
        self.assertIsNone(out["facts"]["collision"]["t"])
        cand = out["hints"]["collision_candidates"]
        self.assertEqual((len(cand), cand[0]["source"], cand[0]["reason"]), (1, "video_end", "never_moving"))
        self.assertGreater(cand[0]["t"], 0)
        other = out["facts"]["parties"]["other"]
        for key in ("entry_from", "movement", "lead_order"):
            self.assertIsNone(other[key]["value"], key)
            self.assertIsNotNone(other[key]["guess"], key)

    def test_track_uses_v3_defaults_and_restores_globals(self):
        """탐지·추적은 기본 v3·960·0.15로 부르고, 끝나면 track_video의 전역을 원래대로 돌려 놓는다"""
        from src.analyze import ego_motion, track_video
        seen = {}

        def spy_track(video, out_dir, **kw):
            seen.update(model=track_video.MODEL, imgsz=track_video.IMGSZ, conf=track_video.CONF, helper=track_video.HELPER_MODEL)
            fake_track(video, out_dir, **kw)
        before = (track_video.MODEL, track_video.IMGSZ, track_video.CONF, track_video.HELPER_MODEL)
        with mock.patch.object(track_video, "run", spy_track), mock.patch.object(ego_motion, "run", fake_ego):
            mtm.analyze(self.video, None)
        self.assertEqual(seen, {"model": "models/bb_v3.pt", "imgsz": 960, "conf": 0.15, "helper": ""})
        self.assertEqual((track_video.MODEL, track_video.IMGSZ, track_video.CONF, track_video.HELPER_MODEL), before)

    def test_kind_signal_runs_at_960_even_when_tracking_is_640(self):
        """상대 종류 신호(bb_kind)는 사고 직전만 보므로 기본 960·0.15로 부르고, 환경변수로 바꿀 수 있다"""
        from src.analyze import ego_motion, track_video
        from src.blackbox.video_lib import bb_kind
        calls = []
        real = bb_kind.run

        def spy(case_dir, video, **kw):
            calls.append(kw)
            return real(case_dir, video, **kw)
        with mock.patch.object(track_video, "run", fake_track), mock.patch.object(ego_motion, "run", fake_ego), \
                mock.patch.object(bb_kind, "run", spy):
            mtm.analyze(self.video, None)
            with mock.patch.object(mtm, "KIND_IMGSZ", 640), mock.patch.object(mtm, "KIND_CONF", 0.1):
                mtm.analyze(self.video, None)
        self.assertEqual([(c["imgsz"], c["conf"]) for c in calls], [(960, 0.15), (640, 0.1)])

    def test_collision_t_picks_the_impact_second(self):
        """사용자가 고른 순간(초)을 주면 그 순간이 사고 순간이 된다. 안 주면 자동(위 시험들)"""
        out = self.run_analyze(collision_t=2.0)
        self.assertEqual(out["status"], "ok")
        col = out["facts"]["collision"]
        self.assertEqual((col["t"], col["frame"]), (2.0, 10))          # 5fps라 2.0초 = 10프레임 (자동은 38프레임 근처)
        self.assertNotEqual(self.run_analyze()["facts"]["collision"]["frame"], 10)

    def test_collision_t_works_when_automatic_finds_nothing(self):
        """자동으로 못 찾는 영상(처음부터 서 있음)도 사용자가 고르면 no_collision이 아니라 그 순간으로 분석된다"""
        from src.analyze import ego_motion, track_video

        def still_ego(video, out_dir, **kw):
            frames = [{"frame": i, "mag": 0.0, "tx": 0.0, "ty": 0.0, "scale": 0.0, "n": 50, "ok": True} for i in range(60)]
            _write(out_dir, "ego_motion.json", {"params": {}, "frames": frames, "summary": {
                "frames": 60, "fps": 5.0, "segments": [{"state": "stopped", "from": 0, "to": 59}], "jolt_frames": []}})
        with mock.patch.object(track_video, "run", fake_track), mock.patch.object(ego_motion, "run", still_ego):
            self.assertEqual(mtm.analyze(self.video, None)["status"], "no_collision")
            out = mtm.analyze(self.video, None, collision_t=3.0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["facts"]["collision"]["frame"], 15)

    def test_crosswalk_model_gets_conf_015_by_default(self):
        """횡단보도 모델에 conf를 넘긴다 (안 넘기면 ultralytics 기본 0.25로 돌았음). 환경변수·설정으로 바꿀 수 있다"""
        from src.analyze import ego_motion, track_video
        from src.blackbox.video_lib import bb_crosswalk
        confs = []

        def spy(case_dir, video, **kw):
            confs.append(kw.get("conf"))
        with mock.patch.object(track_video, "run", fake_track), mock.patch.object(ego_motion, "run", fake_ego), \
                mock.patch.object(bb_crosswalk, "run", spy):
            mtm.analyze(self.video, None)
            with mock.patch.object(mtm, "CROSSWALK_CONF", 0.3):
                mtm.analyze(self.video, None)
        self.assertEqual(confs, [0.15, 0.3])

    def test_found_impact_stays_ok(self):
        """사고 순간을 찾은 영상은 그대로 ok (위 변환이 걸리지 않음)"""
        out = self.run_analyze()
        self.assertEqual(out["status"], "ok")
        self.assertIsNotNone(out["facts"]["collision"]["t"])
        self.assertNotIn("collision_candidates", out["hints"])

    def test_progress_reaches_100_and_never_goes_back(self):
        seen = []
        self.run_analyze(progress=seen.append)
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))

    def test_work_dir_kept_and_temp_removed(self):
        own = os.path.join(self.tmp, "work")
        self.run_analyze(work_dir=own)
        self.assertTrue(os.path.exists(os.path.join(own, "bb_partner.json")))
        before = set(os.listdir(tempfile.gettempdir()))
        self.run_analyze()
        leaked = [n for n in set(os.listdir(tempfile.gettempdir())) - before if n.startswith("hmtm_mtm_") and "test" not in n]
        self.assertEqual(leaked, [])

    def test_unreadable_video_is_failed_status(self):
        bad = os.path.join(self.tmp, "x.mp4")
        with open(bad, "wb") as f:
            f.write(b"not a video")
        out = mtm.analyze(bad)
        self.assertEqual((out["status"], out["reason"]), ("failed", "video_unreadable"))
        self.assertEqual(analyzer.validate_output(out)["status"], "failed")

    def test_run_wraps_via_analyzer(self):
        """analyzer.run이 mtm을 골라 돌리고 이름·판을 박는지 (분석기 쪽은 대역)"""
        with tempfile.NamedTemporaryFile(suffix=".pt") as f, mock.patch.object(mtm, "BB_MODEL", f.name), \
                mock.patch.dict(os.environ, {"HMTM_BB_MODEL_CHECK": "0"}):   # 빈 대역 파일이라 가중치 목록 대조는 끔 (test_bb_models)
            from src.analyze import ego_motion, track_video
            with mock.patch.object(track_video, "run", fake_track), mock.patch.object(ego_motion, "run", fake_ego):
                out = analyzer.run(self.video, name="mtm")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["analyzer"], {"name": "mtm", "version": mtm.VERSION})


class Imports(unittest.TestCase):
    def test_lib_uses_only_blackbox_and_stdlib_paths(self):
        """복사한 분석 코드는 src.analyze 대신 video_lib를 불러야 한다 (src.analyze는 MTM 영역)"""
        lib = os.path.join(ROOT, "src", "blackbox", "video_lib")
        for name in os.listdir(lib):
            if name.endswith(".py"):
                text = open(os.path.join(lib, name), encoding="utf-8").read()
                self.assertNotIn("from src.analyze", text, name)

    def test_output_module_importable(self):
        self.assertTrue(callable(bb_output.to_bb02))


if __name__ == "__main__":
    unittest.main()
