"""정보 합치기 (docs/design-blackbox.md 4절, 확정 Q7·Q9)

같은 항목에 값이 여럿이면 user > vehicle > video > default.
- 확실한 값(사용자 답, 차량 규칙 자동 답변·사실, 영상 value)이 추정값보다 앞선다.
- 확실한 값끼리 다르면 이긴 값을 쓰고 source_conflicts에 남긴다 (user_vs_vehicle / user_vs_video / vehicle_vs_video).
- 확실한 값이 없으면 추정값: 차량·영상 추정이 같으면 그 값, 다르면 미리 고르지 않음(guess_mismatch).
- 시각 맞추기가 coarse면 시각에 민감한 차량 규칙(지시등·서행·진로 변경 방향)은 추정값으로만 쓴다. none이면 차량 규칙을 쓰지 않는다.

항목 키는 질문 키(자기 차 기준 보기)다: parties.<ego|other>.<이름>, road.<이름>, scene.place, scene.junction_type.
"""
from src.blackbox import evidence
from src.vehicle import rules
from src.vehicle.adapter import ENTRY_TO_COMPASS, RULE_FACTS

PRIORITY = ("user", "vehicle", "video")
FULL_GRADES = ("fine", "user")                         # 차량 기록을 전부 쓰는 시각 맞추기 등급
COMPASS_TO_ENTRY = {v: k for k, v in ENTRY_TO_COMPASS.items()}
ROAD_TO_FIELD = {"location": "scene.place", "junction_type": "scene.junction_type"}
QUESTION_ROAD = ("signal_present", "center_line")      # 질문 키가 road.<이름>인 도로 값
# 시각에 민감한 차량 규칙 (5.3 coarse 표): 사고 직전 몇 초 구간을 봄
TIMING_RULES = (rules.TURN_SIGNAL, rules.SLOWED, rules.LANE_CHANGE_DIR)
TIMING_FACTS = ("stopped_before_entry",)               # 서행 규칙이 내는 사실
COARSE_NOTE = " (영상과 차량 기록 시각을 대략만 맞춰 추정으로만 썼어요)"


def video_values(facts):
    """분석기 facts → (확실한 값 {키: {value, evidence}}, 추정값 {키: {guess, evidence}}, 질문 아닌 값 {당사자: {이름: 값}})"""
    definite, guesses, extra = {}, {}, {"ego": {}, "other": {}}
    if not facts:
        return definite, guesses, extra
    items = []
    for pid, p in (facts.get("parties") or {}).items():
        for k, v in p.items():
            if isinstance(v, dict) and "value" in v:
                items.append((f"parties.{pid}.{k}", v, pid == "other" and k == "entry_from"))
            else:
                extra.setdefault(pid, {})[k] = v          # intersection_entry {frame, t} 등
    for k, v in (facts.get("road") or {}).items():
        if isinstance(v, dict) and "value" in v:
            field = ROAD_TO_FIELD.get(k, f"road.{k}")
            items.append((field, v, False))
    for field, v, compass in items:
        conv = (lambda x: COMPASS_TO_ENTRY.get(x, x)) if compass else (lambda x: x)
        if v.get("value") is not None:
            definite[field] = {"value": conv(v["value"]),
                               "evidence": evidence.for_video(field, conv(v["value"]), v.get("t"))}
        elif v.get("guess") is not None:
            guesses[field] = {"guess": conv(v["guess"]),
                              "evidence": evidence.for_video_guess(field, conv(v["guess"]), v.get("t"))}
    return definite, guesses, extra


def vehicle_values(results, grade):
    """차량 규칙 결과 → (확실한 값, 추정값, 쓴 결과). grade: coarse / fine / user / none"""
    definite, guesses, used = {}, {}, []
    if grade not in ("coarse", "fine", "user"):
        return definite, guesses, used
    coarse = grade == "coarse"
    for r in results:
        timing = coarse and r["rule"] in TIMING_RULES
        if r["determined"] and not timing:
            definite[r["field"]] = {"value": r["value"], "evidence": r["evidence"]["text"], "rule": r["rule"]}
        elif r["determined"]:
            guesses[r["field"]] = {"guess": r["value"], "evidence": r["evidence"]["text"] + COARSE_NOTE}
        elif r.get("model_guess") is not None:
            guesses[r["field"]] = {"guess": r["model_guess"], "evidence": r.get("guess_evidence")}
        for k, v in (r.get("facts") or {}).items():
            if k in RULE_FACTS and v is not None and not (coarse and (timing or k in TIMING_FACTS)):
                text = r["evidence"]["text"] if r["determined"] else (r.get("guess_evidence") or "차량 기록")
                definite[f"parties.ego.{k}"] = {"value": v, "evidence": text, "rule": r["rule"]}
        used.append(r)
    return definite, guesses, used


def merge(user, vehicle, video, vehicle_guess=None, video_guess=None):
    """반환 (decided {키: {value, source, evidence}}, guesses {키: {model_guess, guess_source, guess_evidence}},
    source_conflicts [...])"""
    vehicle_guess, video_guess = vehicle_guess or {}, video_guess or {}
    by_source = {"user": {k: {"value": v, "evidence": None} for k, v in user.items()}, "vehicle": vehicle, "video": video}
    decided, conflicts = {}, []
    for field in sorted(set(user) | set(vehicle) | set(video)):
        cands = [(s, by_source[s][field]) for s in PRIORITY if field in by_source[s]]
        src, win = cands[0]
        decided[field] = {"value": win["value"], "source": src, "evidence": win.get("evidence")}
        others = [(s, c) for s, c in cands[1:] if c["value"] != win["value"]]
        if others:
            conflicts.append({"field": field, "used": {"value": win["value"], "source": src},
                              "others": [{"value": c["value"], "source": s, "evidence": c.get("evidence")}
                                         for s, c in others],
                              "evidence": win.get("evidence"), "kind": f"{src}_vs_{others[0][0]}"})
    guesses = {}
    for field in sorted((set(vehicle_guess) | set(video_guess)) - set(decided)):
        vg, wg = vehicle_guess.get(field), video_guess.get(field)
        if vg and wg and vg["guess"] != wg["guess"]:
            guesses[field] = {"model_guess": None, "guess_source": None,
                              "guess_evidence": " / ".join(x for x in (vg["evidence"], wg["evidence"]) if x)}
            conflicts.append({"field": field, "used": None,
                              "others": [{"value": vg["guess"], "source": "vehicle", "evidence": vg["evidence"]},
                                         {"value": wg["guess"], "source": "video", "evidence": wg["evidence"]}],
                              "evidence": None, "kind": "guess_mismatch"})
        elif vg:
            ev = " / ".join(x for x in (vg["evidence"], wg and wg["evidence"]) if x)
            guesses[field] = {"model_guess": vg["guess"], "guess_source": "vehicle", "guess_evidence": ev or None}
        else:
            guesses[field] = {"model_guess": wg["guess"], "guess_source": "video", "guess_evidence": wg["evidence"]}
    return decided, guesses, conflicts


def source_of(sources):
    """여러 근거 사실의 출처 → 하나 (2.7을 넓힘): user > vehicle > video > default"""
    for s in PRIORITY:
        if s in sources:
            return s
    return "default"
