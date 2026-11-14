"""차대차 도표(B 판정 모듈)에 필요한데 영상으로 확실히 못 정하는 사실을 묻는 질문 (docs/facts_plan.md 1·2차)

build_facts의 질문과 달리 사용자 답(진행 방향 등)에 따라 필요한 질문이 달라져서, 답을 아는 pipeline.solve에서 만든다.
판정이 갈리지 않는 질문은 solve가 지운다 (DROP_IF_SAME).

  road.stop_sign_side              일시정지 표지가 있던 쪽 (신호 없는 교차로) → 당사자별 stop_sign (차7~10, 차12 제외 조건)
  parties.<id>.unprotected_left_sign  비보호 좌회전 표지 (신호 교차로, 좌회전 당사자) → 차2, 4
  parties.<id>.u_turn_type         상시 유턴 구역 / 신호 유턴 (유턴 당사자) → 차33
  parties.<id>.stop_state          충돌 전 서 있던 이유 (같은 방향 사고에서 서 있던 당사자) → 차41, 42
  pair.lead_order                  같은 방향이면 앞에 있던 차, 또는 나란히(side_by_side) (궤적으로 못 정했을 때) → 차19~21, 41~48
  pair.right_side                  나란히 가던 두 차 중 오른쪽 차 (나란히라고 답했거나 둘 다 같은 쪽으로 회전) → 차20·21
  road.lane_fits_two               한 차로에 2대가 나란히 지날 만큼 넓은지 (같은 방향 + 회전) → 차19-1
  intersection_entry_clear         진입 순서를 답했을 때 확실히 먼저였는지 → 명확한 선진입, 차12 선·후진입
  situation.special                특수 상황 (여러 개 고르기, 선택 질문). 아래 SPECIAL
  parties.<id>.lane_change_dir     차로를 바꾼 방향 (진로 변경 당사자) → 차43-3
  parties.<id>.overtake_type       앞지르기 유형 (앞지르기를 고른 당사자) → 차45, 47-1
  pair.u_turn_timing               두 차 다 유턴일 때 → 차46-1
  parties.<id>.ped_signal_green_at_turn  우회전 때 보행자 신호 (신호 교차로, 우회전 당사자) → 차5-2
  parties.<id>.lane_marking        있던 차로의 바닥 화살표 (교차로, 선택 질문) → 차11
  road.center_line_rule_not_applied  좁은 길 교행 (마주 오는 사고 + 중앙선 있음) → 차32-1

장소별 (모서리 단계에서 고른 장소 종류, place_questions) / 앞 답에 따라 생기는 질문 (follow_ups):
  road.roundabout_lanes, parties.<id>.roundabout_action / roundabout_lane / entry_lane_from / big_entry → 차54
  parties.<id>.parking_action      주차장에서 한 일 → in_parking_aisle 등 셋 중 하나 (차51)
  road.center_line                 교차로 아닌 길의 중앙선 → 차31, 32
  parties.<id>.position            서 있던(달리던) 곳: 차로 안 / 갓길 / 도로 가장자리 → 차42-2·3, 43-6
  parties.<id>.in_safety_zone_at_collision  안전지대를 골랐을 때 → 차43-7
  parties.<id>.emergency_mode      긴급자동차를 골랐을 때 → driving_left_side, overtaking (차55)
  parties.<id>.damage_enlarged     대형차를 골랐을 때 차가 커서 사고가 나거나 피해가 커졌는지 → 대형차 가산 (인과관계)

영상으로는 알 수 없는 운전자 요인 (선택 질문, 당사자마다 한 화면):
  parties.<id>.driver_factors      12대 중과실 중 영상 밖의 것(무면허, 음주·약물, 과속)과 현저한 과실(휴대전화,
                                   한눈팔기, 짙은 썬팅), 난폭·공동위험 → B의 user_factors, speed_over_limit_kmh
  parties.<id>.damage_severity     이륜차 당사자의 피해 정도 → 이륜차 감산 (경미하면 감산 없음)
12대 중과실 중 영상·장면 질문으로 받는 것: 신호위반(신호 색), 중앙선 침범·앞지르기(특수 상황), 보도 침범(특수 상황),
횡단보도 보행자 보호(보행자 장), 화물 고정(짐 떨어짐). 철길 건널목·승객 추락·어린이보호구역은 판정 모듈에
과실비율 조정 규칙이 없어서 묻지 않음 (형사 책임 쪽이라 비율이 안 바뀜)
"""

from src.app import chapters

STOP_STATE_OPTIONS = ["driving", "accident_stop", "parked"]
STOP_STATE_CHOICES = ["신호·정체로 잠깐 멈춤", "앞서 난 사고 때문에 멈춤", "주차·정차해 있었음"]
U_TURN_OPTIONS = ["always", "signal"]
U_TURN_CHOICES = ["상시 유턴 구역 (유턴 표지만 있음)", "신호에 따라 유턴 (유턴 신호가 있음)"]
OVERTAKE_OPTIONS = ["center_solid", "right_side", "no_passing_zone", "center_in_congestion",
                    "close_range_center_dashed", "white_solid", "around_stopped"]
OVERTAKE_CHOICES = ["노란 실선 중앙선을 넘어 앞지름", "같은 차로에서 오른쪽으로 파고들어 앞지름", "앞지르기 금지 장소에서 왼쪽으로 앞지름",
                    "막힌 길에서 중앙선을 넘어 앞지름", "노란 점선 중앙선을 넘어 바짝 앞지름", "흰색 실선을 넘어 앞지름",
                    "서 있던 차를 돌아서 앞지름"]
