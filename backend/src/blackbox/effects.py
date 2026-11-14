"""차량 기록은 참고 자료 (docs/design-blackbox.md 4.4, 2026-11-10 설계 변경)

판정은 두 번 한다.
  base          영상·사용자 답·기본값만 (result)
  with_vehicle  base + 차량 기록 (result_with_vehicle). 차량 기록이 없으면 null
차량 기록이 답하던 질문도 base에서는 사용자에게 묻고(remaining), 차량 기록 값은 질문마다 참고(vehicle_hint)로 붙인다.

  hints(results, unusable)         차량 규칙 결과 → {질문 키: vehicle_hint}
  effects(base, with_v, hypo)      두 판정의 차이를 만든 기록 [vehicle_effect]. 결과가 같으면 []
  timeline(vreq, t_ms, grade)      충돌 전후 속도·지시등·브레이크·기어 요약 (앱 기록 보기 그래프)

vehicle_hint  {"value", "value_label", "text", "determined", "applied", "reason", "reason_text", "rule"}
vehicle_effect {"field", "label", "value", "value_label", "summary", "text", "rule", "applied", "reason", "reason_text",
                "ego_delta", "direction", "fault_by_party_if_applied"}
  applied=false: 시각 맞추기가 coarse/none이라 with_vehicle에도 쓰지 않은 타이밍 값. 정확히 맞췄다면(fine) 결과가
  바뀌었을 때만 목록에 넣고, 그때의 비율을 fault_by_party_if_applied로 준다.
"""
from src.blackbox import evidence
from src.vehicle import adapter as va
from src.vehicle.samples import Timeline, signal_intervals

EGO, OTHER = va.EGO, va.OTHER
LABELS = {
    "parties.ego.turn_signal_used": "방향지시등",
    "parties.ego.slowed_before_entry": "교차로 앞 서행",
    "parties.ego.stopped_before_entry": "교차로 앞 일시정지",
    "parties.ego.stationary_at_collision": "부딪힐 때 멈춤",
    "parties.ego.movement": "내 차 진행 방향",
    "parties.ego.lane_change_dir": "차로를 바꾼 방향",
}
REASONS = {
    "sync_coarse": "영상과 차량 기록의 시각을 대략만 맞춰서 이 기록은 결과에 넣지 않았어요",
    "sync_none": "영상과 차량 기록의 시각을 맞추지 못해 이 기록은 결과에 넣지 않았어요",
    "guess": "차량 기록만으로는 확실하지 않아 추정값으로만 보여 줘요",
}
TIMELINE_BEFORE_MS = 15_000   # 그래프: 충돌 15초 전부터
TIMELINE_AFTER_MS = 5_000     # 충돌 5초 뒤까지
TIMELINE_STEP_MS = 200        # 속도 점 간격 (최대 100개)


def _label(field):
    return LABELS.get(field) or evidence.FIELD_LABEL.get(field.split(".")[-1], "차량 기록")


def _value_label(field, value):
    return evidence.value_label(field, value)


# ---------- 질문 참고 ----------

def hints(results, unusable=lambda r: None):
    """차량 규칙 결과 → {질문 키: vehicle_hint}. unusable(결과) → 이유 코드(sync_coarse / sync_none) 또는 None"""
    out = {}
    for r in results or []:
        if r["determined"]:
            reason = unusable(r)
            out[r["field"]] = {"value": r["value"], "value_label": _value_label(r["field"], r["value"]),
                               "text": r["evidence"]["text"], "determined": True, "applied": reason is None,
                               "reason": reason, "reason_text": REASONS.get(reason), "rule": r["rule"]}
        elif r.get("model_guess") is not None:
            out[r["field"]] = {"value": r["model_guess"], "value_label": _value_label(r["field"], r["model_guess"]),
                               "text": r.get("guess_evidence"), "determined": False, "applied": False,
                               "reason": "guess", "reason_text": REASONS["guess"], "rule": r["rule"]}
    return out


# ---------- 차이를 만든 기록 ----------

def _key(result):
    return result["status"], result.get("rule_id"), result.get("fault_by_party")


def _ego_part(result, field):
    """field가 근거인 가감 요소들이 내 차 과실을 얼마나 바꿨나 (%p, 상대 몫 가감은 내 차 반대 방향)"""
    tot = 0
    for m in result.get("modifiers") or []:
        if any(field in va.fact_keys(f, m["party"]) for f in m["facts"]):
            tot += m["delta"] if m["party"] == EGO else -m["delta"]
    return tot


def _direction(d):
    return "ego_more" if d > 0 else "ego_less" if d < 0 else "changed"


def _overall(r0, r1):
    a, b = (r0.get("fault_by_party") or {}).get(EGO), (r1.get("fault_by_party") or {}).get(EGO)
    return b - a if a is not None and b is not None else None


