"""블랙박스 사건의 사고 장(차대차·차대보행자·차대자전거)과 장별 질문 (docs/design-blackbox.md 2.4, 8.3.1)

상대 종류(parties.other.cls)로 장을 고른다. 판정 엔진(judge/fault_engine.detect_category)과 같은 기준이다.

  상대 종류 정하기 (사용자 > 영상 확실한 값 > 영상 추정값)
    - 영상 value가 있고 confidence가 CLS_MIN_CONF 이상(또는 confidence 없음)이면 확실한 값: 묻지 않음
    - confidence가 CLS_MIN_CONF보다 낮으면 추정값으로 내림: "상대는 무엇이었나요?"를 remaining 맨 앞에 둠
    - 사용자는 언제든 PUT answers로 parties.other.cls를 바꿀 수 있고, 바뀌면 그 장의 질문·도표로 다시 판정한다

  장별 질문
    - 차대차: 지금 그대로 (base_questions + situation.questions)
    - 차대보행자: 차대차 전용 기본 질문을 빼고 ped_questions(). 질문 키는 판정 엔진 이름 그대로 쓰되,
      횡단보도 거리는 4구간 질문 하나(crosswalk_distance)로 묻고 대표 거리(5/20/40m)로 바꾼다 (A_REQUESTS 1.)
      순서: 도표 선택(장소·거리·신호·고속도로) → 가감 요소(어린이·노인, 보호구역, 야간·시야, 고속도로 사정) →
      선택 질문 운전자 요인(driver_factors, 차대차와 같은 보기). 가감 요소 질문은 영상·차량 기록이 못 채우는 것만
    - 차대자전거: 자전거는 차처럼 진행 방향·신호·표지 도표를 쓰므로 차대차 질문(situation)을 상대를 차로 보고
      그대로 내고, BIKE_QUESTIONS를 더한다

MTM 질문 모듈(src/app/chapters.py)은 고치지 않는다. 그 모듈의 CHAPTER_OF에 "person"이 없어(A_REQUESTS 요청 3)
분석기 값 person은 질문 보기 이름 pedestrian으로 바꿔 넣는다 (판정 엔진 변환기는 pedestrian을 person으로 읽음).
그 모듈의 보행자 질문(crossing_place, ped_signal_at_crossing)은 쓰지 않는다 (A_REQUESTS 요청 1·2의 문제).
"""
import copy

from src.app import situation
from src.blackbox import evidence
from src.vehicle import adapter as va

CLS_FIELD = "parties.other.cls"
CLS_MIN_CONF = 0.7            # 임시값: 상대 종류 확신도가 이보다 낮으면 추정값으로 보고 묻는다 (실제 분석기로 조정)
CLS_TO_ANSWER = {"person": "pedestrian"}   # 분석기 이름 → 질문 보기 이름 (va.OTHER_CLASSES)

CAR_CAR, CAR_PED, CAR_BIKE = "car_car", "car_pedestrian", "car_bicycle"
CHAPTER_OF = {"pedestrian": CAR_PED, "person": CAR_PED, "bicycle": CAR_BIKE, "farm_machine": CAR_BIKE}

# ---------- 보행자 질문 ----------

DIST_FIELD = "parties.other.crosswalk_distance"
PLACE_FIELD = "parties.other.ped_place_other"
OVERPASS_FIELD = "parties.other.overpass_distance"
DIST_OPTIONS = ["on", "within_10m", "10_30m", "over_30m", "no_crosswalk"]
DIST_CHOICES = ["횡단보도 위", "횡단보도에서 10m 이내", "횡단보도에서 10~30m", "횡단보도에서 30m 넘게 떨어진 곳",
                "근처에 횡단보도 없음"]
BIN_M = {"within_10m": 5, "10_30m": 20, "over_30m": 40}   # 구간 대표 거리 (8.3.2)
NEAR = ["on", "within_10m", "10_30m"]                       # 횡단보도 신호가 뜻이 있는 구간 (보1~보20)
OTHER_PLACES = ["near_overpass", "intersection", "road", "sidewalk", "roadway", "ped_only_road", "ped_priority_road"]
OTHER_PLACE_CHOICES = ["육교·지하도 부근", "신호 없는 교차로를 건너던 중", "교차로 아닌 길을 건너던 중", "보도",
                       "차도를 따라 걷던 중", "보행자 전용도로", "보행자 우선도로"]