LANE_MARK_OPTIONS = ["left_only", "straight_left", "straight_only", "straight_right", "right_only", "unknown"]
LANE_MARK_CHOICES = ["좌회전만", "직진·좌회전", "직진만", "직진·우회전", "우회전만", "없음·모름"]

# 특수 상황: 있었다/없었다로 끝나는 드문 사실을 질문 하나로 (여러 개 고르기). 보기 값은 "키:당사자" 또는 장면 키.
# 상황(context)에 맞는 보기만 보여 준다: always / same(같은 방향) / opposite(마주 오는 방향) / straight_at_int(교차로 직진).
# 답하면 보여 준 보기 중 고른 것은 true, 안 고른 것은 false로 넘긴다. 대부분 해당 없음이라 답하지 않아도 결과가
# 완료로 나오는 선택 질문(optional)이다.
# B 사실 이름이 "movement=값"이면 진행 방향을 그 값으로, None이면 다음 질문을 여는 표시만 (앞지르기 → 유형 질문)
SPECIAL = [   # (키, B 사실, 보기 글자, 상황)
    ("emergency", "is_emergency", "{t}번이 긴급 출동 중인 긴급자동차 (경광등·사이렌)", "always"),
    ("one_way", "one_way_violation", "{t}번이 일방통행 길을 거꾸로 들어감", "always"),
    ("door", "door_opening", "{t}번이 서 있다가 문을 열었음", "always"),
    ("cargo", "dropped_cargo", "{t}번 차에서 짐이 떨어짐", "always"),
    ("bus_stop", "at_bus_stop", "{t}번이 버스정류장에서 출발한 버스", "always"),
    ("off_road", "from_off_road", "{t}번이 도로가 아닌 곳(주차장·건물 입구 등)에서 도로로 나옴", "always"),
    ("reverse", "movement=reverse", "{t}번이 후진하던 중", "always"),
    ("lane_change", "movement=lane_change", "{t}번이 차로를 바꾸던 중", "same"),
    ("cut_in", "cut_in", "{t}번이 뒤에서 오른쪽 좁은 틈으로 끼어듦", "same"),
    ("congested", "from_congested_lane", "{t}번이 막힌 차로에서 기다리다 갑자기 차로를 바꿈", "same"),
    ("merging", "merging", "{t}번 차로가 줄어드는 곳(합류)이었음", "same"),
    ("lc_first", "lane_change_first", "{t}번이 같은 차로 뒤에 있다가 먼저 차로를 바꿈", "same"),
    ("overtake", None, "{t}번이 앞지르기를 하던 중", "same"),
    ("to_shoulder", "to_shoulder", "{t}번이 갓길로 차로를 바꿈", "same"),
    ("safety_zone", "through_safety_zone", "{t}번이 안전지대(바닥에 빗금 친 곳)를 지나 달림", "same"),
    ("center", "crossed_center_line", "{t}번이 중앙선을 넘음", "opposite"),
    ("wrong_way", "wrong_way", "{t}번이 중앙선을 넘어 거꾸로 달림 (역주행)", "opposite"),
    ("lc_in_int", "lane_change_in_intersection", "{t}번이 교차로 안에서 차로를 바꿈", "straight_at_int"),
    ("to_off_road", "to_off_road", "{t}번이 도로가 아닌 곳(주차장·건물 입구 등)으로 우회전해 들어감", "always"),
    # 대형차 가산: 차대차는 차 자체가 대형인지(자동차관리법 시행규칙 별표 1). 사람들이 떠올리는 대형차로 묻고,
    # 2,000cc 승용 기준은 넣지 않음. 탐지가 트럭·버스면 미리 골라 둠 (special_question). 고르면 damage_enlarged를 물음
    ("large", "is_large", "{t}번이 버스·덤프트럭·5톤 이상 화물차 같은 대형차", "always"),
    # 영상으로 기준을 못 정한 수정요소 (docs/facts_plan.md 6절): 측정 대신 보기로 받음
    ("blocking", "entered_congested_intersection", "{t}번이 막혀 있는 교차로에 들어감 (꼬리물기)", "intersection"),
    ("turn_done", "turn_almost_completed", "{t}번이 좌회전을 거의 끝낸 뒤 부딪힘", "turn"),
    ("wide_turn", "wide_turn", "{t}번이 크게 돌아서 회전함 (바깥쪽으로 넓게)", "turn"),
    ("narrow_turn", "narrow_turn", "{t}번이 안쪽으로 바짝 붙어 회전함 (좁게)", "turn"),
    ("no_lights", "low_visibility_no_care", "{t}번이 밤·비·안개인데 전조등을 안 켰거나 속도를 안 줄임", "always"),
    # 이륜차 특수 (차61): 그 당사자가 이륜차일 때만 보기
    ("queue", "between_congested_queue", "{t}번(이륜차)이 막힌 차들 오른쪽 좁은 틈으로 직진함", "two_wheeler"),
    ("sidewalk", "on_sidewalk", "{t}번(이륜차)이 보도(인도)로 달림", "two_wheeler"),
    ("pass_right", "passing_on_right", "{t}번(이륜차)이 서 있는 차 오른쪽으로 지나감", "two_wheeler"),
    ("parking_arrow", "against_parking_arrow", "{t}번이 주차장 바닥 화살표와 반대로 달림", "parking_lot"),
    # 12대 중과실 보도 침범: 이륜차 말고 차도 (차43 등의 갓길경계선·인도 침범 +10)
    ("sidewalk_cross", "crossed_shoulder_or_sidewalk", "{t}번이 갓길 경계선이나 인도를 넘어 달림", "always"),
    # 11-02 점검: 판정 모듈 수정요소 중 A가 한 번도 못 넘기던 것 (docs/facts_plan.md 8절). 상황은 당사자별로
    # (left/right/uturn/lane_change/stopped/door/door_other, party_contexts) 그 당사자에게만 보임
    ("sudden_turn", "sudden_turn", "{t}번이 상대가 가까이 왔을 때 갑자기 회전함", "turn"),
    ("left_banned", "left_turn_prohibited_violation", "{t}번이 좌회전 금지 장소에서 좌회전함", "left"),
    ("left_method", "left_turn_method_violation", "{t}번이 교차로 중심 안쪽으로 돌지 않고 좌회전함", "left"),
    ("right_method", "right_turn_method_violation", "{t}번이 도로 오른쪽 가장자리를 따라 돌지 않고 우회전함", "right"),
    ("u_outside", "u_turn_outside_zone", "{t}번이 유턴 구역을 벗어나 유턴함", "uturn"),
    ("sudden_lc", "sudden_lane_change", "{t}번이 갑자기 차로를 바꿈", "lane_change"),
    ("banned_lc", "forbidden_lane_change", "{t}번이 차로 변경 금지 구간(흰색 실선 등)에서 차로를 바꿈", "lane_change"),
    ("forced_cut", "forced_cut_in", "{t}번이 무리하게 끼어들어 진로를 막음", "lane_change"),
    ("signaled_first", "signaled_lane_change_first", "{t}번이 상대보다 먼저 방향지시등으로 차로 변경을 알림", "same"),
    ("bus_lane", "bus_lane_violation", "{t}번이 버스전용차로로 달림", "same"),
    ("sudden_stop", "sudden_stop_without_reason", "{t}번이 이유 없이 갑자기 섰음", "same"),
    ("tailgating", "unsafe_distance", "{t}번이 앞차와 너무 가까이 붙어 달림", "same"),
    ("brake_light", "brake_light_failure", "{t}번 브레이크등이 고장 나 있었음", "same"),
    ("no_fault_stop", "no_fault_in_stopping", "{t}번은 어쩔 수 없이 서 있었음 (고장·앞선 사고 등)", "stopped"),
    ("hazard", "hazard_lights_on", "{t}번이 서 있을 때 비상등을 켜 두었음", "stopped"),
    ("warning_sign", "warning_sign_installed", "{t}번이 서 있을 때 고장 표지(삼각대 등)를 세워 두었음", "stopped"),
    ("no_evacuate", "could_not_evacuate", "{t}번이 사고 뒤 차를 빼거나 피할 수 없는 상황이었음", "stopped"),
    ("bad_parking", "improper_parking", "{t}번이 주정차 방법을 어김 (오른쪽 끝에 안 붙임 등)", "stopped"),
    ("banned_parking", "parking_prohibited_place", "{t}번이 주정차 금지 장소에 서 있었음", "stopped"),
    ("door_traffic", "door_toward_traffic", "{t}번이 차가 다니는 쪽 문을 열었음", "door"),
    ("door_sudden", "sudden_door_open", "{t}번이 문을 갑자기 확 열었음", "door"),
    ("door_stop", "door_at_transit_stop", "{t}번이 버스·택시 승강장에서 문을 열었음", "door"),
    ("door_foresee", "door_open_foreseeable", "{t}번은 앞차 문이 열릴 걸 미리 알 수 있었음", "door_other"),
    ("view_blocked", "view_obstructed", "{t}번 쪽에서 건물·큰 차 때문에 상대가 안 보였음", "always"),
    ("evasive", "evasive_action", "{t}번이 부딪히기 전에 피하려고 속도를 줄이거나 방향을 틀었음", "always"),
    ("school_bus", "is_school_bus", "{t}번이 어린이통학버스", "always"),
    # 적신호 직전 진입 (신호 교차로): 신호등을 연결했으면 색 기록으로 미리 골라 둠 (pipeline.signal_guesses)
    ("late_red", "entered_just_before_red", "{t}번이 노란불에 들어가서 곧 빨간불이 됨", "signal"),
]
PARTY_CONTEXTS = {"two_wheeler", "left", "right", "uturn", "lane_change", "stopped", "door", "door_other"}
# 특수 상황 보기를 앱이 묶어 보여 줄 제목 (보기가 상황별로 10~20개라 한 목록이면 찾기 어려움)
OPTION_GROUPS = {"always": "일반", "same": "같은 방향으로 가다가", "opposite": "마주 오다가", "straight_at_int": "교차로",
                 "intersection": "교차로", "turn": "회전", "left": "회전", "right": "회전", "uturn": "회전",
                 "lane_change": "차로 변경", "stopped": "서 있던 차", "door": "문 열림", "door_other": "문 열림",
                 "two_wheeler": "이륜차", "parking_lot": "주차장", "signal": "신호"}
