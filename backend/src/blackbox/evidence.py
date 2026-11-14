"""판정에 쓴 답의 근거 문장 (bb-flow 2부)

차량 규칙은 자동 답변마다 evidence.text("사고 직전 3초 중 2.4초 동안 기어가 R(후진)이었어요")를 만든다.
영상·사용자·기본값으로 정한 답에도 같은 말투("~했어요")의 문장을 붙여, 앱이 문장을 만들지 않고 그대로 보여 주게 한다.

  sentence(field, value, question=None)          값 하나 → "내 차가 우회전했어요" (질문이 있으면 보기 이름을 씀)
  for_video(field, value, t, question=None)      "내 차가 우회전했어요 (17.5초)" (출처는 앱 배지가 보여 줌)
  for_video_guess(field, guess, t, question=None) "영상으로는 내 차가 우회전한 것 같아요 (17.5초, 추정)"
  for_user(field, value, question=None)          "상대가 승용차였어요 (직접 답했어요)"
  for_default(field, value, basis, question=None) "교차로에 신호등이 없었어요 (영상 추정)" / "… (기본값)"

값은 질문 키 기준(자기 차 기준 보기: left/right/opposite/same, mine/theirs)이다.
"""
from src.vehicle import adapter as va

PLACE = dict(zip(va.PLACES, va.PLACE_CHOICES))
JUNCTION = dict(zip(va.JUNCTIONS, va.JUNCTION_CHOICES))
CLS = dict(zip(va.OTHER_CLASSES, va.OTHER_CLASS_CHOICES), person="보행자")
ENTRY = {"left": "내 차 기준 왼쪽 길", "right": "내 차 기준 오른쪽 길", "opposite": "맞은편 길",
         "same": "같은 방향(내 차 앞이나 뒤)"}
MOVE_DONE = {"straight": "직진했어요", "left_turn": "좌회전했어요", "right_turn": "우회전했어요",
             "u_turn": "유턴했어요", "lane_change": "진로를 바꿨어요", "reverse": "후진했어요"}
MOVE_GUESS = {"straight": "직진한", "left_turn": "좌회전한", "right_turn": "우회전한", "u_turn": "유턴한",
              "lane_change": "진로를 바꾼", "reverse": "후진한"}
# 차량 신호 이름은 판정 엔진 이름 (analyzer.SIGNALS = build_facts.SIGNALS)
SIGNAL = dict(zip(va.SIGNALS, va.SIGNAL_NAMES))
WIDER = {"equal": "두 도로의 폭이 비슷했어요", "mine": "내 차가 달린 도로가 더 넓었어요",
         "theirs": "상대가 달린 도로가 더 넓었어요"}
ORDER = {"ego": "내 차가 먼저 교차로에 들어갔어요", "other": "상대가 먼저 교차로에 들어갔어요",
         "same_time": "두 차가 거의 동시에 교차로에 들어갔어요"}
STOP_SIGN = {"none": "일시정지 표지가 없었어요", "ego": "내 차가 온 길에 일시정지 표지가 있었어요",
             "other": "상대가 온 길에 일시정지 표지가 있었어요", "both": "양쪽 길 모두 일시정지 표지가 있었어요"}
LEAD = {"leading": "앞차였어요", "following": "뒤차였어요"}
DIR = {"left": "왼쪽", "right": "오른쪽"}
BASIS = {"video": "영상 추정", "vehicle": "차량 기록 추정", "default": "기본값", None: "기본값"}

# ---------- 보행자·자전거·도로 항목 (분석기 8.3.2·8.3.3, 장 질문 chapter.py). 필드 이름이 화면에 나오지 않게 ----------
PED_SIGNAL = {"green": "초록", "flashing_green": "초록 점멸", "red": "빨강"}
PLACE_WHERE = {"crosswalk": "횡단보도 위에 있었어요", "near_crosswalk": "횡단보도 근처에 있었어요",
               "near_overpass": "육교·지하도 부근에 있었어요", "intersection": "신호 없는 교차로를 건너던 중이었어요",
               "road": "교차로 아닌 길을 건너던 중이었어요", "sidewalk": "보도에 있었어요",
               "roadway": "차도를 따라 걷던 중이었어요", "ped_only_road": "보행자 전용도로에 있었어요",
               "ped_priority_road": "보행자 우선도로에 있었어요"}
