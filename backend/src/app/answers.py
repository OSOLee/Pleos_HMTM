"""사용자 답(unknowns의 field -> 값)을 B 판정 모듈의 가정(assumptions)으로 바꾼다

answers.json 예시:
  {"parties.79.movement": "straight",
   "road.signal_present": false,
   "road.wider_road": "equal",
   "collision.parties": ["68", "167"]}

"collision.parties"만 facts를 다시 만들어야 해서 따로 꺼낸다 (collision_pair).
나머지는 B의 assumptions로 넘기고, B가 출처를 user로 기록한다.
"""
import copy

from src.analyze.build_facts import SAME_TIME_SEC
from src.app import situation

AXIS = {"north_south": {"north", "south"}, "east_west": {"east", "west"}}


def collision_pair(answers):
    pair = answers.get("collision.parties")
    return [str(t) for t in pair] if pair else None


def check(facts, answers, n_frames):
    """보기가 정해진 질문에 보기 밖의 답이 오면 에러. 장면(프레임)을 고르는 답은 분석한 프레임(n_frames) 안이어야 함"""
    by_field = {u["field"]: u for u in facts["unknowns"]}
    for field, val in answers.items():
        u = by_field.get(field)
        # 지금 묻지 않은 질문의 답도 판정에 넘어가므로(to_assumptions) 프레임 답은 질문이 없어도 범위를 봄
        if field.endswith(".intersection_entry") or (u and u["answer_type"] == "frame"):
            if not isinstance(val, int) or not 0 <= val < n_frames:
                raise ValueError(f"{field}의 답 {val!r}이 분석한 프레임 범위(0~{n_frames - 1}) 밖이에요")
            continue
        if u is None:
            continue
        opts = u["options"]
        if u["answer_type"] == "pair":
            ok = sorted(map(str, val)) in [sorted(map(str, o)) for o in opts]
        elif u["answer_type"] == "multi":   # 여러 개 고르기: 보기 안의 값 목록 (빈 목록 = 해당 없음)
            ok = isinstance(val, list) and all(v in u.get("all_options", opts) for v in val)
        else:
            ok = val in opts
        if not ok:
            raise ValueError(f"{field}의 답 {val!r}이 보기 {opts}에 없어요")


def remaining(facts, answers):
    """답이 없는 질문. depends_on이 있는 질문(신호 색)은 그 조건에 답이 맞을 때만 남긴다.
    조건 값이 목록이면 그중 하나면 됨 (보행자 신호: 횡단보도 위 또는 부근)"""
    def met(k, v):
        return answers.get(k) in v if isinstance(v, list) else answers.get(k) == v
    return [u for u in facts["unknowns"] if u["field"] not in answers
            and all(met(k, v) for k, v in (u.get("depends_on") or {}).items())]


def optional_all(facts, answers):
    """선택 질문(optional) 전부. 답한 것도 넣는다 (remaining은 답한 질문을 빼서, 앱에서 "음주" 같은 걸 고른 뒤
    다시 열면 그 질문이 없어져 취소할 수 없었음). depends_on 조건은 remaining과 같이 본다"""
    def met(k, v):
        return answers.get(k) in v if isinstance(v, list) else answers.get(k) == v
    return [u for u in facts["unknowns"] if u.get("optional")
            and all(met(k, v) for k, v in (u.get("depends_on") or {}).items())]


def conflicts(facts, answers):
    """사용자 답이 모델 추정값과 다른 질문 목록. 결과 화면에서 "사용자 입력이 영상 분석과 다름"으로 보여 준다
    (당사자는 자기에게 유리하게 답할 동기가 있음). 기본값(도로 폭 "비슷함")은 추정이 아니라서 빼고,
    추정값이 없거나 "모름"이면 비교하지 않는다"""
    out = []
    for u in facts["unknowns"]:
        guess, val = u.get("model_guess"), answers.get(u["field"])
        if u["field"] not in answers or guess in (None, "unknown") or u.get("default") or u["answer_type"] != "choice":
            continue
        if val != guess:
            names = dict(zip(map(str, u["options"]), u.get("choices") or u["options"]))
            out.append({"field": u["field"], "question": u["question"], "model_guess": guess, "answer": val,
                        "model_choice": names.get(str(guess), guess), "answer_choice": names.get(str(val), val)})
    return out