SCENE_GROUP = "장소·날씨"
# 운전자 요인 (영상으로 알 수 없음). 보기 값 → B user_factors 값. 과속 두 보기는 speed_over_limit_kmh로
DRIVER_FACTORS = [
    ("drunk_0.03_plus", "음주 (혈중알코올 0.03% 이상)"),
    ("drunk_under_0.03", "음주 (0.03% 미만)"),
    ("drugs", "약물 복용"),
    ("no_license", "무면허"),
    ("speed_20plus", "제한속도보다 시속 20km 이상 빨랐음"),
    ("speed_under20", "제한속도보다 조금(시속 20km 미만) 빨랐음"),
    ("phone", "운전 중 휴대전화 사용·영상 시청"),
    ("inattention", "졸음·한눈팔기 등으로 앞을 제대로 안 봄"),
    ("dark_tint", "밤·비 오는 날 짙은 썬팅 차량"),
    ("reckless", "난폭운전 (위반을 연달아·반복)"),
    ("group_danger", "여러 대가 줄지어 위험하게 운전 (공동위험)"),
]
SPEED_OVER = {"speed_20plus": 25, "speed_under20": 10}   # B는 시속 초과량(km/h)으로 받음: 20 이상 +20, 미만 +10
DAMAGE_OPTIONS = ["minor", "moderate", "severe"]
DAMAGE_CHOICES = ["경미 (긁힘, 가벼운 찰과상)", "중간", "큼 (중상, 크게 파손)"]
PLACE_NAMES = {"intersection": "교차로", "roundabout": "회전교차로", "parking_lot": "주차장", "straight": "교차로 아닌 길"}
ROUNDABOUT_ACTIONS = ["circulating", "entering", "exiting_lane_change"]
ROUNDABOUT_CHOICES = ["회전교차로 안에서 돌고 있었음", "회전교차로로 들어오던 중", "돌다가 바깥 차로로 바꿔 나가던 중"]
PARKING_ACTIONS = ["aisle", "leaving", "entering"]
PARKING_CHOICES = ["통로를 달리던 중", "주차 칸에서 나오던 중", "주차 칸으로 들어가던 중"]
PARKING_FACTS = {"aisle": "in_parking_aisle", "leaving": "leaving_parking_space", "entering": "entering_parking_space"}
EMERGENCY_MODES = ["normal", "left_side", "overtaking"]
EMERGENCY_CHOICES = ["보통으로 달림", "도로 가운데·왼쪽으로 달림", "앞차를 앞지르던 중"]
POSITION_OPTIONS = ["lane", "shoulder", "road_edge"]
POSITION_CHOICES = ["차로 안", "갓길", "도로 가장자리"]
# (키, 장면 사실, 고르면, 안 고르면, 보기 글자). 안 고르면 값이 None이면 안 넘김 (다른 답이 정한 값을 덮지 않게)
SPECIAL_SCENE = [("highway", "road_type", "highway", "general", "고속도로·자동차전용도로였음"),
                 ("night", "night", True, False, "밤이었음"),
                 ("low_vis", "low_visibility", True, False, "비·눈·안개 등으로 앞이 잘 안 보였음"),
                 # 골목길: AI Hub 정답 폴더가 없어서 질문으로만 받음. 중앙선 답(road.center_line)이 정한 값을 덮지 않게 안 고르면 그대로
                 ("side_street", "road_class", "side_street", None, "골목길(중앙선 없는 좁은 길)이었음")]