CROSSWALK_DIST = {"on": "횡단보도 위에서 부딪혔어요", "within_10m": "횡단보도에서 10m 안쪽에서 부딪혔어요",
                  "10_30m": "횡단보도에서 10~30m 떨어진 곳에서 부딪혔어요",
                  "over_30m": "횡단보도에서 30m 넘게 떨어진 곳에서 부딪혔어요", "no_crosswalk": "근처에 횡단보도가 없었어요"}
OVERPASS_DIST = {"within_10m": "육교·지하도에서 10m 안쪽이었어요", "10_30m": "육교·지하도에서 10~30m 떨어진 곳이었어요",
                 "over_30m": "육교·지하도에서 30m 넘게 떨어진 곳이었어요"}
ENUM_SENTENCE = {
    "right_turn_signal": {"green": "우회전 신호등이 초록이었어요", "red": "우회전 신호등이 빨강이었어요",
                          "none": "우회전 신호등이 없었어요"},
    "ped_activity": {"crossing": "길을 건너던 중이었어요", "walking": "길을 따라 걷던 중이었어요",
                     "lying_or_playing": "차도에 눕거나 앉아 있었거나 놀던 중이었어요"},
    "crossing_road_width": {"narrower": "상대가 건넌 도로가 내 차가 달린 도로보다 좁았어요",
                            "equal": "상대가 건넌 도로가 내 차가 달린 도로와 폭이 비슷했어요",
                            "wider": "상대가 건넌 도로가 내 차가 달린 도로보다 넓었어요"},
    "roadway_walk_position": {"edge_1m": "길 가장자리에서 1m 안쪽을 걷고 있었어요",
                              "beyond_1m": "길 가장자리에서 1m 넘게 들어와 걷고 있었어요",
                              "edge": "길 가장자리를 걷고 있었어요", "center": "길 가운데를 걷고 있었어요"},
    "vulnerable_type": {"child": "어린이였어요", "elderly": "노인이었어요", "disabled": "장애인이었어요",
                        "none": "어린이·노인·장애인이 아니었어요"},
    "expressway_walk_reason": {"justified": "고속도로에 있던 이유가 있었어요 (고장·사고 등)",
                               "none": "고속도로에 있던 이유가 없었어요"},
    "walk_manner": {"normal": "보통 걸음으로 건넜어요", "stop": "건너다 멈춰 섰어요", "back": "건너다 되돌아갔어요",
                    "zigzag": "이리저리 비틀거리며 걸었어요"},
    "ped_posture": {"sitting": "앉아 있었어요", "lying": "누워 있었어요", "standing": "서 있었어요"},
    "bike_lane_type": {"dedicated_road": "자전거 전용도로를 달리고 있었어요",
                       "dedicated_lane": "자전거 전용차로를 달리고 있었어요",
                       "priority_road": "자전거 우선도로를 달리고 있었어요", "none": "자전거 길이 없는 곳이었어요"},
}
ROAD_ENUM = {
    "crossing_prohibition": {"none": "횡단 금지 표시가 없었어요", "sign": "횡단 금지 표지가 있었어요",
                             "barrier": "횡단 금지 울타리가 있었어요"},
    "protection_zone": {"child": "어린이 보호구역이었어요", "elderly": "노인 보호구역이었어요",
                        "disabled": "장애인 보호구역이었어요", "none": "보호구역이 아니었어요"},
    "ped_visibility": {"night": "밤이었어요", "obstructed": "세워 둔 차·커브 등으로 보행자가 미리 안 보였어요",
                       "bad_weather": "비·눈·안개로 앞이 잘 안 보였어요", "clear": "보행자가 잘 보이는 때였어요"},
}
# 참·거짓 항목: (참일 때, 거짓일 때). 당사자 항목은 앞에 "내 차가"/"상대가"를 붙임
BOOL_SENTENCE = {
    "impact_after_intersection": ("교차로를 지난 바로 뒤의 횡단보도에서 부딪혔어요",
                                  "교차로를 지난 바로 뒤의 횡단보도는 아니었어요"),
    "passed_crosswalk": ("횡단보도를 지난 뒤에 부딪혔어요", "횡단보도에 닿기 전에 부딪혔어요"),
    "riding_on_crosswalk": ("횡단보도에서 자전거를 탄 채 건넜어요", "횡단보도에서 자전거를 타고 건너지 않았어요"),
    "diagonal_crossing": ("길을 비스듬히 건넜어요", "길을 비스듬히 건너지 않았어요"),
    "opposite_side_start": ("길 건너편에서 건너기 시작했어요", "길 건너편에서 건너기 시작하지 않았어요"),
    "inside_stop_line": ("정지선 안쪽에 있었어요", "정지선 안쪽에 있지 않았어요"),
    "passed_stopped_vehicles": ("서 있는 차들 사이로 나왔어요", "서 있는 차들 사이로 나오지 않았어요"),
    "on_shoulder": ("갓길에 있었어요", "갓길에 있지 않았어요"),
    "behind_before_reverse": ("내 차가 후진하기 전부터 차 뒤에 있었어요", "내 차가 후진하기 전에는 차 뒤에 없었어요"),
    "crossing_road": ("도로를 가로질러 건너고 있었어요", "도로를 가로질러 건너고 있지 않았어요"),
    "on_bike_crossing": ("자전거횡단도로 건너고 있었어요", "자전거횡단도로 건너고 있지 않았어요"),
    "approached_right_edge": ("우회전하기 전에 도로 오른쪽 끝으로 붙었어요", "우회전하기 전에 도로 오른쪽 끝으로 붙지 않았어요"),
    "bike_lane_nearby": ("근처에 자전거 길이 있었어요", "근처에 자전거 길이 없었어요"),
    "in_bike_lane": ("자전거 길 안에 있었어요", "자전거 길 밖에 있었어요"),
    "left_side_riding": ("도로 왼쪽으로 달렸어요", "도로 왼쪽으로 달리지 않았어요"),
    "path_blocked": ("가던 길이 막혀 있었어요", "가던 길이 막혀 있지 않았어요"),
    "obstacle_ahead": ("앞에 장애물이 있었어요", "앞에 장애물이 없었어요"),
    "off_right_side": ("도로 오른쪽 끝을 벗어나 달렸어요", "도로 오른쪽 끝을 벗어나지 않았어요"),
    "sidewalk_closed": ("보도를 걸을 수 없었어요 (공사 등)", "보도를 걸을 수 있었어요"),
    "avoidable_at_limit": ("제한속도를 지켰다면 사고를 피할 수 있었어요", "제한속도를 지켰어도 사고를 피할 수 없었어요"),
}
ROAD_BOOL = {
    "crosswalk_signal": ("횡단보도에 보행자 신호등이 있었어요", "횡단보도에 보행자 신호등이 없었어요"),
    "sidewalk_separated": ("보도와 차도가 나뉜 길이었어요", "보도와 차도가 나뉘지 않은 길이었어요"),
    "night": ("밤이었어요", "밤이 아니었어요"),
    "low_visibility": ("앞이 잘 보이지 않았어요", "앞이 잘 보였어요"),
    "bad_weather": ("날씨가 나빴어요", "날씨가 나쁘지 않았어요"),
    "expressway": ("고속도로·자동차전용도로였어요", "고속도로·자동차전용도로가 아니었어요"),
    "easy_walk_area": ("사람이 걸어 다니기 쉬운 곳이었어요", "사람이 걸어 다니기 쉬운 곳이 아니었어요"),
    "ped_warning_sign": ("보행자 주의 표지가 있었어요", "보행자 주의 표지가 없었어요"),
    "lanes_two_plus": ("편도 2차로 이상인 길이었어요", "편도 1차로인 길이었어요"),
    "dashed_bike_lane_border": ("자전거 길 경계선이 점선이었어요", "자전거 길 경계선이 점선이 아니었어요"),
}
PED_FACTORS = {"group": "여러 명이 함께 건넘", "sudden_entry": "갑자기 뛰어듦", "intentional_block": "일부러 막아섬",
               "inline_skate": "인라인스케이트를 탐"}