PED_SIGNALS = ["green", "flashing_green", "red"]
PED_SIGNAL_CHOICES = ["초록", "초록 점멸", "빨강"]
YES_NO = [True, False]
# 고속도로 (보35·보36, 2026-11-11)
EXPRESSWAY_FIELD = "road.expressway"
WALK_REASON_FIELD = "parties.other.expressway_walk_reason"
FAR = ["over_30m", "no_crosswalk"]                          # 횡단보도가 없거나 먼 곳: 고속도로일 수 있음
# skip_when: 이 답이면 묻지 않음 (depends_on의 반대). 고속도로 도표(보35·보36)는 장소·건넌 도로 폭을 읽지 않음.
# depends_on에 "고속도로 아님"을 걸면 고속도로 질문을 건너뛴 사람에게 장소 질문이 숨어서 skip_when으로 따로 둠
ON_EXPRESSWAY = {EXPRESSWAY_FIELD: True}
# 가감 요소 (2026-11-11). 보행자 수정요소 중 영상·차량 기록으로 못 채우는 것 (A_REQUESTS 2. "질문")
VULNERABLE_FIELD = "parties.other.vulnerable_type"
VULNERABLE = ["child", "elderly", "disabled", "none"]
VULNERABLE_CHOICES = ["어린이 (만 13세 미만)", "노인 (만 65세 이상)", "장애인", "해당 없음"]
ZONE_FIELD = "road.protection_zone"
ZONES = ["child", "elderly", "disabled", "none"]
ZONE_CHOICES = ["어린이보호구역", "노인보호구역", "장애인보호구역", "보호구역 아님"]
# 야간·시야장애는 수정요소 한 묶음(하나만 적용)이라 질문 하나로. 악천후는 고속도로 도표(보35·보36)의 야간 묶음
VISIBILITY_FIELD = "road.ped_visibility"
VISIBILITY = ["night", "obstructed", "bad_weather", "clear"]
VISIBILITY_CHOICES = ["밤이었음", "세워 둔 차·커브·골목 등으로 보행자가 미리 안 보였음", "비·눈·안개로 앞이 잘 안 보였음",
                      "해당 없음 (낮, 잘 보였음)"]
VISIBILITY_SCENE = {"night": {"night": True, "view_obstructed": False, "bad_weather": False},
                    "obstructed": {"night": False, "view_obstructed": True, "bad_weather": False},
                    "bad_weather": {"night": False, "view_obstructed": False, "bad_weather": True},
                    "clear": {"night": False, "view_obstructed": False, "bad_weather": False}}
DRIVER_FIELD = "parties.ego.driver_factors"

# 보행자 장에서 빼는 차대차 기본 질문 (va.base_questions). 내 차 신호·중앙선은 아래에서 조건을 바꿔 다시 묻는다
PED_DROP = {"parties.other.movement", "parties.other.entry_from", "parties.other.signal_at_entry",
            "parties.ego.signal_at_entry", "road.wider_road", "road.center_line", "intersection_entry_order"}


def _q(field, question, options, choices, **extra):
    return va.clean_question(va._q(field, question, options, choices, **extra))