# 답이 무엇이든 판정이 같으면 지우는 질문 (중앙선과 같은 방법). 당사자 질문은 field 끝부분으로 봄.
# 앞차(pair.lead_order)와 서 있던 이유(stop_state)는 빼야 한다: 그 답이 있어야 다음 질문(차로 폭 등)이 생겨서
# 혼자서는 판정을 못 바꾼다 (cc_200507: 앞차를 답해야 차19-1 후보가 뜨고, 차로 폭까지 답해야 판정이 나옴)
DROP_IF_SAME = {"road.center_line", "road.stop_sign_side", "road.lane_fits_two", "intersection_entry_clear",
                "pair.u_turn_timing", "road.center_line_rule_not_applied", "road.location", "pair.right_side"}
# 회전교차로·주차장 질문도 지우지 않음: 두 당사자 답이 다 있어야 차54·51이 골라져서 하나만 바꿔 보면 늘 같음
# 바닥 화살표(lane_marking)도 빼야 한다: 차11은 두 차의 화살표가 다 있어야 골라져서 한쪽만 바꿔 보면 늘 같음
DROP_IF_SAME_PARTY = {"unprotected_left_sign", "u_turn_type", "lane_change_dir", "overtake_type", "damage_severity",
                      "turn_signal_used", "slowed_before_entry",
                      "ped_signal_green_at_turn", "position", "in_safety_zone_at_collision", "emergency_mode"}
# damage_enlarged(대형차 인과관계)는 지우지 않음: 지금 B 조건(cls)으로는 판정이 안 바뀌어도, 답을 넘겨서 B가 쓸지 정하게


def droppable(field):
    return field in DROP_IF_SAME or (field.startswith("parties.") and field.split(".")[-1] in DROP_IF_SAME_PARTY)


def special_chosen(user):
    return set(map(str, user.get("situation.special") or []))


def effective(facts, user, tid, key):
    """당사자 값: 사용자 답 > 특수 상황 답(진행 방향) > 확정값 > 추정값"""
    if f"parties.{tid}.{key}" in user:
        return user[f"parties.{tid}.{key}"]
    if key == "movement":
        for k, fact, _, _ in SPECIAL:
            if fact and fact.startswith("movement=") and f"{k}:{tid}" in special_chosen(user):
                return fact.split("=", 1)[1]
    p = facts["parties"][tid]
    v = p.get(key)
    if v in (None, "unknown") and key == "movement":
        return p.get("movement_guess")
    return v