# 항목 이름 (차량 기록 영향 카드·질문 참고 등에서 짧게)
FIELD_LABEL = {
    "turn_signal_used": "방향지시등", "slowed_before_entry": "교차로 앞 서행", "stopped_before_entry": "교차로 앞 일시정지",
    "stationary_at_collision": "부딪힐 때 멈춤", "movement": "진행 방향", "lane_change_dir": "차로를 바꾼 방향",
    "cls": "종류", "entry_from": "온 길", "signal_at_entry": "진입 신호", "lead_order": "앞뒤",
    "ped_place": "보행자 위치", "dist_from_crosswalk_m": "횡단보도 거리", "crosswalk_distance": "횡단보도 거리",
    "ped_place_other": "보행자 위치", "overpass_distance": "육교·지하도 거리", "crosswalk_signal": "보행자 신호등",
    "ped_signal_at_start": "건너기 시작할 때 보행자 신호", "ped_signal_at_impact": "부딪힐 때 보행자 신호",
    "intersection_entry_speed_kmh": "교차로 진입 속도",
    "vulnerable_type": "어린이·노인·장애인", "protection_zone": "보호구역", "ped_visibility": "밤·시야",
    "expressway": "고속도로", "expressway_walk_reason": "고속도로에 있던 이유", "on_shoulder": "갓길",
    "driver_factors": "운전자 요인",
}
# 값 짧은 이름 (차량 기록 참고 표시: "차량 기록: 켬")
VALUE_LABELS = {
    "turn_signal_used": {True: "켬", False: "안 켬"},
    "slowed_before_entry": {True: "속도를 줄임", False: "속도를 줄이지 않음"},
    "stopped_before_entry": {True: "멈춤", False: "멈추지 않음"},
    "stationary_at_collision": {True: "서 있었음", False: "움직이고 있었음"},
    "movement": {"straight": "직진", "left_turn": "좌회전", "right_turn": "우회전", "u_turn": "유턴",
                 "lane_change": "진로 변경", "reverse": "후진"},
    "lane_change_dir": {"left": "왼쪽", "right": "오른쪽"},
}


