"""차량 사건 ↔ MTM 계약 시험: 자동 답변이 쓰는 키가 지금 MTM 질문·판정 엔진의 키와 맞는지 (docs/api-spec.md 3, 8.4)

  python -m pytest tests/test_vehicle_contract.py

MTM 코드(src/app, src/analyze, judge)가 바뀌어 질문 키·보기·판정 사실 이름이 달라지면 여기서 깨진다.
규칙(rules.py)에 새 자동 답변 키를 더하면 SCENARIOS와 EXPECTED_FIELDS도 같이 고친다.
"""
import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)   # 판정 모듈(backend/judge) 경로가 backend 기준
from src.analyze import build_facts
from src.app import answers as ans
from src.app import judge_bridge, situation
from src.app.pipeline import JUDGE_DIR
from src.vehicle import adapter, rules
from src.vehicle.samples import Timeline, validate
from tests.test_vehicle_api import CROSS, RIGHT_ON, SLOW_DOWN, T, body, build

EGO = adapter.EGO
LEFT_ON = lambda r: "LEFT" if -7000 <= r <= -2000 else "OFF"   # 사고 7~2초 전 LEFT (진로 변경)
STOP_THEN_GO = lambda r: 30.0 if r < -2600 else 0.0 if r < -2000 else 8.0   # 진입 전 멈췄다 출발
REVERSE = dict(speed=lambda r: 5.0 if r >= -3000 else 0.0, gear=lambda r: "R" if r >= -3000 else "D")

# (이름, 기록 만들기 인자, 사용자 답, 판정에서 기대하는 rule_id 또는 None)
SCENARIOS = [
    ("후진", REVERSE, {}, None),
    ("우회전 지시등", dict(speed=SLOW_DOWN, turn=RIGHT_ON), {"parties.ego.movement": "right_turn", **CROSS}, "차13-1"),
    ("진로 변경", dict(turn=LEFT_ON), {"parties.ego.movement": "lane_change", "parties.other.movement": "straight",
                                     "parties.other.cls": "car", "scene.place": "straight"}, None),
    ("직진 서행", dict(speed=SLOW_DOWN), {"parties.ego.movement": "straight", "intersection_entry_order": "same_time",
                                        **CROSS}, "차12-1(가)"),
    ("진입 전 정지", dict(speed=STOP_THEN_GO), {"parties.ego.movement": "straight", **CROSS}, None),
    ("서 있었음", dict(speed=0.0, gear="D"), {}, None),
]
# 규칙이 내는 질문 키 전부 (자동 답변 또는 추정값). 규칙을 더하면 여기도
EXPECTED_FIELDS = {"parties.ego.movement", "parties.ego.lane_change_dir", "parties.ego.turn_signal_used",
                   "parties.ego.slowed_before_entry"}


def rule_results(kw, user):
    req = validate(body(build(**kw)))
    tl = Timeline(req["samples"], end=req["range"]["to"])
    return rules.run_rules(tl, rules.Ctx(req["t_event"], req["t_event_source"]), user)


def mtm_shell(movement=None, place="intersection", signal_present=False):
    """MTM 함수에 넣을 껍데기 (어댑터와 같은 모양): 내 차 진행 방향만 정함"""
    facts = adapter.shell({"vehicle_cls": "car"}, place, "cross" if place == "intersection" else None, {}, [])
    facts["parties"][EGO]["movement"] = movement
    user = {"road.signal_present": signal_present}
    return facts, user