def contexts(facts, user, mv, at_intersection):
    """특수 상황 보기를 고를 상황. 방향을 모르면 같은 방향·마주 오는 방향 보기를 둘 다 보여 줌"""
    a, b = facts["collision"]["a"], facts["collision"]["b"]
    lead = {t: effective(facts, user, t, "lead_order") for t in (a, b)}
    came = {t: effective(facts, user, t, "entry_from") for t in (a, b)}
    same = (any(facts["parties"][t].get("same_direction") for t in (a, b))
            or bool(came[a] and came[a] == came[b]) or any(lead.values())
            or user.get("pair.lead_order") in (a, b, "side_by_side"))
    opposite = any(facts["parties"][t].get("opposite_direction") for t in (a, b))
    known = same or opposite or any(facts["parties"][t].get("same_direction") is False for t in (a, b))
    ctx = {"always"}
    if same or not known:
        ctx.add("same")
    if opposite or not known:
        ctx.add("opposite")
    if at_intersection and any(mv[t] == "straight" for t in (a, b)):
        ctx.add("straight_at_int")
    if (facts.get("road") or {}).get("location") == "parking_lot":
        ctx.add("parking_lot")
    if at_intersection:
        ctx.add("intersection")
    if user.get("road.signal_present") is True:
        ctx.add("signal")
    if any(mv[t] in ("left_turn", "right_turn", None, "unknown") for t in (a, b)):   # 회전 보기 (방향 모르면 보여 줌)
        ctx.add("turn")
    return ctx, same, opposite