def _who(field):
    return "내 차가" if field.startswith("parties.ego.") else "상대가" if field.startswith("parties.other.") else ""


def _choice(question, value):
    """질문 보기 이름. 없으면 값 그대로"""
    if question and question.get("options") is not None:
        for o, c in zip(question["options"], question.get("choices") or question["options"]):
            if o == value:
                return c
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, list):
        return ", ".join(str(_choice(question, v)) for v in value) if value else "없음"
    return str(value)


def _was(noun):
    """명사 + 였어요/이었어요 (받침 따라)"""
    noun = str(noun)
    c = noun[-1] if noun else ""
    batchim = "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 != 0
    return f"{noun}{'이었어요' if batchim else '였어요'}"


def _yes_no(b, yes, no):
    return yes if b else no


def sentence(field, value, question=None):
    """답 하나 → "~했어요" 문장. 모르는 키는 질문 문장 + 보기 이름"""
    key = field.split(".")[-1]
    who = _who(field)
    if value is None or value == "unknown":
        return f"{question['question']} → 모름" if question else f"{FIELD_LABEL.get(key, '확인한 내용')}: 모름"
    if field == "scene.place":
        return f"사고 장소는 {_was(PLACE.get(value, value))}"
    if field == "scene.junction_type":
        return f"교차로 모양은 {_was(JUNCTION.get(value, value))}"
    if key == "cls" and who:
        return f"{who[:-1]}는 {_was(CLS.get(value, value))}"
    if key == "movement" and who and value in MOVE_DONE:
        return f"{who} {MOVE_DONE[value]}"
    if field == "parties.other.entry_from":
        return f"상대가 {ENTRY.get(value, value)}에서 왔어요"
    if field == "road.signal_present":
        return _yes_no(value, "교차로에 신호등이 있었어요", "교차로에 신호등이 없었어요")
    if field == "road.wider_road":
        return WIDER.get(value, f"더 넓은 도로: {value}")
    if field == "road.center_line":
        return _yes_no(value, "사고 난 길에 중앙선이 있었어요", "사고 난 길에 중앙선이 없었어요")
    if field == "road.stop_sign_side" and value in STOP_SIGN:
        return STOP_SIGN[value]
    if field == "intersection_entry_order":
        return ORDER.get(value, f"교차로 진입 순서: {value}")
    if key == "turn_signal_used" and who:
        return f"{who} {_yes_no(value, '방향지시등을 켰어요', '방향지시등을 켜지 않았어요')}"
    if key == "signal_at_entry" and who:
        return f"{who} 교차로에 들어갈 때 신호는 {_was(SIGNAL.get(value, value))}"
    if key == "stationary_at_collision" and who:
        return f"부딪힐 때 {who} {_yes_no(value, '서 있었어요', '움직이고 있었어요')}"
    if key == "stopped_before_entry" and who:
        return f"{who} 교차로에 들어가기 전에 {_yes_no(value, '멈췄어요', '멈추지 않았어요')}"
    if key == "slowed_before_entry" and who:
        return f"{who} 교차로에 들어가기 전에 {_yes_no(value, '속도를 줄였어요', '속도를 줄이지 않았어요')}"
    if key == "lane_change_dir" and who and value in DIR:
        return f"{who} {DIR[value]}으로 차로를 바꿨어요"
    if key == "lead_order" and who and value in LEAD:
        return f"{who} {LEAD[value]}"
    s = _more(field, key, who, value)
    if s:
        return s
    if question:
        return f"{question['question']} → {_choice(question, value)}"
    return f"{FIELD_LABEL.get(key, '확인한 내용')}: {value_label(field, value)}"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _more(field, key, who, value):
    """보행자·자전거·도로 항목 문장. 모르는 항목이면 None"""
    road = field.startswith("road.")
    if key == "ped_place" and value in PLACE_WHERE:
        return f"상대는 {PLACE_WHERE[value]}"
    if key == "ped_place_other" and value in PLACE_WHERE:
        return f"상대는 {PLACE_WHERE[value]}"
    if key == "crosswalk_distance" and value in CROSSWALK_DIST:
        return CROSSWALK_DIST[value]
    if key == "overpass_distance" and value in OVERPASS_DIST:
        return OVERPASS_DIST[value]
    if key == "dist_from_crosswalk_m" and _num(value):
        return f"횡단보도에서 {round(value, 1):g}m 떨어진 곳이었어요"
    if key == "intersection_entry_speed_kmh" and _num(value):
        return f"{who} 교차로에 들어갈 때 속도는 {round(value)}km/h였어요"
    if key in ("ped_signal_at_start", "ped_signal_at_impact") and value in PED_SIGNAL:
        when = "건너기 시작할 때" if key == "ped_signal_at_start" else "부딪힐 때"
        return f"{when} 보행자 신호는 {_was(PED_SIGNAL[value])}"
    if key == "ped_factors" and isinstance(value, list):
        return "보행자 쪽 특별한 사정은 없었어요" if not value else \
            "보행자 쪽 사정: " + ", ".join(PED_FACTORS.get(v, "그 밖의 사정") for v in value)
    if road and key in ROAD_BOOL and isinstance(value, bool):
        return ROAD_BOOL[key][0 if value else 1]
    if road and key in ROAD_ENUM and value in ROAD_ENUM[key]:
        return ROAD_ENUM[key][value]
    if key in ENUM_SENTENCE and value in ENUM_SENTENCE[key]:
        s = ENUM_SENTENCE[key][value]
        return s if key in ("right_turn_signal", "crossing_road_width") else f"{who[:-1] + '는' if who else ''} {s}".strip()
    if key in BOOL_SENTENCE and isinstance(value, bool):
        s = BOOL_SENTENCE[key][0 if value else 1]
        return f"{who} {s}".strip() if who and not s.startswith("내 차가") else s
    return None