def fill_guesses(facts, left, answers=None):
    """답이 없는 질문을 모델 추정값(또는 기본값)으로 채운 판정용 facts 사본을 만든다.
    사용자 입력 없이도 결과를 내기 위한 것으로, 채운 값은 facts의 값처럼 B에 넘어가 출처가 model로 남는다.
    반환: (facts 사본, 채운 field 목록)"""
    f = copy.deepcopy(facts)
    filled = []
    for q in left:
        guess, field = q.get("model_guess"), q["field"]
        if guess is None or guess == "unknown":
            continue
        if field.startswith("parties."):
            _, tid, key = field.split(".", 2)
            if key in ("movement", "entry_from", "cls", "signal_at_entry", "signal_at_collision", "slowed_before_entry"):
                f["parties"][tid][key] = guess
                filled.append(field)
        elif field == "road.signal_present":
            f["road"]["signal_present"] = guess
            filled.append(field)
        elif field == "road.stop_sign_side":   # 기본값 "없음": 두 당사자 모두 stop_sign false
            for t in (f["collision"]["a"], f["collision"]["b"]):
                f["parties"][t]["stop_sign"] = str(guess) in (str(t), "both")
            filled.append(field)
        elif field == "road.wider_road":
            f["road"]["road_width"] = "equal" if guess == "equal" else "different"
            if guess != "equal":
                for tid, p in f["parties"].items():
                    # 온 길은 사용자 답이 있으면 답을 씀 (사용자가 표시한 당사자는 답에만 있음)
                    came = (answers or {}).get(f"parties.{tid}.entry_from", p.get("entry_from"))
                    if came:
                        p["on_wider_road"] = came in AXIS[guess]
            filled.append(field)
    # 장소는 판정용 facts에서 비우고 가정(to_assumptions: 교차로 장면이면 intersection, 답이 있으면 답)으로 넘긴다.
    # B adapter는 facts의 장소를 가정보다 먼저 써서, 비워 두지 않으면 "교차로를 벗어난 길" 답이 무시됨
    if f.get("road"):
        f["road"]["location"] = None
    return f, filled