def questions(facts, user):
    a, b = facts["collision"]["a"], facts["collision"]["b"]
    f0 = facts["collision"]["frame"]
    # 보행자·자전거 사고는 차대차 도표가 아니므로 묻지 않음 (src/app/chapters.py)
    if chapters.chapter(effective(facts, user, t, "cls") for t in (a, b)) != "vehicle":
        return []
    at_intersection = (facts.get("road") or {}).get("location") == "intersection"
    mv = {t: effective(facts, user, t, "movement") for t in (a, b)}
    # 같은 방향 사고인지: 궤적상 같은 방향이거나, 두 차가 같은 길에서 들어옴. 앞뒤·서 있던 이유는 이때만 물음
    # (교차하다 부딪힌 사고에서 한쪽이 서 있었다고 묻지 않게, cc_160316)
    ctx, same, opposite = contexts(facts, user, mv, at_intersection)
    lead = {t: effective(facts, user, t, "lead_order") for t in (a, b)}
    signal = user.get("road.signal_present")
    chosen = special_chosen(user)
    out = []

    def ask(field, question, options, choices, frame=f0, **extra):
        if any(q["field"] == field for q in out):   # 같은 질문이 두 곳에서 생길 때 (주차장 앞차 등)
            return
        out.append({"field": field, "question": question, "answer_type": "choice", "options": options,
                    "choices": choices, "model_guess": None, "evidence_frame": frame, **extra})

    # 충돌이 교차로 영역 밖(진입로)에서 났으면 교차로 안이었는지 물음. 마주 오는 사고(차31·32)는 장소가 교차로가
    # 아니어야 골라진다. 영역만 보고 바꾸지 않는 건, 모서리를 손으로 찍어 경계가 어긋날 때가 있어서
    # (cc_191207은 충돌이 진입로 영역인데 교차로 도표로 정답과 같았음)
    if at_intersection and facts["collision"].get("zone") not in (None, "intersection"):
        ask("road.location", "부딪힌 곳은 교차로 안이었나요?", ["intersection", "straight"],
            ["교차로 안", "교차로를 벗어난 길"], model_guess="intersection", default=True)
    if at_intersection:
        ask("road.stop_sign_side", "일시정지 표지(또는 바닥의 '정지' 글자)가 있던 길은 어느 쪽인가요?",
            ["none", a, b, "both"], ["없음", f"{a}번 차가 온 길", f"{b}번 차가 온 길", "양쪽 다"], f0,   # 충돌 장면 (0프레임엔 당사자가 안 보일 때가 많음)
            model_guess="none", default=True, depends_on={"road.signal_present": False})
        for t in (a, b):
            if mv[t] == "left_turn":
                ask(f"parties.{t}.unprotected_left_sign", f"{t}번 차가 좌회전한 곳에 '비보호 좌회전' 표지가 있었나요?",
                    [True, False], ["있음", "없음"], depends_on={"road.signal_present": True})
            if mv[t] == "right_turn":
                ask(f"parties.{t}.ped_signal_green_at_turn",
                    f"{t}번 차가 우회전할 때, 건너던 횡단보도의 보행자 신호가 초록이었나요?",
                    [True, False], ["초록이었음", "아니었음"], depends_on={"road.signal_present": True})
            # 서행: 비신호 교차로 도표 42개의 "서행 -10 / 서행·감속 불이행 +10". 화면으로는 km/h를 몰라서 묻고,
            # 확실할 때만 추정값을 넣음 (src/app/slowdown.py, pipeline.slow_guesses). 판정이 같으면 지움
            ask(f"parties.{t}.slowed_before_entry", f"{t}번 차는 교차로에 들어가기 전에 속도를 줄였나요?",
                [True, False], ["줄였음 (또는 멈췄음)", "안 줄였음"], depends_on={"road.signal_present": False})
            # 바닥 화살표: 차로 노면표시 위반(차11)에만 쓰여서 선택 질문으로 (모르면 넘어가도 됨)
            ask(f"parties.{t}.lane_marking", f"{t}번 차가 있던 차로 바닥의 화살표는 무엇이었나요?",
                LANE_MARK_OPTIONS, LANE_MARK_CHOICES, optional=True, group="도로 표시")
    for t in (a, b):
        if mv[t] == "u_turn":
            ask(f"parties.{t}.u_turn_type", f"{t}번 차가 유턴한 곳은 어떤 곳인가요?", U_TURN_OPTIONS, U_TURN_CHOICES)
        if mv[t] == "lane_change":
            ask(f"parties.{t}.lane_change_dir", f"{t}번 차는 어느 쪽 차로로 바꿨나요?", ["left", "right"],
                ["왼쪽 차로로", "오른쪽 차로로"])
        # 방향지시등: CCTV로는 안 보임. 진로 변경·회전 도표 40여 개의 "신호 불이행 +10"에 쓰여서, 회전·차로 변경·유턴한
        # 당사자에게만 묻고 판정이 안 바뀌면 지움 (DROP_IF_SAME_PARTY)
        if mv[t] in ("left_turn", "right_turn", "u_turn", "lane_change") or f"lane_change:{t}" in chosen:
            ask(f"parties.{t}.turn_signal_used", f"{t}번 차는 방향지시등을 켰나요?", [True, False],
                ["켰음", "안 켰거나 늦게 켰음"])
        if f"overtake:{t}" in chosen:
            ask(f"parties.{t}.overtake_type", f"{t}번 차는 어떻게 앞지르기를 했나요?", OVERTAKE_OPTIONS, OVERTAKE_CHOICES)
        p = facts["parties"][t]
        if same and p.get("stopped_before_collision") and p.get("stop_state") is None:
            ask(f"parties.{t}.stop_state", f"{t}번 차는 부딪히기 전에 서 있었어요. 왜 서 있었나요?",
                STOP_STATE_OPTIONS, STOP_STATE_CHOICES)
    if mv[a] == "u_turn" and mv[b] == "u_turn":
        ask("pair.u_turn_timing", "두 차가 유턴한 때는 어땠나요?", ["sudden", "simultaneous"],
            ["뒤차가 갑자기 유턴함", "거의 같이 유턴함"])
    if opposite and user.get("road.center_line") is True:
        ask("road.center_line_rule_not_applied", "중앙선은 있지만, 길이 좁아서 마주 오는 차와 서로 비켜 가야 하는 길이었나요?",
            [True, False], ["그런 길이었음", "아니었음"])

    # 같은 방향인데 궤적으로 앞뒤를 못 정했으면 물음 (서 있는 차를 뒤에서 들이받은 모양은 궤적으로 정함)
    if not any(lead.values()) and same:
        ask("pair.lead_order", "두 차가 같은 방향으로 가고 있었다면, 앞에 있던 차는 어느 쪽인가요?",
            [a, b, "side_by_side", "not_same_direction"],
            [f"{a}번", f"{b}번", "나란히 가고 있었음 (앞뒤 없음)", "같은 방향이 아니었음"])
    # 나란히 가다 같은 쪽으로 회전(차20 동시 우회전, 차21 동시 좌회전)은 누가 오른쪽 차인지로 도표·역할이 정해짐.
    # 궤적으로 좌우를 못 정했으면 물음 (cc_200507: 한 차가 부딪힌 순간에야 처음 잡혀서 좌우를 못 잼)
    side = {t: effective(facts, user, t, "side_in_pair") for t in (a, b)}
    both_turn = mv[a] == mv[b] and mv[a] in ("left_turn", "right_turn")
    if same and not any(side.values()) and (user.get("pair.lead_order") == "side_by_side" or both_turn):
        ask("pair.right_side", "두 차 중 오른쪽에 있던 차는 어느 쪽인가요?", [a, b], [f"{a}번", f"{b}번"])
    leading = any(v == "leading" for v in lead.values()) or user.get("pair.lead_order") in (a, b)
    if at_intersection and leading and any(mv[t] in ("left_turn", "right_turn") for t in (a, b)):
        ask("road.lane_fits_two", "두 차가 있던 차로는 차 2대가 나란히 지날 만큼 넓었나요?", [True, False],
            ["넓었음", "아니었음"])
    # 진입 순서를 답으로 받았으면(측정을 못 믿을 때만 묻는 질문) 얼마나 먼저였는지. "명확한 선진입"(B 수정요소,
    # 차12 선진입·후진입)을 가름. 답이 없으면 명확하지 않은 것으로 봄 (answers.to_assumptions)
    ask("intersection_entry_clear", "먼저 들어간 차는 확실히 먼저였나요?", [True, False],
        ["확실히 먼저 (상대가 오기 전에 이미 들어와 있었음)", "조금 먼저 (거의 같이 들어옴)"],
        model_guess=False, default=True, depends_on={"intersection_entry_order": [a, b]})
    place_questions(facts, user, ask, a, b)
    follow_ups(facts, user, ask, a, b, chosen)
    cls = {t: effective(facts, user, t, "cls") for t in (a, b)}
    out.append(special_question(a, b, f0, ctx, cls, party_contexts(facts, user, a, b, mv, chosen, cls)))
    out += driver_questions(facts, user, ask, a, b)
    return out


def driver_questions(facts, user, ask, a, b):
    """영상으로 알 수 없는 운전자 요인. 선택 질문이라 안 골라도 결과가 나옴 (고르지 않은 것은 해당 없음으로 봄).
    당사자는 상대에 대해 모를 수 있고, 자기에게 유리하게 답할 수도 있어서 결과에는 사용자 입력으로 남는다"""
    out = []
    f0 = facts["collision"]["frame"]
    for t in (a, b):
        out.append({"field": f"parties.{t}.driver_factors",
                    "question": f"{t}번 운전자에게 해당하는 것이 있으면 골라 주세요 (모르면 넘어가도 돼요)",
                    "answer_type": "multi", "options": [k for k, _ in DRIVER_FACTORS],
                    "choices": [c for _, c in DRIVER_FACTORS], "model_guess": [], "default": True,
                    "optional": True, "evidence_frame": f0, "group": "운전자 요인"})
        if effective(facts, user, t, "cls") == "two_wheeler":   # 이륜차 감산은 피해 정도로 (경미하면 없음)
            ask(f"parties.{t}.damage_severity", f"{t}번(이륜차) 쪽 피해(부상·파손)는 어느 정도였나요?",
                DAMAGE_OPTIONS, DAMAGE_CHOICES)
    return out