def value_label(field, value):
    """값 짧은 이름 ("켬", "좌회전", "예"). 질문 보기 이름을 모르면 이 표 → 예/아니요 → 그대로(숫자)"""
    key = field.split(".")[-1]
    if isinstance(value, list):   # 분석기 user_factors·ped_factors 등 목록 값 (전에는 TypeError)
        return ", ".join(str(value_label(field, v)) for v in value) or "없음"
    table = VALUE_LABELS.get(key) or {}
    if value in table:
        return table[value]
    if key == "cls":
        return CLS.get(value, "모름")
    if key == "signal_at_entry":
        return SIGNAL.get(value, "모름")
    if key in ("ped_signal_at_start", "ped_signal_at_impact"):
        return PED_SIGNAL.get(value, "모름")
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if value is None:
        return "모름"
    if _num(value):
        return f"{round(value, 1):g}"
    return "기타"


def _guess_clause(field, guess, question):
    """추정 문장: "내 차가 우회전한 것 같아요" """
    key = field.split(".")[-1]
    who = _who(field)
    if key == "movement" and who and guess in MOVE_GUESS:
        return f"{who} {MOVE_GUESS[guess]} 것 같아요"
    s = sentence(field, guess, question)
    return s[:-2] + "던 것 같아요" if s.endswith("었어요") or s.endswith("였어요") else f"{s} (추정)"


def _t(t):
    return f"{round(t, 1):g}초" if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def for_video(field, value, t=None, question=None):
    ts = _t(t)
    return sentence(field, value, question) + (f" ({ts})" if ts else "")


def for_video_guess(field, guess, t=None, question=None):
    ts = _t(t)
    return f"영상으로는 {_guess_clause(field, guess, question)}" + (f" ({ts}, 추정)" if ts else " (추정)")


def for_user(field, value, question=None):
    return f"{sentence(field, value, question)} (직접 답했어요)"


def for_default(field, value, basis=None, question=None):
    """답이 없어 추정값(basis video/vehicle)이나 기본값으로 채운 값. 앱은 "추정"/"가정" 배지와 "다르면 결과가 바뀔 수 있어요"를 붙인다"""
    return f"{sentence(field, value, question)} ({BASIS.get(basis, '기본값')})"
