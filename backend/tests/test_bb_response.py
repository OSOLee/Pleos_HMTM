"""블랙박스 사건 응답 보강 시험 (bb-flow 2부 1단계)

  python -m pytest tests/test_bb_response.py

- answers[키].evidence: 모든 출처(vehicle / video / user / default)에 "~했어요" 근거 문장
- remaining / remaining_count: 실제로 답이 필요한 질문(선택 질문 제외)과 추정값·출처
- 기존 칸은 그대로 (앱 1부가 읽는 칸)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
from src.blackbox import evidence
from test_bb_merge import RIGHT_ON, run, vreq

OLD_KEYS = {"status", "event", "data_quality", "parties", "auto_answers", "answers", "answer_conflicts",
            "source_conflicts", "questions", "result", "judge_version"}


class Sentences(unittest.TestCase):
    def test_particles_and_tone(self):
        self.assertEqual(evidence.sentence("scene.place", "parking_lot"), "사고 장소는 주차장이었어요")
        self.assertEqual(evidence.sentence("scene.place", "intersection"), "사고 장소는 교차로였어요")
        self.assertEqual(evidence.sentence("parties.ego.signal_at_entry", "green"),
                         "내 차가 교차로에 들어갈 때 신호는 초록이었어요")
        self.assertEqual(evidence.sentence("parties.other.cls", "bus"), "상대는 버스였어요")
        self.assertEqual(evidence.sentence("parties.ego.movement", "left_turn"), "내 차가 좌회전했어요")
        self.assertEqual(evidence.sentence("parties.other.entry_from", "opposite"), "상대가 맞은편 길에서 왔어요")
        self.assertEqual(evidence.sentence("road.signal_present", True), "교차로에 신호등이 있었어요")

    def test_unknown_field_uses_question(self):
        q = {"question": "왜 서 있었나요?", "options": ["signal", "parking"], "choices": ["신호 대기", "주차"]}
        self.assertEqual(evidence.sentence("parties.other.stop_state", "signal", q), "왜 서 있었나요? → 신호 대기")

    def test_source_wrappers(self):
        self.assertEqual(evidence.for_video("parties.ego.movement", "right_turn", 17.5),
                         "내 차가 우회전했어요 (17.5초)")
        self.assertEqual(evidence.for_video_guess("road.signal_present", False, None),
                         "영상으로는 교차로에 신호등이 없었던 것 같아요 (추정)")
        self.assertTrue(evidence.for_user("parties.other.cls", "car").endswith("(직접 답했어요)"))
        self.assertIn("(영상 추정)", evidence.for_default("parties.other.cls", "car", "video"))
        self.assertIn("기본값", evidence.for_default("road.wider_road", "equal", None))


class Answers(unittest.TestCase):
    def test_every_answer_has_evidence(self):
        rec = run("right_turn_left_straight", vreq(turn=RIGHT_ON), grade="fine",
                  user={"road.signal_present": False, "parties.other.cls": "truck"})
        views = [run("right_turn_left_straight")["view"], run("mostly_unknown")["view"], rec["view"], rec["with_vehicle"]]
        for view in views:
            for f, a in view["answers"].items():
                self.assertIsInstance(a.get("evidence"), str, f)
                self.assertTrue(a["evidence"], f)
                self.assertIn(a["source"], ("vehicle", "video", "user", "default"), f)

    def test_evidence_by_source(self):
        view = run("right_turn_left_straight", vreq(turn=RIGHT_ON), grade="fine",
                   user={"road.signal_present": False, "parties.other.cls": "truck"})["with_vehicle"]
        a = view["answers"]
        auto = {x["field"]: x["evidence"]["text"] for x in view["auto_answers"]}
        self.assertEqual(a["parties.ego.turn_signal_used"]["evidence"], auto["parties.ego.turn_signal_used"])
        self.assertEqual(a["parties.ego.movement"]["evidence"], "내 차가 우회전했어요 (17.5초)")
        self.assertEqual(a["parties.other.cls"]["evidence"], "상대는 화물차였어요 (직접 답했어요)")
        self.assertEqual(a["road.wider_road"]["evidence"], "두 도로의 폭이 비슷했어요 (기본값)")
        self.assertEqual(a["parties.ego.cls"]["evidence"], "내 차는 승용차였어요 (차량 정보)")
        # 사용자가 영상 값을 고친 충돌에도 사용자 근거 문장
        c = [x for x in view["source_conflicts"] if x["field"] == "parties.other.cls"][0]
        self.assertEqual((c["kind"], c["evidence"]), ("user_vs_video", "상대는 화물차였어요 (직접 답했어요)"))
        self.assertTrue(c["others"][0]["evidence"].startswith("상대는 승용차였어요"))

    def test_default_from_video_guess(self):
        a = run("mostly_unknown")["view"]["answers"]
        self.assertEqual(a["parties.ego.movement"]["evidence"], "내 차가 직진했어요 (영상 추정)")
        # 추정값으로 채움 → basis guess (앱 "추정" 배지), 기본값 → basis default ("가정" 배지)
        self.assertEqual(a["parties.ego.movement"]["basis"], "guess")
        self.assertEqual(a["road.wider_road"]["basis"], "default")


class Remaining(unittest.TestCase):
    def test_remaining_list(self):
        view = run("right_turn_left_straight")["view"]
        rem = view["remaining"]
        self.assertEqual(view["remaining_count"], len(rem))
        self.assertEqual([q["field"] for q in rem], [q["field"] for q in view["questions"] if not q["optional"]])
        q = {x["field"]: x for x in rem}["road.signal_present"]
        self.assertEqual((q["model_guess"], q["guess_source"], q["guess_choice"]), (False, "video", "없음"))
        self.assertEqual(q["question"], "이 교차로에 신호등이 있었나요?")
        self.assertEqual((q["options"], q["choices"]), ([True, False], ["있음", "없음"]))
        self.assertTrue(q["guess_evidence"].startswith("영상으로는"))
        for x in rem:
            self.assertFalse({"field", "question", "options", "choices", "model_guess", "guess_source",
                              "guess_evidence", "guess_choice", "default", "depends_on"} - set(x))

    def test_remaining_shrinks_with_answers(self):
        """남은 질문에 답해 가면 (답이 새 질문을 열 수 있음: 신호 있음 → 신호 색) 결국 비고 done"""
        user, view = {}, run("right_turn_left_straight")["view"]
        for _ in range(5):
            if not view["remaining"]:
                break
            user.update({q["field"]: q["options"][0] for q in view["remaining"]})
            view = run("right_turn_left_straight", user=user)["view"]
        done = view
        self.assertEqual(done["remaining"], [])
        self.assertEqual(done["remaining_count"], 0)
        self.assertEqual(done["status"], "done")

    def test_old_keys_kept(self):
        view = run("right_turn_left_straight")["view"]
        self.assertFalse(OLD_KEYS - set(view))


if __name__ == "__main__":
    unittest.main()