def place_questions(facts, user, ask, a, b):
    """회전교차로·주차장·교차로 아닌 길: 장소 종류는 모서리 단계에서 받고(pipeline.set_scene의 place), 그 장소의
    도표에 필요한 것을 묻는다. 영상으로는 회전 차로·주차 칸을 알아볼 수 없어서 모두 질문"""
    place = (facts.get("road") or {}).get("location")
    if place == "roundabout":   # 차54
        ask("road.roundabout_lanes", "회전교차로의 회전 차로는 몇 개였나요?", ["single", "multi"], ["1개", "2개 이상"])
        multi = user.get("road.roundabout_lanes") == "multi"
        for t in (a, b):
            ask(f"parties.{t}.roundabout_action", f"{t}번 차는 회전교차로에서 무엇을 하고 있었나요?",
                ROUNDABOUT_ACTIONS, ROUNDABOUT_CHOICES)
            act = user.get(f"parties.{t}.roundabout_action")
            if multi and act in ("circulating", "entering"):
                ask(f"parties.{t}.roundabout_lane", f"{t}번 차가 {'돌던' if act == 'circulating' else '들어간'} 회전 차로는?",
                    [1, 2], ["1차로 (안쪽)", "2차로 (바깥쪽)"])
            if multi and act == "entering":
                ask(f"parties.{t}.entry_lane_from", f"{t}번 차는 들어오기 전 몇 차로에 있었나요?", [1, 2],
                    ["1차로 (왼쪽)", "2차로 (오른쪽)"])
                ask(f"parties.{t}.big_entry", f"{t}번 차는 회전 1차로로 곧바로 크게 들어갔나요?", [True, False],
                    ["그랬음", "아니었음"])
    elif place == "parking_lot":   # 차51
        for t in (a, b):
            ask(f"parties.{t}.parking_action", f"{t}번 차는 주차장에서 무엇을 하고 있었나요?", PARKING_ACTIONS, PARKING_CHOICES)
        acts = {t: user.get(f"parties.{t}.parking_action") for t in (a, b)}
        lead_known = any(effective(facts, user, t, "lead_order") for t in (a, b)) or "pair.lead_order" in user
        if "entering" in acts.values() and "aisle" in acts.values() and not lead_known:   # 차51-2
            ask("pair.lead_order", "두 차 중 앞에 있던 차는 어느 쪽인가요?", [a, b, "not_same_direction"],
                [f"{a}번", f"{b}번", "같은 방향이 아니었음"])
    elif place == "straight":   # 교차로가 아닌 길: 마주 오는 사고(차31·32)에 중앙선이 쓰임 (교차로는 build_facts가 물음)
        ask("road.center_line", "사고 난 길에 중앙선(가운데 노란 선)이 있나요?", [True, False], ["있음", "없음"])


def follow_ups(facts, user, ask, a, b, chosen):
    """앞 답에 따라 생기는 질문: 서 있던·달리던 곳(갓길 등), 안전지대, 긴급자동차가 달린 방식"""
    for t in (a, b):
        other = b if t == a else a
        # 차42: 주정차한 곳 / 차43-6: 상대가 갓길로 차로를 바꿨으면 이쪽이 갓길을 달렸는지
        if user.get(f"parties.{t}.stop_state") in ("parked", "accident_stop") or f"to_shoulder:{other}" in chosen:
            ask(f"parties.{t}.position", f"{t}번 차가 {'달리던' if f'to_shoulder:{other}' in chosen else '서 있던'} 곳은 어디였나요?", POSITION_OPTIONS, POSITION_CHOICES)
        if f"safety_zone:{t}" in chosen:   # 차43-7
            ask(f"parties.{t}.in_safety_zone_at_collision", f"부딪힐 때 {t}번 차는 아직 안전지대 안이었나요?",
                [True, False], ["안이었음", "벗어난 뒤였음"])
        if f"emergency:{t}" in chosen:   # 차55
            ask(f"parties.{t}.emergency_mode", f"긴급자동차({t}번)는 어떻게 달리고 있었나요?", EMERGENCY_MODES,
                EMERGENCY_CHOICES)
        if f"large:{t}" in chosen:   # 대형차 가산은 사고와 인과관계가 있을 때만
            ask(f"parties.{t}.damage_enlarged", f"{t}번 차가 커서 사고가 나거나 피해가 커졌나요? (교차로를 지나는 데 오래 걸림, 피하기 어려웠음 등)",
                [True, False], ["그랬음", "아니었음"])


