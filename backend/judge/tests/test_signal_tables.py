"""신호 있는 교차로 도표(차1~차4) 테스트: 도표마다 조건을 만족하는 facts를 만들어 해당 도표와 기본 비율이 나오는지 확인"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fault_engine import judge, load_catalog, load_rules  # noqa: E402

RULES, CATALOG = load_rules(), load_catalog()
NORTH, WEST, SOUTH, EAST = [0, -1], [-1, 0], [0, 1], [1, 0]   # 화면 좌표 (y 아래로 증가)
B_HEADING = {"enters_from_opposite_of": SOUTH, "enters_from_right_of": WEST,
             "enters_from_left_of": EAST, "enters_from_side_of": WEST, "enters_same_direction_as": NORTH}

NEUTRAL = {"user_factors": [], "speed_over_limit_kmh": 0, "entry_speed_to_limit": 0.3, "entry_speed": 0.01,
           "entry_speed_ratio": 1.0, "entry_lead_sec": 0.0, "damage_severity": "minor", "damage_enlarged": False,
           "wide_turn": False, "narrow_turn": False, "sudden_turn": False, "turn_almost_completed": False,
           "entered_just_before_red": False, "lane_marking_violation": False, "lane_change_after_turn": False,
           "view_obstructed": False, "turn_signal_used": None, "stopped_before_entry": True,
           "stopped_in_intersection": False, "entered_congested_intersection": False,
           "lane_change_in_intersection": False, "ped_signal_green_at_turn": False,
           "stop_sign": False, "one_way_violation": False, "left_turn_prohibited_violation": False,
           "left_turn_method_violation": False, "no_lane_across": False, "could_foresee_other_turn": False,
           "yield_violation": False, "started_from_parking": False, "slowed_before_entry": False,
           "right_turn_method_violation": False, "forced_cut_in": False, "crossed_shoulder_or_sidewalk": False,
           "right_space_wide": False, "wrong_way": False, "from_off_road": False, "crossed_center_line": False,
           "overtook_in_no_passing_zone": False, "rear_inattention": False, "crossed_double_solid_center": False,
           "going_uphill": False, "crossed_virtual_center": False, "stationary_at_collision": False,
           "evasive_action": False, "ran_signal": False, "is_emergency": False, "door_opening": False,
           "_sources": {}}


def first(v):
    return v[0] if isinstance(v, list) else v


def _resolve(value):
    if isinstance(value, str) and value.startswith("$"):
        return RULES["thresholds"][value[1:]]["value"]
    return value


def _put(obj, cond):
    """조건을 만족하는 값을 obj에 넣는다 (부등호는 기준값에서 0.5만큼 떨어진 값)"""
    if "any" in cond:
        return _put(obj, cond["any"][0])
    op, val = cond["op"], _resolve(cond["value"])
    if op == "!=":
        obj[cond["fact"]] = "other"
        return
    if op in (">=", ">"):
        obj[cond["fact"]] = val + 0.5
    elif op in ("<=", "<"):
        obj[cond["fact"]] = val - 0.5
    else:
        obj[cond["fact"]] = first(val)


def facts_for(rule):
    """도표의 장소·역할 조건을 그대로 만족하는 facts 생성"""
    roles = rule["applies_when"]["roles"]
    rels = roles["B"].get("relations") or [{"type": "enters_from_opposite_of"}]
    headings = {"A": NORTH, "B": B_HEADING[rels[0]["type"]]}
    vehicles = []
    for name, tid in (("A", "1"), ("B", "2")):
        v = {**copy.deepcopy(NEUTRAL), "track_id": tid, "cls": "car", "heading": headings[name]}
        for c in roles[name]["where"]:
            _put(v, c)
        if v.get("stop_sign"):
            v["stopped_before_entry"] = False   # 일시정지 표지 위반
        if v.get("signal_at_entry") == "flashing_red":
            v["stopped_before_entry"] = False   # 일시정지 후 진입이면 차1-5 등 미적용
        vehicles.append(v)
    facts = {"schema_version": "2.0", "video": "t.mp4", "scene": {}, "signal": {},
             "vehicles": vehicles, "collision": {"frame": 1, "between": ["1", "2"]}}
    for c in rule["applies_when"]["scene"]:
        if "any" in c:
            c = c["any"][0]
        head, key = c["fact"].split(".", 1)
        facts[head][key] = "other" if c["op"] == "!=" else first(c["value"])
    if facts["scene"].get("location") == "roundabout":
        for v in vehicles:
            v["stopped_before_entry"] = False   # 회전교차로 진입 전 일시정지(-10)가 없는 기본 상황
    return facts


SIGNAL_RULES = list(RULES["rules"])


class TestEveryTable(unittest.TestCase):
    def test_each_table_selected_with_base(self):
        self.assertEqual(len(SIGNAL_RULES), 124)
        for rule in SIGNAL_RULES:
            with self.subTest(rule=rule["id"]):
                r = judge(facts_for(rule), RULES, CATALOG)
                self.assertTrue(r["supported"], r.get("undetermined_rules"))
                self.assertEqual(r["rule_id"], rule["id"])
                self.assertEqual(r["fault"], rule["base"])


def by_id(i):
    return next(r for r in RULES["rules"] if r["id"] == i)


class TestSignalModifiers(unittest.TestCase):
    def test_1_1_zero_base_b_grave_not_applied(self):
        """차1-1 A0:B100. A 수정요소가 없으면 B 중대한 과실은 적용하지 않음 (총설 p.21 ②)"""
        f = facts_for(by_id("차1-1"))
        f["vehicles"][1]["user_factors"] = ["no_license"]
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 0, "B": 100})

    def test_1_1_a_notable(self):
        f = facts_for(by_id("차1-1"))
        f["vehicles"][0]["user_factors"] = ["phone"]
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 10, "B": 90})

    def test_1_1_excluded_when_stopped_in_intersection(self):
        """교차로 안에서 일시정지 중인 차량과의 충돌은 차1-1 미적용"""
        f = facts_for(by_id("차1-1"))
        f["vehicles"][1]["stopped_in_intersection"] = True
        self.assertFalse(judge(f, RULES, CATALOG)["supported"])

    def test_1_3_late_entry_before_red(self):
        f = facts_for(by_id("차1-3"))
        f["vehicles"][0]["entered_just_before_red"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 40, "B": 60})

    def test_2_3_turn_completed(self):
        f = facts_for(by_id("차2-3"))
        f["vehicles"][1]["turn_almost_completed"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 50, "B": 50})

    def test_2_6_straight_side_reductions(self):
        """차2-6 A90:B10, B 비보호 표지 없음 -10 → 100:0"""
        f = facts_for(by_id("차2-6"))
        f["vehicles"][1]["unprotected_left_sign"] = False
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 100, "B": 0})

    def test_2_2_vs_2_6_by_unprotected_sign(self):
        f = facts_for(by_id("차2-2(녹색)"))
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차2-2(녹색)")
        # 좌회전 차량 쪽에 비보호 표지가 있으면 차2-2가 아님 (역할을 바꿔 차2-6 상황)
        f["vehicles"][1]["unprotected_left_sign"] = True
        self.assertNotEqual(judge(f, RULES, CATALOG).get("rule_id"), "차2-2(녹색)")

    def test_1_5_flashing_red_stopped_falls_back(self):
        """적색점멸에서 일시정지 후 진입했으면 신호등 없는 교차로 기준 (차1-5 미적용)"""
        f = facts_for(by_id("차1-5"))
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차1-5")
        f["vehicles"][0]["stopped_before_entry"] = True
        self.assertFalse(judge(f, RULES, CATALOG)["supported"])

    def test_unknown_stop_gives_caution(self):
        f = facts_for(by_id("차1-1"))
        for v in f["vehicles"]:
            v["stopped_in_intersection"] = None
        r = judge(f, RULES, CATALOG)
        self.assertEqual(r["rule_id"], "차1-1")
        self.assertTrue(any("확인 필요" in n for n in r["notes"]))

    def test_4_1_stop_violation(self):
        f = facts_for(by_id("차4-1"))
        f["vehicles"][1]["stopped_before_entry"] = False
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 10, "B": 90})


class TestOneSideSignal(unittest.TestCase):
    def test_5_1_stop_violation_only_when_red_ahead(self):
        """차5-1 일시정지 위반은 A 전방 신호가 적색일 때만"""
        f = facts_for(by_id("차5-1(가)"))           # A 전방 신호 없음
        f["vehicles"][0]["stopped_before_entry"] = False
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 80, "B": 20})
        f["vehicles"][0]["signal_at_entry"] = "red"  # 전방 적색에서 정지 없이 우회전
        f["signal"]["state"] = "normal"
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 90, "B": 10})

    def test_5_1_b_lane_change(self):
        f = facts_for(by_id("차5-1(나)"))
        f["vehicles"][1]["lane_change_in_intersection"] = True
        f["vehicles"][1]["turn_signal_used"] = False
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 20, "B": 80})

    def test_5_2_vs_5_1_by_ped_signal(self):
        f = facts_for(by_id("차5-2"))
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차5-2")
        f["vehicles"][0]["ped_signal_green_at_turn"] = False
        f["vehicles"][0]["signal_at_entry"] = "red"
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차5-1(가)")

    def test_6_1_left_turn_also(self):
        f = facts_for(by_id("차6-1(다)"))
        f["vehicles"][0]["movement"] = "left_turn"
        r = judge(f, RULES, CATALOG)
        self.assertEqual((r["rule_id"], r["fault"]), ("차6-1(다)", {"A": 10, "B": 90}))


class TestStopSign(unittest.TestCase):
    def test_7_1_excluded_when_b_stopped(self):
        """차7-1: 일시정지 의무를 지키고 진입했으면 차12 적용(이 기준 미적용)"""
        f = facts_for(by_id("차7-1"))
        f["vehicles"][1]["stopped_before_entry"] = True
        self.assertFalse(judge(f, RULES, CATALOG)["supported"])

    def test_8_1_stopped_then_started_and_prohibited(self):
        f = facts_for(by_id("차8-1"))
        f["vehicles"][1]["stopped_before_entry"] = True            # 일시정지 후 출발 -10
        f["vehicles"][1]["left_turn_prohibited_violation"] = True  # 좌회전 금지 위반 +20
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 10, "B": 90})

    def test_8_2_vs_8_3_by_side(self):
        """오른쪽에서 온 좌회전 70:30, 왼쪽에서 온 좌회전 60:40"""
        self.assertEqual(judge(facts_for(by_id("차8-2")), RULES, CATALOG)["base"], {"A": 70, "B": 30})
        self.assertEqual(judge(facts_for(by_id("차8-3")), RULES, CATALOG)["base"], {"A": 60, "B": 40})

    def test_t_junction_only_in_t(self):
        f = facts_for(by_id("차9-1"))
        f["scene"]["junction_type"] = "cross"
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 80, "B": 20})
        f["scene"]["junction_type"] = "t"
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 90, "B": 10})

    def test_ch14_excluded_with_stop_sign(self):
        """일시정지 표지가 있으면 차14-1(표지 없는 교차로)은 적용하지 않음"""
        from test_engine import base_facts
        f = base_facts()
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차14-1")
        f["vehicles"][0]["stop_sign"] = True
        self.assertNotEqual(judge(f, RULES, CATALOG).get("rule_id"), "차14-1")


class TestLaneMarking(unittest.TestCase):
    def test_11_1_vs_11_3_by_signal(self):
        """같은 차로 상황이라도 신호 있으면 차11-1(100:0), 없으면 차11-3(40:60) 계열"""
        self.assertEqual(judge(facts_for(by_id("차11-1")), RULES, CATALOG)["base"], {"A": 100, "B": 0})
        self.assertEqual(judge(facts_for(by_id("차11-3")), RULES, CATALOG)["base"], {"A": 40, "B": 60})

    def test_11_3_modifiers(self):
        f = facts_for(by_id("차11-3"))
        f["vehicles"][0]["no_lane_across"] = True         # A +10
        f["vehicles"][1]["sudden_turn"] = True            # B +10
        f["vehicles"][1]["turn_signal_used"] = False      # B +10
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 30, "B": 70})

    def test_11_2_excluded_when_b_changes_lane(self):
        f = facts_for(by_id("차11-2"))
        f["vehicles"][1]["lane_change_in_intersection"] = True
        self.assertFalse(judge(f, RULES, CATALOG)["supported"])

    def test_11_4_excluded_when_b_started_from_parking(self):
        f = facts_for(by_id("차11-4"))
        f["vehicles"][1]["started_from_parking"] = True
        self.assertFalse(judge(f, RULES, CATALOG)["supported"])

    def test_same_direction_required(self):
        """노면표시 도표는 두 차가 같은 방향일 때만"""
        f = facts_for(by_id("차11-6"))
        f["vehicles"][1]["heading"] = [-1, 0]
        self.assertNotEqual(judge(f, RULES, CATALOG).get("rule_id"), "차11-6")


class TestNoSignal(unittest.TestCase):
    def test_12_1_entry_order(self):
        """동시 40:60, A 선진입 30:70, A 후진입 70:30"""
        for v, lead, base in (("가", 0.2, {"A": 40, "B": 60}), ("나", 2.0, {"A": 30, "B": 70}), ("다", -2.0, {"A": 70, "B": 30})):
            f = facts_for(by_id(f"차12-1({v})"))
            f["vehicles"][0]["entry_lead_sec"] = lead
            r = judge(f, RULES, CATALOG)
            self.assertEqual((r["rule_id"], r["fault"]), (f"차12-1({v})", base))

    def test_12_unknown_entry_order(self):
        """진입 순서를 모르면 차12는 판정 보류"""
        f = facts_for(by_id("차12-1(가)"))
        f["vehicles"][0]["entry_lead_sec"] = None
        r = judge(f, RULES, CATALOG)
        self.assertFalse(r["supported"])
        self.assertTrue(any(u["rule_id"].startswith("차12-1") for u in r["undetermined_rules"]))

    def test_12_slowed_down(self):
        f = facts_for(by_id("차12-1(가)"))
        f["vehicles"][0]["slowed_before_entry"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 30, "B": 70})

    def test_15_1_turn_completed_minus_30(self):
        f = facts_for(by_id("차15-1"))
        f["vehicles"][1]["turn_almost_completed"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 60, "B": 40})

    def test_16_1_vs_16_2_by_side(self):
        self.assertEqual(judge(facts_for(by_id("차16-1")), RULES, CATALOG)["base"], {"A": 40, "B": 60})
        self.assertEqual(judge(facts_for(by_id("차16-2")), RULES, CATALOG)["base"], {"A": 30, "B": 70})

    def test_width_decides_16_1_vs_16_3(self):
        f = facts_for(by_id("차16-1"))
        f["scene"]["road_width"] = "different"
        f["vehicles"][0]["on_wider_road"] = True
        f["vehicles"][1]["on_wider_road"] = False
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차16-3")

    def test_stop_sign_excludes_no_signal_tables(self):
        f = facts_for(by_id("차13-1"))
        f["vehicles"][0]["stop_sign"] = True
        self.assertNotEqual(judge(f, RULES, CATALOG).get("rule_id"), "차13-1")


class TestSimultaneousTurn(unittest.TestCase):
    def test_19_1_right_turn_also(self):
        f = facts_for(by_id("차19-1"))
        f["vehicles"][1]["movement"] = "right_turn"
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차19-1")

    def test_20_2_preferred_over_20_1_when_cut_in(self):
        """뒤에서 오른쪽으로 끼어든 경우는 차20-2(70:30), 아니면 차20-1(40:60)"""
        f = facts_for(by_id("차20-2"))
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차20-2")
        f["vehicles"][0]["cut_in"] = False
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차20-1")

    def test_21_1_inside_car_priority(self):
        f = facts_for(by_id("차21-1"))
        f["vehicles"][1]["forced_cut_in"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 30, "B": 70})


class TestHeadOn(unittest.TestCase):
    def test_31_not_at_intersection(self):
        """중앙선 침범 도표는 교차로 밖(단일로)에서만"""
        f = facts_for(by_id("차31-1"))
        f["scene"]["location"] = "intersection"
        self.assertNotEqual(judge(f, RULES, CATALOG).get("rule_id"), "차31-1")

    def test_32_1_each_side(self):
        f = facts_for(by_id("차32-1"))
        f["vehicles"][0]["crossed_virtual_center"] = True   # A +20
        f["vehicles"][1]["evasive_action"] = True           # B -10
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 80, "B": 20})

    def test_32_1_vs_31_by_center_line(self):
        f = facts_for(by_id("차32-1"))
        f["scene"]["center_line"] = True
        f["vehicles"][1]["wrong_way"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차31-1")

    def test_33_1_signal_violation_plus_80(self):
        f = facts_for(by_id("차33-1(가)"))
        f["vehicles"][0]["ran_signal"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 100, "B": 0})

    def test_33_type_decides_base(self):
        self.assertEqual(judge(facts_for(by_id("차33-2(가)")), RULES, CATALOG)["base"], {"A": 30, "B": 70})
        self.assertEqual(judge(facts_for(by_id("차33-2(나)")), RULES, CATALOG)["base"], {"A": 80, "B": 20})


class TestSameDirection(unittest.TestCase):
    def test_41_1_rear_end_b_sudden_stop(self):
        """추돌은 뒤차 100%. 앞차의 이유 없는 급정지 +30 (0:100 순서상 B 먼저 적용)"""
        f = facts_for(by_id("차41-1"))
        f["vehicles"][1]["sudden_stop_without_reason"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 70, "B": 30})

    def test_41_1_excluded_for_dropped_cargo(self):
        f = facts_for(by_id("차41-1"))
        f["vehicles"][1]["dropped_cargo"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차48-1")

    def test_43_6_more_specific_than_43_2(self):
        """갓길 진로변경 사고는 일반 진로변경(차43-2)이 아니라 차43-6"""
        self.assertEqual(judge(facts_for(by_id("차43-6")), RULES, CATALOG)["rule_id"], "차43-6")

    def test_43_3_stop_start_and_congested_not_both(self):
        """정차 후 출발(+20)과 정체차로변경(+10)은 중복하지 않음"""
        f = facts_for(by_id("차43-3"))
        f["vehicles"][0]["started_after_stop"] = True
        f["vehicles"][0]["congested_lane_change"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 70, "B": 30})

    def test_44_1_off_road_right_turn(self):
        f = facts_for(by_id("차44-1"))
        f["vehicles"][1]["body_partly_out_waiting"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 30, "B": 70})

    def test_47_3_bus_more_specific(self):
        self.assertEqual(judge(facts_for(by_id("차47-3")), RULES, CATALOG)["rule_id"], "차47-3")

    def test_47_2_school_bus(self):
        f = facts_for(by_id("차47-2"))
        f["vehicles"][0]["is_school_bus"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 30, "B": 70})


class TestOtherTypes(unittest.TestCase):
    def test_emergency_priority_over_signal_table(self):
        """녹색 직진 대 적색 직진이라도 상대가 긴급자동차면 차1-1이 아니라 차55-1"""
        f = facts_for(by_id("차1-1"))
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차1-1")
        f["vehicles"][1]["is_emergency"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차55-1")

    def test_emergency_lane_change_over_43_2(self):
        f = facts_for(by_id("차43-2"))
        f["vehicles"][1]["is_emergency"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차55-6")

    def test_roundabout_single_vs_multi(self):
        self.assertEqual(judge(facts_for(by_id("차54-1")), RULES, CATALOG)["base"], {"A": 20, "B": 80})
        f = facts_for(by_id("차54-2"))
        self.assertEqual(judge(f, RULES, CATALOG)["base"], {"A": 10, "B": 90})

    def test_door_opening_transit_stop(self):
        f = facts_for(by_id("차52-1"))
        f["vehicles"][1]["door_at_transit_stop"] = True
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 40, "B": 60})

    def test_parking_lot_exit(self):
        f = facts_for(by_id("차51-1"))
        f["vehicles"][1]["movement"] = "reverse"   # B 후진 출차 +10
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 20, "B": 80})


class TestTwoWheelerSpecial(unittest.TestCase):
    def test_61_3_over_52_1_for_two_wheeler_on_right(self):
        """오른쪽으로 지나간 이륜차의 문 열림 사고는 차52-1(20:80)이 아니라 차61-3(30:70)"""
        f = facts_for(by_id("차52-1"))
        f["vehicles"][0].update({"cls": "two_wheeler", "passing_on_right": True})
        self.assertEqual(judge(f, RULES, CATALOG)["rule_id"], "차61-3")

    def test_61_no_double_two_wheeler_reduction(self):
        """특수유형에는 이륜차 감산을 다시 적용하지 않음"""
        f = facts_for(by_id("차61-1"))
        f["vehicles"][0]["damage_severity"] = "severe"
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 70, "B": 30})

    def test_61_2_sidewalk_stop_and_slow_both(self):
        """보도 횡단 일시정지 불이행은 서행불이행과 별개로 가산"""
        f = facts_for(by_id("차61-2"))
        f["vehicles"][1]["stopped_before_sidewalk"] = False
        f["vehicles"][1]["entry_speed_to_limit"] = 0.9
        self.assertEqual(judge(f, RULES, CATALOG)["fault"], {"A": 50, "B": 50})


if __name__ == "__main__":
    unittest.main()