def mtm_questions(movement=None, place="intersection"):
    """지금 MTM이 내는 질문 {field: 질문}: 상황 질문(situation) + 진행 방향 질문(build_facts)"""
    facts, user = mtm_shell(movement, place)
    qs = {q["field"]: q for q in situation.questions(facts, user)}
    # 진행 방향 질문은 build_facts.unknown_items 안에 있어 직접 부르기 어렵다. 보기 목록이 같은지 소스로 확인
    src = inspect.getsource(build_facts.unknown_items)
    assert f'"options": {adapter.MOVEMENTS!r}'.replace("'", '"') in src, "build_facts 진행 방향 보기가 바뀜"
    qs[f"parties.{EGO}.movement"] = {"field": f"parties.{EGO}.movement", "options": adapter.MOVEMENTS}
    return qs


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {name: rule_results(kw, user) for name, kw, user, _ in SCENARIOS}
        cls.judge_adapter = judge_bridge.load(JUDGE_DIR)[0]

    def all_results(self):
        return [r for rs in self.results.values() for r in rs]

    def test_scenarios_cover_every_rule(self):
        """시나리오가 모든 규칙 키를 자동 답변(정함)으로 한 번 이상 냄 (규칙이 늘면 이 시험이 알려 줌)"""
        fields = {r["field"] for r in self.all_results()}
        self.assertEqual(fields, EXPECTED_FIELDS)
        determined = {r["field"] for r in self.all_results() if r["determined"]}
        self.assertEqual(determined, EXPECTED_FIELDS)
        facts = {k for r in self.all_results() for k, v in r["facts"].items() if v is not None}
        self.assertTrue(set(adapter.RULE_FACTS) <= facts, facts)

    def test_auto_answer_keys_are_mtm_questions(self):
        """자동 답변 키 = MTM이 같은 상황에서 묻는 질문 키, 값 = 그 질문의 보기 중 하나.
        서행 규칙은 장소와 관계없이 계산하고(B10) 어댑터가 MTM이 묻는 곳(교차로)에서만 쓰므로 교차로 밖에서는 뺀다"""
        checked = set()
        for name, kw, user, _ in SCENARIOS:
            place = user.get("scene.place", "intersection")
            for r in self.results[name]:
                if r["field"] == "parties.ego.slowed_before_entry" and place != "intersection":
                    continue
                movement = user.get("parties.ego.movement") or (r["value"] if r["field"].endswith(".movement") else None)
                qs = mtm_questions(movement, place)
                with self.subTest(scenario=name, field=r["field"]):
                    self.assertTrue(r["field"] in qs, f"MTM 질문에 {r['field']}가 없음: {sorted(qs)}")
                    for v in (r["value"], r.get("model_guess")):
                        if v is not None:
                            self.assertIn(v, qs[r["field"]]["options"])
                    checked.add(r["field"])
        self.assertEqual(checked, EXPECTED_FIELDS)

    def test_auto_answer_reaches_judge(self):
        """MTM to_assumptions가 자동 답변 값을 판정 가정의 같은 이름으로 넘기고, 판정 엔진 변환기가 그 이름을 읽음"""
        party_fields = set(self.judge_adapter.OPTIONAL_PARTY_FIELDS) | {"movement", "entry_from", "cls"}
        for r in self.all_results():
            if not r["determined"]:
                continue
            key = r["field"].split(".", 2)[2]
            with self.subTest(field=r["field"], value=r["value"]):
                facts, _ = mtm_shell()
                asm = ans.to_assumptions(facts, {r["field"]: r["value"]})
                self.assertEqual(asm["parties"].get(EGO, {}).get(key), r["value"])
                self.assertIn(key, party_fields)

    def test_rule_facts_reach_judge(self):
        """질문 없이 넘기는 사실(stopped_before_entry 등)은 판정 엔진이 읽는 이름이고, 출처 vehicle로 들어감"""
        for k in adapter.RULE_FACTS:
            self.assertIn(k, self.judge_adapter.OPTIONAL_PARTY_FIELDS)
        facts, _ = mtm_shell("straight")
        for k in adapter.RULE_FACTS:   # 어댑터 judge()와 같은 값 객체 모양
            facts["parties"][EGO][k] = {"value": True, "source": "vehicle"}
        facts["parties"]["other"].update(cls="car", movement="straight", entry_from="west")
        engine_facts, _ = self.judge_adapter.to_engine_facts(facts, {})
        ego = next(v for v in engine_facts["vehicles"] if v["track_id"] == EGO)
        for k in adapter.RULE_FACTS:
            self.assertIs(ego[k], True, k)
            self.assertEqual(ego["_sources"].get(k), "vehicle", k)

    def test_preselect_is_special_option(self):
        """후진 확정의 preselect(situation.special의 reverse:ego)가 MTM 특수 상황 보기에 있음"""
        mv = next(r for r in self.results["후진"] if r["field"] == "parties.ego.movement")
        self.assertTrue(mv["determined"])
        facts, user = mtm_shell("reverse")
        q = next(q for q in situation.questions(facts, user) if q["field"] == "situation.special")
        opts = q.get("all_options", q["options"])
        for v in mv["preselect"]["situation.special"]:
            self.assertIn(v, opts)

    def test_full_run(self):
        """자동 답변을 넣어 판정까지 돔: 오류 없이 결과가 나오고, 자동 답변 값은 판정에 출처 vehicle로 쓰임"""
        for name, kw, user, rule_id in SCENARIOS:
            with self.subTest(scenario=name):
                rec = adapter.build(validate(body(build(**kw))), user)
                v = rec["with_vehicle"]   # 자동 답변을 넣은 판정 (기본 판정 rec["view"]는 차량 기록 없이)
                self.assertIn(v["result"]["status"], ("ok", "no_rule"))
                self.assertEqual(rec["view"]["result_with_vehicle"], v["result"])
                base_q = {q["field"]: q for q in rec["view"]["questions"]}
                for a in v["auto_answers"]:   # 자동 답변한 질문은 기본 판정에서 묻고 차량 기록 값을 참고로 붙임
                    if a["field"] in base_q:
                        self.assertEqual(base_q[a["field"]]["vehicle_hint"]["value"], a["value"])
                self.assertTrue(v["judge_version"])
                for a in v["auto_answers"]:
                    self.assertEqual(v["answers"][a["field"]], {"value": a["value"], "source": "vehicle"})
                    self.assertNotIn(a["field"], {q["field"] for q in v["questions"]})
                if rule_id:
                    self.assertEqual((v["result"]["status"], v["result"]["rule_id"]), ("ok", rule_id))
        # 차량 기록 값으로 가감이 붙는 경우: 출처 vehicle
        v = adapter.build(validate(body(build(speed=SLOW_DOWN))),
                          {"parties.ego.movement": "straight", "intersection_entry_order": "same_time", **CROSS})["with_vehicle"]
        self.assertIn("vehicle", {m["source"] for m in v["result"]["modifiers"]})


if __name__ == "__main__":
    unittest.main()
