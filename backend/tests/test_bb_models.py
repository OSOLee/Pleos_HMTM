"""가중치 목록 검사 (src/blackbox/models.py, docs/design-blackbox.md 1.6)

  python -m pytest tests/test_bb_models.py

가중치 파일은 git에 없으므로 임시 폴더에 작은 대역 파일과 그 sha256을 적은 목록을 만들어 시험한다.
- 등록된 항목: 파일이 있고 크기·sha256이 같으면 ok, 없으면 missing, 다르면 mismatch → MtmAnalyzer는 AnalyzerNotReady
- 등록 안 된 항목(version·sha256 null): unregistered → 분석하는 동안 그 모델 경로를 없는 파일로 바꿔 그 단계만 건너뜀
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from src.blackbox import analyzer, models
from src.blackbox import video_analyzer as mtm


def entry(file, data=None, version="v1"):
    if data is None:
        return {"file": file, "role": "x", "version": None, "sha256": None, "size_bytes": None, "source": "",
                "classes": None, "imgsz": None, "conf": None}
    return {"file": file, "role": "x", "version": version, "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data), "source": "", "classes": [], "imgsz": 960, "conf": 0.15}


class Base(unittest.TestCase):
    DATA = b"weights-v3"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hmtm_models_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.det = os.path.join(self.tmp, "bb_v3.pt")
        with open(self.det, "wb") as f:
            f.write(self.DATA)
        self.list_path = self.write_list({"detector": entry("bb_v3.pt", self.DATA),
                                          "kind": entry("bb_v3.pt", self.DATA),
                                          "scene": entry("scene_cls.pt"), "crosswalk": entry("crosswalk.pt")})

    def write_list(self, m, schema=models.SCHEMA):
        p = os.path.join(self.tmp, "models.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"schema": schema, "models": m}, f)
        return p

    def paths(self, **kw):
        return {"detector": self.det, "kind": self.det, "scene": os.path.join(self.tmp, "scene_cls.pt"),
                "crosswalk": os.path.join(self.tmp, "crosswalk.pt"), **kw}


class Check(Base):
    def test_ok_and_unregistered(self):
        r = models.check(self.paths(), self.list_path)
        self.assertEqual({k: v["status"] for k, v in r.items()},
                         {"detector": "ok", "kind": "ok", "scene": "unregistered", "crosswalk": "unregistered"})
        self.assertEqual(models.problems(r), [])

    def test_unregistered_even_if_file_exists(self):
        """목록에 sha256이 없으면 파일이 있어도 쓰지 않음 (검증 안 된 가중치)"""
        open(os.path.join(self.tmp, "scene_cls.pt"), "wb").write(b"x")
        self.assertEqual(models.check(self.paths(), self.list_path)["scene"]["status"], "unregistered")

    def test_missing(self):
        r = models.check(self.paths(detector=os.path.join(self.tmp, "nope.pt")), self.list_path)
        self.assertEqual(r["detector"]["status"], "missing")
        self.assertTrue(any("탐지 모델" in m for m in models.problems(r)))

    def test_size_and_hash_mismatch(self):
        other = os.path.join(self.tmp, "other.pt")
        open(other, "wb").write(b"weights-v2")                    # 크기는 같고 내용이 다름
        r = models.check(self.paths(detector=other), self.list_path)
        self.assertEqual(r["detector"]["status"], "mismatch")
        self.assertIn("sha256", r["detector"]["message"])
        open(other, "wb").write(b"short")
        r = models.check(self.paths(detector=other), self.list_path)
        self.assertEqual(r["detector"]["status"], "mismatch")
        self.assertIn("크기", r["detector"]["message"])

    def test_registered_optional_missing_is_problem(self):
        """등록된 모델(예: 나중에 scene이 전달돼 목록에 sha256이 들어감)은 없으면 준비 안 됨"""
        lp = self.write_list({"detector": entry("bb_v3.pt", self.DATA), "kind": entry("bb_v3.pt", self.DATA),
                              "scene": entry("scene_cls.pt", b"scene"), "crosswalk": entry("crosswalk.pt")})
        r = models.check(self.paths(), lp)
        self.assertEqual(r["scene"]["status"], "missing")
        self.assertEqual(len(models.problems(r)), 1)

    def test_unregistered_detector_is_problem(self):
        lp = self.write_list({"detector": entry("bb_v3.pt"), "kind": entry("bb_v3.pt"),
                              "scene": entry("scene_cls.pt"), "crosswalk": entry("crosswalk.pt")})
        self.assertTrue(models.problems(models.check(self.paths(), lp)))

    def test_bad_list(self):
        with self.assertRaises(models.ListInvalid):
            models.check(self.paths(), self.write_list({}, schema="other"))
        with self.assertRaises(models.ListInvalid):
            models.check(self.paths(), os.path.join(self.tmp, "none.json"))

    def test_real_list_shape(self):
        """저장소의 models.json: 탐지·scene·crosswalk 모두 등록돼 있음 (등록 여부는 목록의 version·sha256만 보므로 가중치 파일이 없어도 통과)"""
        d = models.load()
        self.assertTrue(models.registered(d["models"]["detector"]))
        self.assertTrue(models.registered(d["models"]["scene"]))
        self.assertTrue(models.registered(d["models"]["crosswalk"]))


class Analyzer(Base):
    def make(self):
        with mock.patch.object(models, "LIST_PATH", self.list_path), mock.patch.object(mtm, "BB_MODEL", self.det), \
                mock.patch.object(mtm, "KIND_MODEL", self.det), mock.patch.dict(os.environ, {models.CHECK_ENV: "1"}):
            return analyzer.get_analyzer("mtm")

    def test_ready_and_skips_unregistered_stages(self):
        an = self.make()
        self.assertEqual(set(an.skip), {"scene", "crosswalk"})
        seen = {}

        def fake_analyze(video_path, start_time=None, **kw):
            seen.update(scene=mtm.SCENE_MODEL, crosswalk=mtm.CROSSWALK_MODEL)
            return {"status": "failed"}

        before = (mtm.SCENE_MODEL, mtm.CROSSWALK_MODEL)
        with mock.patch.object(mtm, "analyze", fake_analyze):
            an.analyze("x.mp4")
        self.assertEqual(seen, {"scene": models.SKIPPED_PATH, "crosswalk": models.SKIPPED_PATH})
        self.assertFalse(os.path.exists(models.SKIPPED_PATH))     # 없는 파일 → bb_scene·bb_crosswalk가 건너뜀
        self.assertEqual((mtm.SCENE_MODEL, mtm.CROSSWALK_MODEL), before)   # 끝나면 되돌림

    def test_mismatch_is_not_ready(self):
        open(self.det, "wb").write(b"weights-xx")
        with self.assertRaises(analyzer.AnalyzerNotReady) as e:
            self.make()
        self.assertIn("sha256", e.exception.message)

    def test_run_not_ready_is_failed(self):
        os.remove(self.det)
        with mock.patch.object(models, "LIST_PATH", self.list_path), mock.patch.object(mtm, "BB_MODEL", self.det):
            out = analyzer.run("x.mp4", name="mtm")
        self.assertEqual((out["status"], out["reason"]), ("failed", "analyzer_not_ready"))

    def test_one_analysis_at_a_time(self):
        """한 프로세스에서 MTM 분석은 겹치지 않음 (track_video 전역 바꿔치기, 3.4)"""
        import threading
        import time
        an = self.make()
        active, peak = [0], [0]
        lock = threading.Lock()

        def slow(video_path, start_time=None, **kw):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return {}

        with mock.patch.object(mtm, "analyze", slow):
            ts = [threading.Thread(target=an.analyze, args=("x.mp4",)) for _ in range(4)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(peak[0], 1)


if __name__ == "__main__":
    unittest.main()
