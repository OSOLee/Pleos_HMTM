"""블랙박스 분석기 계약 시험 (docs/design-blackbox.md 1.4·2.3·8절, bb-flow 2부 5단계)

  python -m pytest tests/test_blackbox_contract.py

분석기 출력(bb-0.2)이 약속한 모양이면 HMTM의 나머지 흐름(시각 맞추기 → 합치기 → 질문 → 판정)이 돈다는 것을 확인한다.
진짜 분석기(MTM)를 끼우면 이 시험만 통과시키면 된다:

  $env:HMTM_BB_CONTRACT_ANALYZER="mtm"
  $env:HMTM_BB_CONTRACT_VIDEOS="data\\videos\\bb\\a.mp4;data\\videos\\bb\\b.mp4"   # 짧은 블랙박스 영상 (git 제외)
  python -m pytest tests/test_blackbox_contract.py

기본(fake)은 모든 가짜 분석기 시나리오를 테스트 안에서 만든 짧은 영상으로 돌린다. analyzer_broken은 일부러 틀린
출력이라 "검사가 막는지"를 본다.

시험하는 것
  Output    분석기가 낸 그대로가 validate_output을 통과 (HMTM이 고쳐 주지 않음), 상태별 필수 칸, 프레임·시각이 맞음,
            bb-0.2면 상대 종류(cls)에 확신도(confidence)가 꼭 있음 (8.3.1)
  Flow      status ok면: 판정 엔진 변환기(judge/adapter.to_engine_facts)가 읽음, 차량 기록 없이·있을 때 adapter.build가
            질문·판정을 냄, ego_motion이 있으면 시각 맞추기(fine_match)가 예외 없이 돎
  Rejects   약속을 어긴 출력(빠진 칸, 틀린 값, 당사자 id 등)은 validate_output이 failed / analyzer_output_invalid로 막음.
            깨뜨릴 원본은 늘 가짜 분석기 출력이라(analyzer.run(name="fake")) 환경변수 분석기와 관계없이 돈다
"""
import copy
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from bb_common import make_video
from judge import adapter as judge_adapter
from src.blackbox import adapter, analyzer, fake, sync

ANALYZER = os.environ.get("HMTM_BB_CONTRACT_ANALYZER", "fake")
VIDEOS = [p for p in os.environ.get("HMTM_BB_CONTRACT_VIDEOS", "").split(";") if p.strip()]
BROKEN = {"analyzer_broken"}            # 가짜 분석기의 일부러 틀린 시나리오
S0 = 1_762_666_212_000
START = [{"source": "filename", "start_ms": S0}]


def outputs(tmp):
    """(이름, 분석기 원래 출력) 목록. 분석기를 쓸 수 없으면 SkipTest"""
    try:
        an = analyzer.get_analyzer(ANALYZER)
    except analyzer.AnalyzerNotReady as e:
        raise unittest.SkipTest(f"분석기 {ANALYZER}를 쓸 수 없어요: {e.message}")
    if an.name == fake.NAME:
        video = make_video(os.path.join(tmp, "20261109_143012_F.mp4"), seconds=12.0, fps=5.0)
        return [(n, an.analyze(video, None, work_dir=tmp, scenario=n)) for n in fake.scenario_names()]
    if not VIDEOS:
        raise unittest.SkipTest("HMTM_BB_CONTRACT_VIDEOS에 시험 영상 경로를 넣어 주세요")
    out = []
    for p in VIDEOS:
        wd = tempfile.mkdtemp(dir=tmp)
        out.append((os.path.basename(p), an.analyze(p, None, work_dir=wd)))
    return out


def flat_vehicle(t_ms, before=20_000, after=5_000):
    s = [{"t": t, "speedKmh": 30.0, "gear": "D", "turnSignal": "OFF", "brake": False}
         for t in range(t_ms - before, t_ms + after + 1, 100)]
    return {"range": {"from": s[0]["t"], "to": s[-1]["t"]}, "samples": s, "vehicle_cls": "car", "client": {}}


class ContractBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hmtm_bbcontract_")
        try:
            cls.outs = outputs(cls.tmp)
        except unittest.SkipTest:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def good(self):
        return [(n, o) for n, o in self.outs if n not in BROKEN]