def party_contexts(facts, user, a, b, mv, chosen, cls):
    """당사자별 상황 (그 당사자에게만 보이는 특수 상황 보기). 진행 방향을 모르면 회전 보기를 다 보여 줌"""
    out = {t: set() for t in (a, b)}
    for t in (a, b):
        other = b if t == a else a
        if cls.get(t) == "two_wheeler":
            out[t].add("two_wheeler")
        m = mv[t] if f"lane_change:{t}" not in chosen else "lane_change"
        out[t] |= {"left_turn": {"left"}, "right_turn": {"right"}, "u_turn": {"uturn"},
                   "lane_change": {"lane_change"}, None: {"left", "right"}, "unknown": {"left", "right"}}.get(m, set())
        if (user.get(f"parties.{t}.stop_state") in ("parked", "accident_stop")
                or facts["parties"][t].get("stationary_at_collision")):
            out[t].add("stopped")
        if f"door:{t}" in chosen:
            out[t].add("door")
        if f"door:{other}" in chosen:
            out[t].add("door_other")
    return out


def special_options(a, b, ctx=None, cls=None, pctx=None, groups=False):
    """(보기 값, 보기 글자) 목록. ctx가 없으면 모든 보기 (답 검사용). 당사자별 상황(PARTY_CONTEXTS) 보기는
    그 상황인 당사자에게만 (pctx가 없으면 이륜차 보기만 cls로 판단). groups면 (값, 글자, 묶음 제목)"""
    out = []
    pctx = pctx or {t: ({"two_wheeler"} if (cls or {}).get(t) == "two_wheeler" else set()) for t in (a, b)}
    for key, _, text, c in SPECIAL:
        for t in (a, b):
            if ctx is None or (c in PARTY_CONTEXTS and c in pctx.get(t, ())) or (c not in PARTY_CONTEXTS and c in ctx):
                out.append((f"{key}:{t}", text.format(t=t), OPTION_GROUPS.get(c, "일반")))
    out += [(key, text, SCENE_GROUP) for key, _, _, _, text in SPECIAL_SCENE]
    return out if groups else [(o, c) for o, c, _ in out]


# 이 사건에서는 드문 보기 (11-04). 보여 주기는 하되 앱이 "다른 상황 더 보기" 아래로 접어 둠.
# 트럭·승용차 교차로 사고에 버스정류장·주차장 보기가 맨 앞에 나와서 고를 게 너무 많아 보였음.
# 탐지가 틀릴 수 있어서(승합차를 truck으로 등) 아예 빼지는 않음. 접힌 보기를 골라도 똑같이 반영됨
BUS_ONLY = {"bus_stop", "school_bus"}        # 그 당사자가 버스로 잡혔을 때만 펼침
LARGE_ONLY = {"large"}                       # 트럭·버스로 잡혔을 때만 펼침
NOT_AT_INTERSECTION = {"off_road", "to_off_road", "highway"}   # 교차로 사고면 접음 (주차장·건물 입구, 고속도로)


def rare_option(opt, ctx, cls=None, pctx=None):
    """보기 값("키:당사자" 또는 장면 키)이 이 사건에서 드문지"""
    key, _, t = str(opt).partition(":")
    c = (cls or {}).get(t)
    if key in BUS_ONLY:
        return c != "bus"
    if key in LARGE_ONLY:
        return c not in ("truck", "bus")
    if key in NOT_AT_INTERSECTION:
        return "intersection" in ctx
    if key == "door":   # 서 있던 차가 아니면 문 열림 사고는 드묾
        return not ({"stopped", "door"} & set((pctx or {}).get(t, ())))
    return False


def special_question(a, b, f0, ctx, cls=None, pctx=None):
    shown = special_options(a, b, ctx, cls, pctx, groups=True)
    # 트럭·버스로 잡힌 당사자는 대형차 보기를 미리 골라 둠 (1톤 트럭도 truck이라 사용자가 고칠 수 있게 보여 줌)
    guess = [f"large:{t}" for t in (a, b) if (cls or {}).get(t) in ("truck", "bus")]
    return {"field": "situation.special", "question": "이 중에 해당하는 게 있으면 골라 주세요 (없으면 넘어가도 돼요)",
            "answer_type": "multi", "options": [o for o, _, _ in shown], "choices": [c for _, c, _ in shown],
            "option_groups": [g for _, _, g in shown],   # 보기마다 묶음 제목 (앱이 제목별로 나눠 보여 줌)
            "more_options": [o for o, _, _ in shown if rare_option(o, ctx, cls, pctx)],   # 앱이 "더 보기"로 접을 보기
            "group": "특수 상황",
            # 상황(같은 방향 등)이 다음 답에서 바뀌어 보기가 달라져도 전에 고른 답이 틀린 답이 되지 않게, 검사는 전체 보기로
            "all_options": [o for o, _ in special_options(a, b)],
            "model_guess": guess, "default": True, "optional": True, "evidence_frame": f0}


def special_assumptions(facts, val, party, scene):
    """특수 상황 답 → 당사자·장면 사실. 보여 준 보기 중 고른 것은 true, 안 고른 것은 false.
    진행 방향 보기(후진, 차로 변경)는 고른 것만 진행 방향으로 넘김"""
    chosen = set(map(str, val or []))
    q = next((u for u in facts.get("unknowns", []) if u["field"] == "situation.special"), None)
    shown = set(q["options"]) if q else {o for o, _ in special_options(facts["collision"]["a"], facts["collision"]["b"])}
    for t in (facts["collision"]["a"], facts["collision"]["b"]):
        for key, fact, _, _ in SPECIAL:
            opt = f"{key}:{t}"
            if fact is None or opt not in shown:
                continue
            if fact.startswith("movement="):
                if opt in chosen:
                    party(t)["movement"] = fact.split("=", 1)[1]
            else:
                party(t)[fact] = opt in chosen
    for key, fact, yes, no, _ in SPECIAL_SCENE:
        if key in chosen or no is not None:
            scene[fact] = yes if key in chosen else no
