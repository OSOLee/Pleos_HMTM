"""여러 개 고르기 질문(situation.special 특수 상황, parties.<ego|other>.driver_factors 운전자 요인)의 답 (2026-11-11)

MTM(answers.to_assumptions → situation.special_assumptions)은 보여 준 보기 중 안 고른 것을 "아니요"로 넘긴다.
그러면 "밤이었음"을 안 고른 사람의 답이 영상의 "밤"을 이긴다. 블랙박스 사건은 이렇게 바꾼다:

  - 고른 보기만 사용자 답 (영상 값을 이기고, 다르면 source_conflicts)
  - 안 고른 보기는 답 없음: 영상 값이 있으면 영상, 없으면 기본값 (빈 목록 []도 답 없음)
  - "해당 없음"(보기 값 NONE)을 고르면 그때만 전부 "아니요" (MTM 변환 그대로)

src/app은 고치지 않는다: 이 두 질문을 to_assumptions에서 빼고 여기서 가정으로 바꾼다.
"""
from src.app import situation
from src.vehicle.samples import VehicleError

NONE = "none"
NONE_CHOICE = "해당 없음 (모두 아니요)"
SPECIAL = "situation.special"


def is_multi(field):
    return field == SPECIAL or (isinstance(field, str) and field.startswith("parties.")
                                and field.endswith(".driver_factors"))


def with_none(q):
    """여러 개 고르기 질문에 "해당 없음" 보기를 맨 끝에 더함"""
    if q.get("answer_type") != "multi" or NONE in q["options"]:
        return q
    q = dict(q, options=q["options"] + [NONE], choices=(q.get("choices") or q["options"]) + [NONE_CHOICE])
    if q.get("all_options") is not None:
        q["all_options"] = q["all_options"] + [NONE]
    if q.get("option_groups") is not None:
        q["option_groups"] = q["option_groups"] + ["일반"]
    return q


def check(user):
    """"해당 없음"을 다른 보기와 같이 고르면 오류"""
    for f, v in user.items():
        if is_multi(f) and isinstance(v, list) and NONE in v and len(v) > 1:
            raise VehicleError("answer_invalid", f"답을 확인해 주세요: {f}에서 '해당 없음'은 다른 보기와 같이 고를 수 없어요")


def strip(mtm_user):
    """to_assumptions에 넘기지 않을 답 (이 모듈이 따로 바꿈)"""
    return {k: v for k, v in mtm_user.items() if not is_multi(k)}


def assumptions(facts, asm, user, video_def):
    """여러 개 고르기 답 → 판정 가정 (asm에 더함, 제자리). video_def: 영상 확정값 {질문 키: {value}}"""
    parties = asm.setdefault("parties", {})
    scene = asm.setdefault("scene", {})

    def party(t):
        return parties.setdefault(str(t), {})

    for field, val in user.items():
        if not is_multi(field) or not isinstance(val, list):
            continue
        explicit_none = val == [NONE]
        if field == SPECIAL:
            if explicit_none:                     # 보여 준 보기 전부 아니요 (MTM 그대로)
                situation.special_assumptions(facts, [], party, scene)
            elif val:
                _special_chosen(facts, val, party, scene)
            continue
        pid = field.split(".")[1]
        p = party(pid)
        if explicit_none:
            p["user_factors"], p["speed_over_limit_kmh"] = [], 0
            continue
        chosen = [v for v in val if v != NONE]
        factors = [v for v in chosen if v not in situation.SPEED_OVER]
        if factors:                               # 고른 것 + 영상이 낸 것 (안 고른 것은 답 없음)
            vid = (video_def.get(f"parties.{pid}.user_factors") or {}).get("value") or []
            p["user_factors"] = factors + [v for v in vid if v not in factors]
        over = [situation.SPEED_OVER[v] for v in chosen if v in situation.SPEED_OVER]
        if over:
            p["speed_over_limit_kmh"] = max(over)
    return asm


def _special_chosen(facts, chosen, party, scene):
    """MTM special_assumptions를 그대로 돌리고 고른 보기에서 나온 값만 남김 (안 고른 보기의 false·기본값은 버림)"""
    tmp_parties, tmp_scene = {}, {}
    situation.special_assumptions(facts, chosen, lambda t: tmp_parties.setdefault(str(t), {}), tmp_scene)
    picked = set(map(str, chosen))
    for t, kv in tmp_parties.items():
        for key, fact, _, _ in situation.SPECIAL:
            if fact is None or f"{key}:{t}" not in picked:
                continue
            name = "movement" if fact.startswith("movement=") else fact
            if name in kv:
                party(t)[name] = kv[name]
    for key, fact, *_ in situation.SPECIAL_SCENE:
        if key in picked and fact in tmp_scene:
            scene[fact] = tmp_scene[fact]


def _special_facts(val):
    """특수 상황 답이 정한 사실 이름 (고른 보기의 사실. "해당 없음"이면 모든 보기의 사실)"""
    if not isinstance(val, list) or not val:
        return set()
    every = val == [NONE]
    picked = {str(v).partition(":")[0] for v in val}
    out = {f.split("=")[0] for k, f, *_ in situation.SPECIAL if f and (every or k in picked)}
    out |= {f for k, f, *_ in situation.SPECIAL_SCENE if every or k in picked}
    return out


def source_keys(keys, fact, user):
    """가감 요소 출처를 찾을 질문 키 (va.fact_keys 결과). 특수 상황 답은 그 사실을 정한 보기를 골랐을 때만 넣음
    (안 고른 보기는 답이 아니라서, 영상이 정한 밤 가산이 "사용자"로 보이지 않게)"""
    name = str(fact).split(".")[-1]
    keys = [k for k in keys if k != SPECIAL]
    if name in _special_facts(user.get(SPECIAL)):
        keys.append(SPECIAL)
    return keys