def ped_questions():
    """보행자 장 질문. 앞이 도표 선택용, 뒤가 가감 요소용, 맨 끝이 선택 질문 (remaining은 이 순서를 지킴)"""
    near_signal = {"road.crosswalk_signal": True}
    return [
        _q(DIST_FIELD, "보행자와 부딪힌 곳은 횡단보도에서 얼마나 떨어져 있었나요?", DIST_OPTIONS, DIST_CHOICES),
        # 고속도로 (보35·보36): 횡단보도가 없거나 먼 곳일 때만. 다른 도표 질문의 조건으로 쓰지 않음
        # (답하지 않으면 조건 걸린 질문이 숨어서, 고속도로를 건너뛴 사람이 장소 질문을 못 받게 됨)
        _q(EXPRESSWAY_FIELD, "고속도로나 자동차전용도로에서 난 사고인가요?", YES_NO, ["예", "아니요"],
           depends_on={DIST_FIELD: FAR}),
        _q(WALK_REASON_FIELD, "보행자가 고속도로에 있던 이유가 있었나요?", ["justified", "none"],
           ["있음 (고장·사고로 차에서 내림 등)", "없음 (그냥 걷거나 건넘)"], depends_on={EXPRESSWAY_FIELD: True}),
        _q(PLACE_FIELD, "그럼 보행자는 어디에 있었나요?", OTHER_PLACES, OTHER_PLACE_CHOICES,
           depends_on={DIST_FIELD: "no_crosswalk"}, skip_when=ON_EXPRESSWAY),
        _q(OVERPASS_FIELD, "육교·지하도에서 얼마나 떨어진 곳이었나요?", ["within_10m", "10_30m", "over_30m"],
           ["10m 이내", "10~30m", "30m 넘게"], depends_on={PLACE_FIELD: "near_overpass"}, skip_when=ON_EXPRESSWAY),
        _q("road.crosswalk_signal", "그 횡단보도에 보행자 신호등이 있었나요?", YES_NO, ["있음", "없음"],
           depends_on={DIST_FIELD: NEAR}),
        _q("parties.other.ped_signal_at_start", "보행자가 건너기 시작할 때 보행자 신호는 무엇이었나요?", PED_SIGNALS,
           PED_SIGNAL_CHOICES, depends_on={**near_signal, DIST_FIELD: NEAR}),
        _q("parties.other.ped_signal_at_impact", "부딪힐 때 보행자 신호는 무엇이었나요?", PED_SIGNALS,
           PED_SIGNAL_CHOICES, depends_on={**near_signal, DIST_FIELD: "on"}),
        _q("parties.ego.signal_at_entry", "내 차가 횡단보도(정지선)를 지날 때 차량 신호는 무엇이었나요?", va.SIGNALS,
           va.SIGNAL_NAMES, depends_on={**near_signal, DIST_FIELD: NEAR}),
        _q("parties.ego.impact_after_intersection", "교차로를 지난 바로 뒤의 횡단보도였나요?", YES_NO,
           ["예 (교차로를 지나서 부딪힘)", "아니요 (교차로 앞이거나 교차로 없는 길)"],
           depends_on={**near_signal, DIST_FIELD: "on"}),
        _q("parties.ego.passed_crosswalk", "내 차가 횡단보도를 지난 뒤에 부딪혔나요?", YES_NO,
           ["예 (횡단보도를 지나서)", "아니요 (횡단보도에 닿기 전)"],
           depends_on={**near_signal, DIST_FIELD: ["within_10m", "10_30m"]}),
        _q("parties.ego.right_turn_signal", "우회전 신호등(우회전 화살표)이 있었나요?", ["green", "red", "none"],
           ["있음, 초록", "있음, 빨강", "없음"],
           depends_on={**near_signal, DIST_FIELD: ["within_10m", "10_30m"], "parties.ego.movement": "right_turn"}),
        _q("parties.other.ped_activity", "보행자는 무엇을 하고 있었나요?", ["crossing", "walking", "lying_or_playing"],
           ["길을 건너던 중", "길을 따라 걷던 중", "차도에 눕거나 앉아 있었음·놀던 중"],
           depends_on={DIST_FIELD: ["over_30m", "no_crosswalk"]}),
        _q("parties.other.crossing_road_width", "보행자가 건넌 도로는 내 차가 달린 도로와 비교해 어땠나요?",
           ["narrower", "equal", "wider"], ["더 좁음", "비슷함", "더 넓음"],
           depends_on={"scene.place": "intersection", DIST_FIELD: ["over_30m", "no_crosswalk"]},
           skip_when=ON_EXPRESSWAY),
        _q("road.sidewalk_separated", "보도와 차도가 나뉜 길이었나요?", YES_NO, ["예 (보도가 있음)", "아니요"],
           depends_on={PLACE_FIELD: "roadway"}),
        _q("parties.other.sidewalk_closed", "보도 공사 등으로 보도를 걸을 수 없었나요?", YES_NO, ["예", "아니요"],
           depends_on={PLACE_FIELD: "roadway", "road.sidewalk_separated": True}),
        _q("road.center_line", "사고 난 길에 중앙선(가운데 노란 선)이 있나요?", YES_NO, ["있음", "없음 (골목길)"],
           depends_on={PLACE_FIELD: "roadway", "road.sidewalk_separated": False}),
        _q("parties.other.roadway_walk_position", "보행자는 차도의 어디를 걷고 있었나요?",
           ["edge_1m", "beyond_1m", "edge", "center"],
           ["길 가장자리에서 1m 안 (보도 있는 길)", "길 가장자리에서 1m 넘게 (보도 있는 길)",
            "길 가장자리 (보도 없는 길)", "길 가운데 (보도 없는 길)"],
           depends_on={PLACE_FIELD: "roadway"}),
        # ---- 가감 요소 (도표 선택 질문 뒤) ----
        _q(VULNERABLE_FIELD, "보행자는 어린이·노인·장애인이었나요?", VULNERABLE, VULNERABLE_CHOICES),
        _q(ZONE_FIELD, "사고 난 곳이 보호구역이었나요?", ZONES, ZONE_CHOICES),
        _q(VISIBILITY_FIELD, "사고 때 보행자가 잘 보이지 않을 사정이 있었나요?", VISIBILITY, VISIBILITY_CHOICES),
        _q("parties.other.on_shoulder", "보행자가 갓길에 있었나요?", YES_NO, ["예 (갓길)", "아니요 (차로)"],
           depends_on={EXPRESSWAY_FIELD: True}),
        _q("road.easy_walk_area", "사람이 걸어 다니기 쉬운 곳이었나요? (휴게소·요금소 부근 등)", YES_NO, ["예", "아니요"],
           depends_on={EXPRESSWAY_FIELD: True}),
        _q("road.ped_warning_sign", "보행자 주의 표지가 있었나요?", YES_NO, ["있음", "없음"],
           depends_on={WALK_REASON_FIELD: "justified"}),
        # 선택 질문: 운전자 요인 (차대차 situation.driver_questions와 같은 보기, 판정 변환도 answers.to_assumptions 그대로)
        _q(DRIVER_FIELD, "내 차 운전자에게 해당하는 것이 있으면 골라 주세요 (모르면 넘어가도 돼요)",
           [k for k, _ in situation.DRIVER_FACTORS], [c for _, c in situation.DRIVER_FACTORS],
           answer_type="multi", model_guess=[], default=True, optional=True, group="운전자 요인"),
    ]