class Output(ContractBase):
    def test_raw_output_passes_validation(self):
        """분석기가 낸 그대로가 검사를 통과해야 함 (HMTM이 고치지 않음)"""
        for name, out in self.good():
            with self.subTest(name):
                try:
                    analyzer._check(out)
                except analyzer.OutputInvalid as e:
                    self.fail(f"{name}: {e}")
                self.assertEqual(analyzer.validate_output(out), out)

    def test_status_fields(self):
        for name, out in self.good():
            with self.subTest(name):
                self.assertIn(out["status"], analyzer.STATUSES)
                if out["status"] != "ok":
                    self.assertTrue(out.get("reason"), name)
                    self.assertIsInstance(out.get("message"), str, name)
                    self.assertTrue(out["message"], name)
                if out["status"] == "no_collision":
                    self.assertIsNone(out["facts"]["collision"]["t"])

    def test_frame_matches_time(self):
        """collision.frame ≈ t × fps (프레임과 초를 함께 기록)"""
        for name, out in self.good():
            if out["status"] != "ok":
                continue
            with self.subTest(name):
                col, fps = out["facts"]["collision"], out["video"]["fps"]
                if col.get("frame") is not None:
                    self.assertLessEqual(abs(col["frame"] - col["t"] * fps), 1.0, name)

    def test_cls_has_confidence(self):
        """bb-0.2: 상대 종류(cls)는 사고 장을 정하므로 확신도가 꼭 있어야 함 (8.3.1). status ok면 cls도 꼭 있어야 함"""
        for name, out in self.good():
            if out.get("schema_version") != analyzer.SCHEMA_VERSION or out["status"] not in ("ok", "no_collision"):
                continue
            with self.subTest(name):
                cls = out["facts"]["parties"]["other"].get("cls")
                if cls is None and out["status"] == "no_collision":
                    continue
                self.assertIsInstance(cls, dict, f"{name}: parties.other.cls가 없어요")
                c = cls.get("confidence")
                self.assertTrue(isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 1,
                                f"{name}: parties.other.cls.confidence(0~1)가 없어요: {cls}")

    def test_motion_shape(self):
        for name, out in self.good():
            em = out.get("ego_motion")
            if not em or not em.get("t"):
                continue
            with self.subTest(name):
                self.assertEqual(len(em["speed_proxy"]), len(em["t"]))
                step = (em["t"][-1] - em["t"][0]) / max(1, len(em["t"]) - 1)
                self.assertLessEqual(step, 0.5, "ego_motion 간격은 0.1초 안팎 (1.3 F)")

    def test_broken_is_rejected(self):
        for name, out in self.outs:
            if name in BROKEN:
                v = analyzer.validate_output(out)
                self.assertEqual((v["status"], v["reason"]), ("failed", "analyzer_output_invalid"), name)


class Flow(ContractBase):
    def test_engine_adapter_reads_facts(self):
        for name, out in self.good():
            if out["status"] != "ok":
                continue
            with self.subTest(name):
                judge_adapter.to_engine_facts(copy.deepcopy(out["facts"]))

    def test_merge_questions_judge(self):
        """차량 기록 없이, 그리고 대충 맞는 차량 기록과 함께 질문·판정까지 돎"""
        for name, raw in self.good():
            out = analyzer.validate_output(raw)
            if out["status"] != "ok":
                continue
            with self.subTest(name):
                t = out["facts"]["collision"]["t"]
                s = sync.sync(START, t, None)
                view = adapter.build(out, None, s, {})["view"]
                self.assertIn(view["status"], ("needs_answers", "done"))
                self.assertIn(view["result"]["status"], ("ok", "no_rule"))
                for f, a in view["answers"].items():
                    self.assertTrue(a.get("evidence"), f)
                self.assertEqual(view["remaining_count"], len(view["remaining"]))
                veh = flat_vehicle(S0 + int(round(t * 1000)))
                s = sync.sync(START, t, veh["range"], samples=veh["samples"], ego_motion=out.get("ego_motion"),
                              duration_s=out["video"]["duration_s"])
                self.assertIn(s["grade"], ("fine", "coarse", "none"))
                view = adapter.build(out, veh, s, {})["view"]
                self.assertEqual(view["answers"]["parties.ego.cls"]["source"], "vehicle")

    def test_fine_match_runs(self):
        for name, raw in self.good():
            out = analyzer.validate_output(raw)
            if out["status"] != "ok":
                continue
            with self.subTest(name):
                t = out["facts"]["collision"]["t"]
                veh = flat_vehicle(S0 + int(round(t * 1000)))
                r = sync.fine_match(S0, "filename", t, veh["samples"], out.get("ego_motion"),
                                    out["video"]["duration_s"])
                self.assertIn("reason", r)