def to_assumptions(facts, answers):
    fps = facts["fps"]
    asm = {"scene": {}, "parties": {}}
    # 장소: facts의 장소(모서리 단계에서 고른 장소 종류)를 가정으로 넘김. 판정용 facts에서는 비워 두므로
    # (fill_guesses) 여기서 넘겨야 함. "부딪힌 곳" 답(road.location)이 있으면 아래에서 덮어씀
    place = (facts.get("road") or {}).get("location")
    if place is None and str(facts.get("road_type")).startswith("intersection"):
        place = "intersection"
    if place:
        asm["scene"]["location"] = place

    def party(tid):
        return asm["parties"].setdefault(str(tid), {})

    for field, val in answers.items():
        if field.startswith("parties."):
            _, tid, key = field.split(".", 2)
            if key == "movement" and val != "unknown":
                party(tid)["movement"] = val
            elif key == "cls":
                party(tid)["cls"] = val
            elif key == "entry_from":
                party(tid)["entry_from"] = val
            elif key in ("signal_at_entry", "signal_at_collision", "ped_signal_at_crossing"):
                party(tid)[key] = val
            elif key in ("unprotected_left_sign", "u_turn_type", "stop_state", "lane_change_dir", "overtake_type",
                         "ped_signal_green_at_turn", "position", "in_safety_zone_at_collision", "roundabout_action",
                         "roundabout_lane", "entry_lane_from", "big_entry", "damage_enlarged", "turn_signal_used",
                         "slowed_before_entry"):   # src/app/situation.py
                party(tid)[key] = val
            elif key == "parking_action":   # 주차장에서 한 일 → B의 세 사실 중 하나만 true (차51)
                for act, fact in situation.PARKING_FACTS.items():
                    party(tid)[fact] = val == act
            elif key == "emergency_mode":   # 긴급자동차가 달린 방식 (차55)
                party(tid)["driving_left_side"] = val == "left_side"
                party(tid)["overtaking"] = val == "overtaking"
            elif key == "driver_factors":   # 운전자 요인 (situation.DRIVER_FACTORS): 과속은 초과량으로, 나머지는 user_factors
                chosen = list(val or [])
                party(tid)["user_factors"] = [v for v in chosen if v not in situation.SPEED_OVER]
                over = [situation.SPEED_OVER[v] for v in chosen if v in situation.SPEED_OVER]
                if over:
                    party(tid)["speed_over_limit_kmh"] = max(over)
            elif key == "damage_severity":   # 이륜차 감산 (B two_wheeler_reduction)
                party(tid)[key] = val
            elif key == "lane_marking" and val != "unknown":
                party(tid)[key] = val
            elif key == "crossing_place":   # 보행자·자전거 사고 (src/app/chapters.py)
                party(tid)["crossing_place"] = val
                party(tid)["crossing_on_crosswalk"] = val == "on_crosswalk"   # B 명세의 이름 (차53-1)
            elif key == "intersection_entry":   # 답은 프레임 번호
                party(tid)["intersection_entry_t"] = round(val / fps, 3)
        elif field == "road.signal_present":
            asm["signal"] = {"state": "normal" if val else "none"}
        elif field == "road.center_line":
            asm["scene"]["center_line"] = bool(val)
            # 중앙선 없는 도로 = 골목길 (B 변환기의 ROAD_CLASS와 같은 기준). 있으면 일반 도로로 확정해서
            # B가 "road_class 모름"으로 남기지 않게 함
            asm["scene"]["road_class"] = "general" if val else "side_street"
        elif field == "road.wider_road":
            if val == "equal":
                asm["scene"]["road_width"] = "equal"
            else:
                asm["scene"]["road_width"] = "different"
                for tid, p in facts["parties"].items():
                    came = answers.get(f"parties.{tid}.entry_from", p.get("entry_from"))   # 답이 있으면 답 우선
                    if came:
                        party(tid)["on_wider_road"] = came in AXIS[val]
        elif field == "road.stop_sign_side":   # 일시정지 표지가 있던 쪽 → 당사자별 stop_sign
            for t in (facts["collision"]["a"], facts["collision"]["b"]):
                party(t)["stop_sign"] = str(val) in (str(t), "both")
        elif field == "pair.lead_order":       # 앞에 있던 차 → 당사자별 lead_order
            a, b = facts["collision"]["a"], facts["collision"]["b"]
            if str(val) in (str(a), str(b)):
                other = b if str(val) == str(a) else a
                party(val)["lead_order"], party(other)["lead_order"] = "leading", "following"
            # "side_by_side"(나란히)는 앞뒤가 없다는 답이라 lead_order를 넣지 않음 (좌우는 pair.right_side로)
        elif field == "pair.right_side":       # 나란히 가던 두 차 중 오른쪽 차 → 당사자별 side_in_pair (차20·21)
            a, b = facts["collision"]["a"], facts["collision"]["b"]
            if str(val) in (str(a), str(b)):
                other = b if str(val) == str(a) else a
                party(val)["side_in_pair"], party(other)["side_in_pair"] = "right", "left"
        elif field == "road.lane_fits_two":
            asm["scene"]["lane_fits_two"] = bool(val)
        elif field == "road.location":         # 교차로 안 / 벗어난 길 (판정용 facts의 장소는 비워 두고 여기서 넘김)
            asm["scene"]["location"] = val
        elif field == "road.roundabout_lanes":   # 회전교차로 회전 차로 수 (차54)
            asm["scene"]["roundabout_lanes"] = val
        elif field == "road.center_line_rule_not_applied":
            asm["scene"]["center_line_rule_not_applied"] = bool(val)
        elif field == "pair.u_turn_timing":    # 두 차 다 유턴 (차46-1): 두 당사자에 같은 값
            for t in (facts["collision"]["a"], facts["collision"]["b"]):
                party(t)["u_turn_timing"] = val
        elif field == "situation.special":     # 특수 상황 (긴급차, 일방통행 역주행, 문 열림 등)
            situation.special_assumptions(facts, val, party, asm["scene"])
        elif field == "intersection_entry_order":
            # 순서 질문은 A가 진입 시각 차이를 확실히 못 쟀을 때만 나오므로, 차이는 잰 값 대신 "얼마나 먼저였나"
            # 답(intersection_entry_clear)으로 정한다. 명확히 먼저면 B의 기준값(clear_lead_sec), 아니면 그 절반.
            # 답이 없으면 명확하지 않은 것으로 봄 (B의 "명확한 선진입"은 증거가 있어야 적용, needs_proof).
            # 예전엔 "먼저"를 무조건 1초로 올려 보내서 B 기준(1초, 임시값)에 늘 걸렸음 (cc_180629)
            a, b = facts["collision"]["a"], facts["collision"]["b"]
            if val == "same_time":
                party(a)["entry_lead_sec"] = party(b)["entry_lead_sec"] = 0.0
            else:
                clear = (facts.get("judge_thresholds") or {}).get("clear_lead_sec", SAME_TIME_SEC)
                lead = clear if answers.get("intersection_entry_clear") is True else round(clear / 2, 3)
                other = b if str(val) == str(a) else a
                party(val)["entry_lead_sec"] = lead
                party(other)["entry_lead_sec"] = -lead
    # 충돌 순간 신호 색은 진입 뒤 화면 신호가 바뀌었을 때만 물으므로, 안 물었으면 진입 때 색이 그대로라고 봄
    for p in asm["parties"].values():
        if "signal_at_entry" in p and "signal_at_collision" not in p:
            p["signal_at_collision"] = p["signal_at_entry"]
    return asm