# ---------- 자전거 질문 ----------

BIKE_LANES = ["dedicated_road", "dedicated_lane", "priority_road", "none"]
BIKE_LANE_CHOICES = ["자전거 전용도로", "자전거 전용차로", "자전거 우선도로", "없음"]


def bike_questions():
    return [
        # 거41·거42는 자전거가 내 차 옆(왼쪽·오른쪽 길)에서 왔는지로 역할을 정함. 기본 질문은 교차로에서만 물어서 더함
        _q("parties.other.entry_from", "자전거는 어느 쪽에서 왔나요?", va.ENTRIES, va.ENTRY_CHOICES),
        _q("parties.other.on_bike_crossing", "자전거가 자전거횡단도로 건너고 있었나요?", YES_NO, ["예", "아니요"]),
        _q("parties.other.crossing_road", "자전거가 도로를 가로질러 건너고 있었나요?", YES_NO, ["예", "아니요"],
           depends_on={"parties.other.on_bike_crossing": False}),
        _q("parties.other.bike_lane_type", "자전거가 달리던 곳은 어떤 자전거 길이었나요?", BIKE_LANES,
           BIKE_LANE_CHOICES, depends_on={"parties.ego.movement": "lane_change"}),
        _q("parties.ego.approached_right_edge", "내 차가 우회전하기 전에 도로 오른쪽 끝으로 붙었나요?", YES_NO,
           ["예", "아니요"], depends_on={"parties.ego.movement": "right_turn"}),
        _q("parties.other.approached_right_edge", "자전거가 우회전하기 전에 도로 오른쪽 끝으로 붙었나요?", YES_NO,
           ["예", "아니요"], depends_on={"parties.other.movement": "right_turn"}),
    ]


# ---------- 장 고르기 ----------

def chapter_of(cls):
    return CHAPTER_OF.get(cls, CAR_CAR)


def to_answer_cls(cls):
    return CLS_TO_ANSWER.get(cls, cls)