def _diff_items(r0, a0, r1, a1, applied, reason, hint_map=None):
    """r0/a0(앞 판정의 result·answers) → r1/a1에서 값이 생기거나 바뀐 차량 기록 항목 중 차이를 만든 것"""
    fields = [f for f, u in a1.items() if u["source"] == "vehicle" and f != "parties.ego.cls"
              and not (a0.get(f, {}).get("source") == "vehicle" and a0[f]["value"] == u["value"])]
    if not fields or _key(r0) == _key(r1):
        return []
    deltas = {f: _ego_part(r1, f) - _ego_part(r0, f) for f in fields}
    if any(deltas.values()):
        fields = [f for f in fields if deltas[f]]
    else:   # 가감 요소가 아니라 도표가 바뀜 (예: 후진): 바뀐 항목 모두에 전체 차이
        whole = _overall(r0, r1)
        deltas = {f: whole for f in fields}
    out = []
    hint_map = hint_map or {}
    for f in fields:
        u, d = a1[f], deltas[f]
        h = hint_map.get(f) or {}
        out.append({"field": f, "label": _label(f), "value": u["value"], "value_label": _value_label(f, u["value"]),
                    "summary": evidence.sentence(f, u["value"]), "text": u.get("evidence") or h.get("text"),
                    "rule": u.get("rule") or h.get("rule"), "applied": applied, "reason": reason, "reason_text": REASONS.get(reason),
                    "ego_delta": d, "direction": _direction(d) if d is not None else "changed",
                    "fault_by_party_if_applied": None if applied else r1.get("fault_by_party")})
    return out


def effects(base, with_v, hypo=None, reason=None, hint_map=None):
    """base·with_v·hypo = {"result", "answers"}. hypo: 시각을 정확히 맞췄다고 보고 낸 판정 (coarse/none일 때만).
    반환: 차이를 만든 기록 목록. 결과가 같고 hypo도 같으면 []"""
    if with_v is None:
        return []
    out = _diff_items(base["result"], base["answers"], with_v["result"], with_v["answers"], True, None, hint_map)
    if hypo is not None:
        out += _diff_items(with_v["result"], with_v["answers"], hypo["result"], hypo["answers"], False, reason,
                           hint_map)
    return out


# ---------- 기록 보기 그래프 ----------

def _rel(t, t0):
    return round((t - t0) / 1000, 1)


def timeline(vreq, t_ms, grade, video_collision_t=None):
    """충돌 시각 t_ms(차량 시계) 전후 차량 기록 요약. 기록이나 충돌 시각이 없으면 None.
    시각은 충돌 기준 초(앞이 음수). 속도는 TIMELINE_STEP_MS마다 그 시각의 값(기록 없으면 null)"""
    if not vreq or not vreq.get("samples") or t_ms is None:
        return None
    rng = vreq["range"]
    tl = Timeline(vreq["samples"], end=rng["to"])
    a, b = max(rng["from"], t_ms - TIMELINE_BEFORE_MS), min(rng["to"], t_ms + TIMELINE_AFTER_MS)
    if a >= b:
        return None
    speed = []
    for t in range(a, b + 1, TIMELINE_STEP_MS):
        v = tl.state("speedKmh", t)
        speed.append([_rel(t, t_ms), round(v, 1) if v is not None else None])
    known = [v for _, v in speed if v is not None]
    gears = []
    for s, e, v, kind in tl.pieces("gear", a, b):
        if kind != "data" or v is None:
            continue
        if gears and gears[-1]["value"] == v and gears[-1]["to"] == _rel(s, t_ms):
            gears[-1]["to"] = _rel(e, t_ms)
        else:
            gears.append({"value": v, "from": _rel(s, t_ms), "to": _rel(e, t_ms)})
    return {
        "t0_ms": t_ms, "from_s": _rel(a, t_ms), "to_s": _rel(b, t_ms), "step_s": TIMELINE_STEP_MS / 1000,
        "collision_s": 0.0, "video_collision_t": video_collision_t,
        "sync_grade": grade, "aligned": grade in ("fine", "user"),
        "speed": speed, "speed_max": round(max(known), 1) if known else None,
        "turn_signal": [{"dir": d, "from": _rel(s, t_ms), "to": _rel(e, t_ms)} for d, s, e in signal_intervals(tl, a, b)],
        "brake": [{"from": _rel(s, t_ms), "to": _rel(e, t_ms)} for s, e in tl.intervals("brake", a, b, lambda v: v is True)],
        "gear": gears,
        "gaps": [{"from": _rel(g["from"], t_ms), "to": _rel(g["to"], t_ms)} for g in tl.gaps()
                 if g["to"] > a and g["from"] < b],
    }
