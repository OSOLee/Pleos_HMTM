"""A가 넘기는 사실·답으로 B 판정 모듈의 차대차 도표가 실제로 골라지는지 (docs/facts_plan.md 1·2차)

  python -m unittest tests.test_rules_coverage -v

평가 영상에는 추돌·진로변경·역주행·앞지르기 같은 사고가 거의 없어서, 사고마다 A 형식의 facts(build_facts가 만드는
모양)와 사용자 답(answers.json)을 손으로 만들어 A의 답 변환(answers.to_assumptions) → B adapter → B 엔진을 그대로
거친다. 판정 모듈(backend/judge)이 없으면 건너뜀.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.app import answers, judge_bridge, situation

JUDGE = os.path.join(ROOT, "judge")
DIRS = {"south": (0, -1), "north": (0, 1), "east": (-1, 0), "west": (1, 0)}   # 그 길에서 들어올 때 화면 진행 방향


def party(came, movement="straight", **kw):
    p = {"cls": "car", "movement": movement, "entry_from": came, "heading_start": list(DIRS[came]) if came else None,
         "intersection_entry": None, "stop_state": "driving"}
    p.update(kw)
    return p


def judge(pa, pb, user=None, signal=False, location="intersection", zone="intersection"):
    facts = {"schema_version": "0.2", "video": "test", "fps": 15,
             "road_type": location if location == "intersection" else None,
             "road": {"location": location, "junction_type": "cross", "signal_present": signal},
             "collision": {"frame": 50, "t": 3.3, "a": "1", "b": "2", "zone": zone},
             "parties": {"1": pa, "2": pb}, "events": [], "unknowns": []}
    user = user or {}
    facts["unknowns"] = situation.questions(facts, user)
    answers.check(facts, user, 100)   # 답이 질문 보기 안인지 (앱과 같은 검사)
    asked = {u["field"] for u in facts["unknowns"]} | {"road.signal_present", "road.center_line"}   # 둘은 build_facts가 물음
    not_asked = sorted(set(user) - asked)
    assert not not_asked, f"앱이 묻지 않는 답을 넣음: {not_asked}"
    judge_facts, _ = answers.fill_guesses(facts, [], user)   # 앱과 같이 판정용 facts를 만듦 (장소는 가정으로)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(judge_facts, f)
    try:
        r = judge_bridge.judge(f.name, answers.to_assumptions(facts, user), JUDGE)["result"]
    finally:
        os.remove(f.name)
    return r.get("rule_id"), r


@unittest.skipUnless(os.path.exists(os.path.join(JUDGE, "fault_engine.py")), "판정 모듈이 없음")
class CarToCarRules(unittest.TestCase):
    def check(self, expect, pa, pb, user=None, **kw):
        rule, r = judge(pa, pb, user, **kw)
        missing = [(u["rule_id"], u["missing"]) for u in r.get("undetermined_rules", [])][:5]
        self.assertEqual(rule, expect, f"고른 도표 {rule}, 못 정한 후보 {missing}")

    def test_stop_sign(self):   # 1차: 일시정지 표지 질문
        self.check("차7-1", party("south"), party("east"), {"road.signal_present": False, "road.stop_sign_side": "2"})

    def test_rear_end(self):    # 1차: 앞차 질문
        self.check("차41-1", party("south"), party("south"), {"pair.lead_order": "2"}, location=None)

    def test_lane_change(self):   # 2차: 특수 상황 "차로를 바꾸던 중"
        self.check("차43-2", party("south"), party("south"),
                   {"pair.lead_order": "2", "situation.special": ["lane_change:2"], "parties.2.lane_change_dir": "left"},
                   location=None)

    def test_wrong_way(self):     # 2차: 교차로를 벗어난 길에서 마주 오다 역주행 (충돌이 진입로 영역 → 장소 질문)
        self.check("차31-1", party("south", opposite_direction=True), party("north", opposite_direction=True),
                   {"road.center_line": True, "road.location": "straight", "situation.special": ["wrong_way:2"]},
                   zone="appr_s")

    def test_location_answer_reaches_judge(self):
        # 장소를 답하지 않으면 교차로로 보고, 같은 사고라도 역주행 도표(교차로가 아닌 곳)는 안 골라짐
        rule, _ = judge(party("south", opposite_direction=True), party("north", opposite_direction=True),
                        {"road.center_line": True, "situation.special": ["wrong_way:2"]}, zone="appr_s")
        self.assertNotEqual(rule, "차31-1")

    def test_overtake(self):      # 2차: 앞지르기 → 유형
        self.check("차45-1", party("south"), party("south", "left_turn"),
                   {"pair.lead_order": "2", "situation.special": ["overtake:1"],
                    "parties.1.overtake_type": "center_solid"}, location=None)

    def test_both_u_turn(self):   # 2차: 두 차 다 유턴
        self.check("차46-1(가)", party("south", "u_turn"), party("south", "u_turn"),
                   {"pair.lead_order": "2", "pair.u_turn_timing": "sudden",
                    "parties.1.u_turn_type": "always", "parties.2.u_turn_type": "always"}, location=None)

    def test_lane_marking(self):  # 2차: 바닥 화살표 (신호 없는 교차로, 같은 방향)
        self.check("차11-3", party("south", lane_marking=None), party("south", "left_turn"),
                   {"road.signal_present": False, "pair.lead_order": "2",
                    "parties.1.lane_marking": "left_only", "parties.2.lane_marking": "straight_only"})

    # 범위 밖 장소 (모서리 단계에서 고른 장소 종류 → 질문)
    def roundabout(self, expect, lanes, p1, p2):
        user = {"road.roundabout_lanes": lanes}
        for t, p in (("1", p1), ("2", p2)):
            user.update({f"parties.{t}.{k}": v for k, v in p.items()})
        self.check(expect, party(None), party(None), user, location="roundabout")

    def test_roundabout(self):
        self.roundabout("차54-1", "single", {"roundabout_action": "circulating"}, {"roundabout_action": "entering"})
        self.roundabout("차54-2", "multi", {"roundabout_action": "circulating", "roundabout_lane": 1},
                        {"roundabout_action": "entering", "roundabout_lane": 1, "entry_lane_from": 1, "big_entry": True})
        self.roundabout("차54-3", "multi", {"roundabout_action": "exiting_lane_change"},
                        {"roundabout_action": "entering", "roundabout_lane": 2, "entry_lane_from": 2, "big_entry": False})
        self.roundabout("차54-4", "multi", {"roundabout_action": "exiting_lane_change"},
                        {"roundabout_action": "circulating", "roundabout_lane": 2})
        self.roundabout("차54-5", "multi",
                        {"roundabout_action": "entering", "roundabout_lane": 2, "entry_lane_from": 1, "big_entry": False},
                        {"roundabout_action": "entering", "roundabout_lane": 2, "entry_lane_from": 2, "big_entry": False})

    def test_parking_lot(self):
        self.check("차51-1", party(None), party(None),
                   {"parties.1.parking_action": "aisle", "parties.2.parking_action": "leaving"}, location="parking_lot")
        self.check("차51-2", party(None), party(None),
                   {"parties.1.parking_action": "entering", "parties.2.parking_action": "aisle", "pair.lead_order": "1"},
                   location="parking_lot")

    def test_parked_position(self):   # 서 있던 이유 → 서 있던 곳 (차42-2 일반 도로 가장자리, 42-3 고속도로 갓길)
        stopped = dict(stopped_before_collision=True, stop_state=None)
        self.check("차42-2", party("south", **stopped), party("south"),
                   {"parties.1.stop_state": "parked", "parties.1.position": "road_edge", "pair.lead_order": "1",
                    "situation.special": []}, location=None)
        self.check("차42-3", party("south"), party("south", **stopped),
                   {"parties.2.stop_state": "parked", "parties.2.position": "shoulder", "pair.lead_order": "2",
                    "situation.special": ["highway"]}, location=None)

    def test_shoulder_and_safety_zone(self):
        self.check("차43-6", party("south"), party("south"),
                   {"pair.lead_order": "1", "situation.special": ["lane_change:1", "to_shoulder:1"],
                    "parties.1.lane_change_dir": "right", "parties.2.position": "shoulder"}, location=None)
        for inside, expect in ((True, "차43-7(가)"), (False, "차43-7(나)")):
            self.check(expect, party("south"), party("south"),
                       {"pair.lead_order": "2", "situation.special": ["safety_zone:1", "lane_change:2"],
                        "parties.2.lane_change_dir": "left", "parties.1.in_safety_zone_at_collision": inside},
                       location=None)

    def test_emergency_mode(self):
        self.check("차55-2", party("south", opposite_direction=True), party("north", opposite_direction=True),
                   {"situation.special": ["emergency:2"], "parties.2.emergency_mode": "left_side"}, location=None)
        self.check("차55-5", party("south"), party("south"),
                   {"pair.lead_order": "1", "situation.special": ["emergency:2"], "parties.2.emergency_mode": "overtaking"},
                   location=None)

    def test_two_wheeler(self):   # 이륜차 특수 보기는 이륜차 당사자에게만
        moto = dict(cls="two_wheeler")
        self.check("차61-1", party("south", **moto), party("north", "left_turn"),
                   {"situation.special": ["queue:1"]})
        self.check("차61-3", party("south", **moto), party("south"),
                   {"pair.lead_order": "2", "situation.special": ["pass_right:1", "door:2"]}, location=None)
        q = situation.special_question("1", "2", 0, {"always"}, {"1": "two_wheeler", "2": "car"})
        self.assertIn("queue:1", q["options"])
        self.assertNotIn("queue:2", q["options"])


if __name__ == "__main__":
    unittest.main()