def adjust_video(facts, definite, guesses):
    """merge.video_values 결과를 장 기준으로 고친다 (제자리).
    1. 상대 종류: person → pedestrian, 확신도 낮은 value는 추정값으로 내림
    2. 보행자 장소·거리 → 질문 키(crosswalk_distance, ped_place_other, overpass_distance) 값도 만듦
    반환: 상대 종류 정보 {"value", "guess", "confidence", "low_confidence"} (영상 기준)"""
    other = ((facts or {}).get("parties") or {}).get("other") or {}
    raw = other.get("cls") if isinstance(other.get("cls"), dict) else {}
    conf = raw.get("confidence")
    info = {"value": to_answer_cls(raw.get("value")), "guess": to_answer_cls(raw.get("guess")),
            "confidence": conf, "low_confidence": False}
    if CLS_FIELD in definite:
        definite[CLS_FIELD]["value"] = info["value"]
        if conf is not None and conf < CLS_MIN_CONF:
            ev = evidence.for_video_guess(CLS_FIELD, info["value"], raw.get("t"))
            guesses[CLS_FIELD] = {"guess": info["value"], "evidence": f"{ev[:-1]}, 확신도 {conf:g})"
                                  if ev.endswith(")") else ev}
            del definite[CLS_FIELD]
            info.update(guess=info["value"], value=None, low_confidence=True)
    elif CLS_FIELD in guesses:
        guesses[CLS_FIELD]["guess"] = info["guess"]
    _ped_place_keys(other, definite, guesses)
    _visibility_keys(facts, definite, guesses)
    return info


def _visibility_keys(facts, definite, guesses):
    """분석기 road.night·bad_weather(값 객체) → 시야 질문 값. 밤이나 악천후가 확실하면 묻지 않음.
    "아님"만 확실하면 시야장애(세워 둔 차 등)가 남아 있어 계속 묻는다"""
    road = (facts or {}).get("road") or {}
    q = next(x for x in ped_questions() if x["field"] == VISIBILITY_FIELD)
    for key in ("night", "bad_weather"):
        v = road.get(key) if isinstance(road.get(key), dict) else {}
        if v.get("value") is True:
            definite[VISIBILITY_FIELD] = {"value": key,
                                          "evidence": evidence.for_video(VISIBILITY_FIELD, key, v.get("t"), q)}
            guesses.pop(VISIBILITY_FIELD, None)
            return
        if v.get("value") is None and v.get("guess") is True and VISIBILITY_FIELD not in guesses:
            guesses[VISIBILITY_FIELD] = {"guess": key,
                                         "evidence": evidence.for_video_guess(VISIBILITY_FIELD, key, v.get("t"), q)}


def _bin(d):
    if d is None:
        return None
    return "within_10m" if d <= 10 else "10_30m" if d <= 30 else "over_30m"


def _ped_place_keys(other, definite, guesses):
    """분석기 ped_place·dist_from_crosswalk_m(값 객체) → 보행자 질문 키 값. 확실한 값이면 definite, 추정이면 guesses"""
    place = other.get("ped_place") if isinstance(other.get("ped_place"), dict) else None
    if not place:
        return
    dist = other.get("dist_from_crosswalk_m") if isinstance(other.get("dist_from_crosswalk_m"), dict) else {}
    sure = place.get("value") is not None
    p = place.get("value") if sure else place.get("guess")
    if p is None:
        return
    d_sure = dist.get("value") is not None
    d = dist.get("value") if d_sure else dist.get("guess")
    b = dist.get("bin") or _bin(d)
    t = place.get("t")
    out = {}
    if p == "crosswalk":
        out[DIST_FIELD] = ("on", sure)
    elif p == "near_crosswalk":
        if b:
            out[DIST_FIELD] = (b, sure and d_sure)
    else:
        out[DIST_FIELD] = ("no_crosswalk", sure)
        out[PLACE_FIELD] = (p, sure)
        if p == "near_overpass" and b:
            out[OVERPASS_FIELD] = (b, sure and d_sure)
    for field, (v, is_sure) in out.items():
        q = next((x for x in ped_questions() if x["field"] == field), None)
        if is_sure:
            definite[field] = {"value": v, "evidence": evidence.for_video(field, v, t, q)}
        elif field not in definite:
            guesses[field] = {"guess": v, "evidence": evidence.for_video_guess(field, v, t, q)}


