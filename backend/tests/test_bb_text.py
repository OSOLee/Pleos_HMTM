"""질문·보기 문구의 조사와 답한 선택 질문 정의 (2026-11-12, feature/collision-pick)

  python -m pytest tests/test_bb_text.py

Josa      MTM 문구 "{t}번이 …"의 당사자 이름을 바꿀 때 조사도 받침에 맞게 (내 차가, 상대는, 상대(이륜차)가)
Answered  이미 답한 선택 질문(특수 상황·운전자 요인·과속 인과관계)도 answered에 정의가 나옴
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)
os.chdir(ROOT)
from bb_common import make_video   # noqa: E402
from src.app import situation   # noqa: E402
from src.blackbox import adapter, analyzer, api, fake   # noqa: E402
from src.vehicle.adapter import _rename, josa   # noqa: E402

WRONG = re.compile(r"(내 차|상대 차|상대)(\([^()]*\))?(이|은|을|과)(?![가-힣])")


class Josa(unittest.TestCase):
    def test_rename(self):
        cases = {"ego번이 후진하던 중": "내 차가 후진하던 중", "other번이 중앙선을 넘음": "상대가 중앙선을 넘음",
                 "ego번은 어쩔 수 없이 서 있었음": "내 차는 어쩔 수 없이 서 있었음",
                 "other번(이륜차)이 서 있는 차 오른쪽으로 지나감": "상대(이륜차)가 서 있는 차 오른쪽으로 지나감",
                 "ego번 차와 other번 차": "내 차와 상대 차", "other번을 봤나요": "상대를 봤나요", "ego번": "내 차",
                 "other번이 상대가 가까이 왔을 때 갑자기 회전함": "상대가 내 차가 가까이 왔을 때 갑자기 회전함"}
        for src, want in cases.items():
            self.assertEqual(_rename(src), want, src)

    def test_josa(self):
        self.assertEqual([josa("내 차", j) for j in "이은을과"], ["가", "는", "를", "와"])
        self.assertEqual([josa("보행자", j) for j in "가는를와"], ["가", "는", "를", "와"])
        self.assertEqual([josa("신호등", j) for j in "가는를와"], ["이", "은", "을", "과"])

    def test_all_special_options(self):
        """특수 상황 보기 전부(두 당사자)에 틀린 조사가 없음"""
        texts = [_rename(c) for _, c in situation.special_options("ego", "other")]
        self.assertTrue(texts)
        self.assertEqual([t for t in texts if WRONG.search(t)], [])
        self.assertFalse([t for t in texts if "상대가 상대" in t])

    def test_all_scenario_questions(self):
        """가짜 시나리오 전부의 질문·보기·근거 문장에 "내 차이"·"상대은" 같은 조사가 없음"""
        tmp = tempfile.mkdtemp(prefix="hmtm_text_")
        try:
            video = make_video(os.path.join(tmp, "v.mp4"), seconds=6.0, fps=5.0)
            bad = []
            for name in fake.scenario_names():
                bb = analyzer.run(video, None, name="fake", scenario=name)
                if bb["status"] != "ok":
                    continue
                s, _ = api.match_clock(bb, [], None)
                for answers in ({}, {"parties.other.cls": "pedestrian"}, {"parties.other.cls": "two_wheeler"}):
                    view = adapter.build(bb, None, s, answers)["view"]
                    for q in view["questions"] + view["remaining"]:
                        for t in [q["question"]] + list(q.get("choices") or []):
                            if WRONG.search(t):
                                bad.append((name, t))
            self.assertEqual(bad, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Answered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hmtm_text_")
        video = make_video(os.path.join(cls.tmp, "v.mp4"), seconds=6.0, fps=5.0)
        cls.bb = analyzer.run(video, None, name="fake", scenario="right_turn_left_straight")
        cls.sync, _ = api.match_clock(cls.bb, [], None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def view(self, answers):
        return adapter.build(self.bb, None, self.sync, answers)["view"]

    def test_optional_questions_in_answered(self):
        special = next(q for q in self.view({})["questions"] if q["field"] == "situation.special")
        answers = {"road.signal_present": False, "situation.special": [special["options"][0]],
                   "parties.ego.driver_factors": ["speed_20plus"], "parties.ego.avoidable_at_limit": True}
        got = {a["field"]: a for a in self.view(answers)["answered"]}
        self.assertEqual(set(got), set(answers))
        sp = got["situation.special"]
        self.assertTrue(sp["optional"])
        self.assertEqual(sp["answer_type"], "multi")
        for k in ("options", "choices", "option_groups", "more_options"):   # 여러 개 고르기 화면을 그릴 칸
            self.assertTrue(sp[k], k)
        self.assertEqual(sp["value"], [special["options"][0]])
        self.assertEqual(sp["value_choice"], special["choices"][0])
        self.assertFalse(got["road.signal_present"]["optional"])
        self.assertEqual(got["parties.ego.avoidable_at_limit"]["value_choice"], "예 (피할 수 있었음)")

    def test_avoidable_dropped_when_no_speeding(self):
        """과속을 빼면 인과관계 질문은 answered에서도 빠짐 (답은 서버에 남아도 판정에 안 씀)"""
        answers = {"parties.ego.driver_factors": ["none"], "parties.ego.avoidable_at_limit": True}
        self.assertEqual([a["field"] for a in self.view(answers)["answered"]], ["parties.ego.driver_factors"])


if __name__ == "__main__":
    unittest.main()