def _good_output():
    """깨뜨릴 원본: 가짜 분석기로 고정 (HMTM_BB_ANALYZER가 mtm이어도 같은 출력)"""
    return analyzer.run("none.mp4", scenario="right_turn_motion", name="fake")


def _set(path, value):
    def f(o):
        node = o
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        if value is _DEL:
            del node[keys[-1]]
        else:
            node[keys[-1]] = value
    return f


_DEL = object()
BREAKS = {
    "schema_version": _set("schema_version", "bb-0.0"),
    "status": _set("status", "maybe"),
    "analyzer": _set("analyzer", {"name": "x"}),
    "video.fps": _set("video.fps", _DEL),
    "facts.schema_version": _set("facts.schema_version", "0.2"),
    "collision.t missing": _set("facts.collision.t", None),
    "collision.t outside": _set("facts.collision.t", 99.0),
    "collision.frame": _set("facts.collision.frame", -3),
    "collision.a": _set("facts.collision.a", "A"),
    "collision.zone": _set("facts.collision.zone", "parking"),
    "party ids": _set("facts.parties", {"ego": {}, "B": {}}),
    "bare value": _set("facts.parties.other.cls", "car"),
    "bad enum": _set("facts.parties.other.movement", {"value": "fly", "source": "model"}),
    "bad guess": _set("facts.road.signal_present", {"value": None, "source": "model", "guess": "yes"}),
    "confidence": _set("facts.parties.ego.movement", {"value": "right_turn", "source": "model", "confidence": 1.5}),
    "ego entry_from": _set("facts.parties.ego.entry_from", {"value": "south", "source": "model"}),
    "entry time": _set("facts.parties.other.intersection_entry", {"frame": 3}),
    "motion length": lambda o: o["ego_motion"]["speed_proxy"].pop(),
    "motion order": lambda o: o["ego_motion"]["t"].reverse(),
    "jolt outside": _set("ego_motion.jolt_t", [99.0]),
    "no reason": lambda o: o.update(status="unsupported", reason=None),
    "no_collision with t": _set("status", "no_collision"),
    "t_confidence": _set("facts.collision.t_confidence", 1.5),
    "t_source": _set("facts.collision.t_source", "maybe"),
    "candidates shape": _set("hints.collision_candidates", {"t": 3.0}),
    "candidate outside": _set("hints.collision_candidates", [{"t": 99.0}]),
}


class Rejects(unittest.TestCase):
    def test_good_output_passes(self):
        out = _good_output()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(analyzer.validate_output(out), out)

    def test_each_break_is_rejected(self):
        for name, brk in BREAKS.items():
            with self.subTest(name):
                out = _good_output()
                brk(out)
                v = analyzer.validate_output(out)
                self.assertEqual((v["status"], v["reason"]), ("failed", "analyzer_output_invalid"), name)
                self.assertIn("약속한 모양", v["message"])

    def test_extra_keys_allowed(self):
        """분석기가 더 내는 값(모르는 키)은 모양만 맞으면 통과 (1.3 "나머지 키는 모양만")"""
        out = _good_output()
        out["facts"]["parties"]["other"]["heading_hint"] = {"value": 12, "source": "model"}
        out["hints"]["light_hints"] = [{"t": 3.0}]
        self.assertEqual(analyzer.validate_output(out)["status"], "ok")

    def test_exception_becomes_failed(self):
        class Boom:
            name, version = "boom", "0"

            def analyze(self, *a, **k):
                raise RuntimeError("x")
        orig = analyzer.get_analyzer
        analyzer.get_analyzer = lambda name=None: Boom()
        try:
            out = analyzer.run("none.mp4")
        finally:
            analyzer.get_analyzer = orig
        self.assertEqual((out["status"], out["reason"], out["analyzer"]["name"]), ("failed", "server_error", "boom"))


if __name__ == "__main__":
    unittest.main()