def skipped(q, answers):
    """remaining에서 뺄 질문이면 True.
    skip_when: 조건(모두)이 답에 맞으면 뺌. when_any: {여러 개 고르기 질문 키: [값]} 답 목록에 그 값이 하나도 없으면 뺌
    (depends_on은 답이 값과 같거나 목록 안에 있는지만 봐서, 여러 개 고르기 답(목록)에 값이 들었는지는 못 봄)"""
    cond = q.get("skip_when")
    if cond and all(answers.get(k) == v for k, v in cond.items()):
        return True
    for k, vals in (q.get("when_any") or {}).items():
        if not set(answers.get(k) or []) & set(vals):
            return True
    return False


# ---------- 과속 인과관계 (2026-11-11) ----------

AVOIDABLE = "avoidable_at_limit"
SPEED_KEYS = list(situation.SPEED_OVER)            # 운전자 요인의 과속 보기 (speed_20plus, speed_under20)


def speed_followups(qs):
    """운전자 요인 질문마다 "제한속도를 지켰다면 사고를 피할 수 있었나요?"를 바로 뒤에 둠 (모든 장).
    판정 엔진의 속도위반 가산은 인과관계(avoidable_at_limit)가 참일 때만 붙음 (judge/modifiers.json speeding_20plus 등).
    과속 보기를 골랐을 때만 묻는다 (when_any). 반환: 새 질문 목록"""
    out = []
    for q in qs:
        out.append(q)
        if not q["field"].endswith(".driver_factors"):
            continue
        pid = q["field"].split(".")[1]
        who = "내 차" if pid == "ego" else "상대 차"
        out.append(_q(f"parties.{pid}.{AVOIDABLE}", f"{who}가 제한속도를 지켰다면 사고를 피할 수 있었나요?", YES_NO,
                      ["예 (피할 수 있었음)", "아니요 (지켰어도 났을 것)"], when_any={q["field"]: SPEED_KEYS},
                      group=q.get("group")))
    return out


def avoidable_assumptions(asm, user):
    """인과관계 답 → 판정 가정 (answers.to_assumptions가 모르는 키라 여기서). 당사자 이름은 질문 키 그대로(ego/other)"""
    for k, v in user.items():
        if isinstance(k, str) and k.endswith("." + AVOIDABLE) and k.startswith("parties.") and isinstance(v, bool):
            asm.setdefault("parties", {}).setdefault(k.split(".")[1], {})[AVOIDABLE] = v
    return asm


PLACE_KEYS = {DIST_FIELD, PLACE_FIELD, OVERPASS_FIELD}
ENGINE_PLACE = ("ped_place", "dist_from_crosswalk_m")


def drop_overridden(facts, chapter, user):
    """사용자가 장소·거리 질문에 답하면 영상이 낸 ped_place·dist_from_crosswalk_m를 판정 facts에서 뺌 (제자리).
    "횡단보도 없음"만 답하면 엔진 이름 ped_place의 답(가정)이 아직 없어서, 빼지 않으면 영상의 crosswalk가 남아
    보13이 그대로 나옴. 빼면 장소 답이 올 때까지 판단 보류"""
    if chapter != CAR_PED or not PLACE_KEYS & set(user):
        return facts
    for k in ENGINE_PLACE:
        facts["parties"]["other"].pop(k, None)
    return facts


def questions(chapter, base, situation_qs):
    """장별 질문 목록. base = va.base_questions(place)를 clean_question한 것, situation_qs = 상황 질문(정리한 것)"""
    if chapter == CAR_PED:
        qs = [q for q in base if q["field"] not in PED_DROP]
        have = {q["field"] for q in qs}
        return qs + [q for q in ped_questions() if q["field"] not in have]
    qs = base + situation_qs
    if chapter == CAR_BIKE:
        have = {q["field"] for q in qs}
        qs += [q for q in bike_questions() if q["field"] not in have]
    return qs


# ---------- 답 → 판정 엔진 값 ----------

PED_DIRECT = {"ped_signal_at_start", "ped_signal_at_impact", "ped_activity", "crossing_road_width", "sidewalk_closed",
              "roadway_walk_position", "impact_after_intersection", "passed_crosswalk", "right_turn_signal",
              "signal_at_entry", "expressway_walk_reason", "vulnerable_type", "on_shoulder"}
BIKE_DIRECT = {"on_bike_crossing", "crossing_road", "bike_lane_type", "approached_right_edge"}
SCENE_DIRECT = {"crosswalk_signal", "sidewalk_separated", "protection_zone", "easy_walk_area", "ped_warning_sign"}


def engine_values(chapter, values):
    """장 질문 답(질문 키 → 값) → ({당사자: {엔진 이름: 값}}, {장면 이름: 값}).
    answers.to_assumptions가 모르는 키만 바꾼다 (중앙선·신호등 유무 등은 그 함수가 처리)"""
    parties, scene = {}, {}
    if chapter not in (CAR_PED, CAR_BIKE):
        return parties, scene
    direct = PED_DIRECT if chapter == CAR_PED else BIKE_DIRECT
    for field, v in values.items():
        if v is None:
            continue
        if field.startswith("parties."):
            _, pid, k = field.split(".", 2)
            if k in direct:
                parties.setdefault(pid, {})[k] = v
                if k == "ped_signal_at_impact":   # 차53-1이 읽는 이름 (A_REQUESTS 요청 1)
                    parties[pid]["ped_signal_at_crossing"] = v
        elif field.startswith("road.") and field.split(".", 1)[1] in SCENE_DIRECT and chapter == CAR_PED:
            scene[field.split(".", 1)[1]] = v
    if chapter == CAR_PED:
        ped = parties.setdefault("other", {})
        dist = values.get(DIST_FIELD)
        if dist == "on":
            ped["ped_place"] = "crosswalk"
        elif dist in BIN_M:
            ped["ped_place"], ped["dist_from_crosswalk_m"] = "near_crosswalk", BIN_M[dist]
        elif dist == "no_crosswalk" and values.get(PLACE_FIELD) is not None:
            ped["ped_place"] = values[PLACE_FIELD]
            if values[PLACE_FIELD] == "near_overpass" and values.get(OVERPASS_FIELD) in BIN_M:
                ped["dist_from_crosswalk_m"] = BIN_M[values[OVERPASS_FIELD]]
        # 보호구역 종류와 보행자가 맞음 (어린이보호구역의 어린이 등): 둘 다 알 때만
        zone, who = values.get(ZONE_FIELD), values.get(VULNERABLE_FIELD)
        if zone is not None and who is not None:
            ped["in_own_protection_zone"] = zone != "none" and zone == who
        if values.get(EXPRESSWAY_FIELD) is True:
            scene["road_class"] = "expressway"
        if values.get(VISIBILITY_FIELD) in VISIBILITY_SCENE:
            scene.update(VISIBILITY_SCENE[values[VISIBILITY_FIELD]])
        if not ped:
            del parties["other"]
    return parties, scene


def add_assumptions(asm, chapter, user):
    """사용자 답 → 판정 가정 (출처 user). to_assumptions 결과(asm)에 더함"""
    parties, scene = engine_values(chapter, user)
    for pid, kv in parties.items():
        asm.setdefault("parties", {}).setdefault(pid, {}).update(kv)
    asm.setdefault("scene", {}).update(scene)
    return asm


def fill(facts, chapter, guesses):
    """답이 없는 장 질문의 추정값 → 판정 facts (출처 model, fill_guesses와 같은 뜻). 반환: (facts 사본, 채운 질문 키)"""
    f = copy.deepcopy(facts)
    used = {k: v for k, v in guesses.items() if v is not None}
    parties, scene = engine_values(chapter, used)
    for pid, kv in parties.items():
        for k, v in kv.items():
            if f["parties"][pid].get(k) is None:
                f["parties"][pid][k] = v
    for k, v in scene.items():
        if f["road"].get(k) is None:
            f["road"][k] = v
    return f, sorted(used)


def cls_view(decided, guesses, info, chapter):
    """결과 응답의 상대 종류 (앱의 "상대가 OO가 아니었나요?" 버튼):
    {"field", "value", "label", "source": user|video|guess|null, "confidence", "chapter"}"""
    d = decided.get(CLS_FIELD)
    if d:
        value, source = d["value"], "user" if d["source"] == "user" else "video"
    elif (guesses.get(CLS_FIELD) or {}).get("model_guess") is not None:
        value, source = guesses[CLS_FIELD]["model_guess"], "guess"
    else:
        value, source = None, None
    label = evidence.CLS.get(value) if value else None
    return {"field": CLS_FIELD, "value": value, "label": label, "source": source,
            "confidence": info.get("confidence") if source in ("video", "guess") else None,
            "low_confidence": bool(info.get("low_confidence")) and source == "guess",
            "chapter": chapter, "options": va.OTHER_CLASSES, "choices": va.OTHER_CLASS_CHOICES}
