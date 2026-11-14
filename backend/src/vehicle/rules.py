"""자동 답변 규칙 v0 (docs/api-spec.md 4절)

규칙마다 결과 dict 하나를 돌려준다 (해당 없으면 None).

  정함 (자동 답변):  {"field", "value", "source": "vehicle", "rule", "evidence": {"text", "window", "points"},
                     "determined": True, "facts", "params"}
  못 정함:           {"field", "rule", "determined": False, "value": None,
                     "model_guess", "guess_source", "guess_evidence", "facts", "params"}

- facts: 질문 없이 판정에 넘길 사실 (예: stopped_before_entry). 모두 출처 vehicle.
- params: 판정에 쓴 계산값 (LEAD, 평균 속도 등). 저장·설명용.
- auto_answer(결과)는 3절 자동 답변 모양만 남긴다.

모든 숫자는 임시값이다 (4절). 규칙을 고치면 아래 버전 이름을 올린다.
"""
from src.vehicle.samples import signal_intervals

TURN_SIGNAL = "turn_signal_v0"
SLOWED = "slowed_v0"
REVERSE = "reverse_v0"
MOVEMENT = "movement_v0"
LANE_CHANGE_DIR = "lane_change_dir_v0"

HARD_BRAKE_CUT_MS = -1500       # hard_brake면 [-1500, 0]은 충돌 직전 제동 구간 (4.1)

# 지시등 (4.4)
TS_WINDOW_MS = -10000
TS_MIN_ON_MS = 1000
LEAD_DIST_M = 30.0
LEAD_MIN_MS, LEAD_MAX_MS = 2000, 5000
LEAD_STILL_KMH = 1.0
LEAD_SPEED_FROM_MS = -5000
MANUAL_LEAD_SPEED_TO_MS = -500

# 서행 (4.5)
REF_MS = (-6000, -3000)
PRE_FROM_MS = -3000
MANUAL_PRE_TO_MS = -500
STOP_KMH, STOP_MIN_MS = 3.0, 500
SLOW_KMH = 15.0
SLOW_RATIO, SLOW_BRAKE_MS = 0.7, 500
KEEP_RATIO, KEEP_MIN_KMH = 0.9, 20.0

# 후진 (4.2)
REV_WINDOW_MS = -3000
REV_RATIO = 0.6

# 진행 방향 (4.3), 진로 변경 방향 (4.6)
SIG_WINDOW_MS = (-8000, -1500)
SIG_MIN_ON_MS = 1000
STILL_WINDOW_MS = -3000
STILL_KMH = 2.0
STILL_GEARS = ("P", "N", "D")
STRAIGHT_WINDOW_MS = -8000
STRAIGHT_MIN_KMH = 15.0

TURNING = ("left_turn", "right_turn", "u_turn", "lane_change")

GAP_TEXT = "사고 전 기록이 2초 넘게 끊긴 곳이 있어요"
HARD_BRAKE_ONLY_TEXT = "사고 직전 1.5초 안에만 켜져 판단에서 제외했어요"
BOTH_SIDES_TEXT = "양쪽 지시등이 함께 켜졌어요(비상등 가능성)"


class Ctx:
    """사고 시각 T와 t_event_source"""

    def __init__(self, t_event, source):
        if source not in ("hard_brake", "manual"):
            raise ValueError(f"t_event_source: {source}")
        self.T = t_event
        self.source = source

    @property
    def hard_brake(self):
        return self.source == "hard_brake"

    def at(self, rel_ms):
        return self.T + rel_ms

    def cut(self, manual_end_ms):
        """판단 구간의 끝: hard_brake면 -1500, manual이면 manual_end_ms (T 기준)"""
        return self.T + (HARD_BRAKE_CUT_MS if self.hard_brake else manual_end_ms)


# ---------- 결과 만들기 ----------

def sec(ms):
    """ms → "3.2" (소수 한 자리, .0은 뺌)"""
    return f"{round(abs(ms) / 1000, 1):g}"


def kmh(v):
    return f"{round(v)}km/h"


def _auto(field, value, rule, text, window, points=(), facts=None, params=None, **extra):
    return {"field": field, "value": value, "source": "vehicle", "rule": rule, "determined": True,
            "evidence": {"text": text, "window": {"from": window[0], "to": window[1]}, "points": list(points)},
            "facts": facts or {}, "params": params or {}, **extra}


def _undetermined(field, rule, guess=None, evidence=None, facts=None, params=None):
    return {"field": field, "rule": rule, "determined": False, "value": None,
            "model_guess": guess, "guess_source": "vehicle" if guess is not None else None,
            "guess_evidence": evidence, "facts": facts or {}, "params": params or {}}


def _point(t, key, value):
    return {"t": t, "key": key, "value": value}


def auto_answer(result):
    """규칙 결과 → 3절 자동 답변 {field, value, source, rule, evidence}. 못 정했으면 None"""
    if not result or not result["determined"]:
        return None
    return {k: result[k] for k in ("field", "value", "source", "rule", "evidence")}


# ---------- turn_signal_v0 (4.4) ----------

def lead_ms(v_kmh):
    """LEAD = clamp(30m ÷ 평균 속도, 2초, 5초) (D3). 거의 서 있으면(1km/h 미만) 5초. 속도를 모르면 None"""
    if v_kmh is None:
        return None
    if v_kmh < LEAD_STILL_KMH:
        return LEAD_MAX_MS
    return round(min(max(LEAD_DIST_M / (v_kmh / 3.6) * 1000, LEAD_MIN_MS), LEAD_MAX_MS))


SIDE = {"LEFT": "왼쪽", "RIGHT": "오른쪽"}


def side(d):
    """차량 신호 값(LEFT/RIGHT) → 화면 문장용 이름 (왼쪽/오른쪽)"""
    return SIDE.get(d, d)


def _expected(movement, lane_change_dir):
    if movement in ("left_turn", "u_turn"):
        return ("LEFT",)
    if movement == "right_turn":
        return ("RIGHT",)
    if lane_change_dir in ("left", "right"):
        return (lane_change_dir.upper(),)
    return ("LEFT", "RIGHT")


def turn_signal(tl, ctx, movement, lane_change_dir=None):
    """parties.ego.turn_signal_used. movement(사용자 답 또는 자동 답변)가 회전·진로 변경일 때만 계산"""
    if movement not in TURNING:
        return None
    field, T = "parties.ego.turn_signal_used", ctx.T
    a, b = ctx.at(TS_WINDOW_MS), ctx.cut(0)
    if tl.has_gap(a, b):
        return _undetermined(field, TURN_SIGNAL, evidence=GAP_TEXT)
    if tl.known("turnSignal", a, b) == 0:
        return _undetermined(field, TURN_SIGNAL, evidence="사고 전 지시등 기록이 없어요")
    v_avg = tl.mean("speedKmh", ctx.at(LEAD_SPEED_FROM_MS), ctx.cut(MANUAL_LEAD_SPEED_TO_MS))
    lead = lead_ms(v_avg)
    if lead is None:
        return _undetermined(field, TURN_SIGNAL, evidence="사고 전 속도 기록이 없어 지시등을 언제까지 켜야 했는지 알 수 없어요")
    params = {"lead_ms": lead, "v_avg_kmh": round(v_avg, 1)}
    exp = _expected(movement, lane_change_dir)
    label = f"{side(exp[0])} " if len(exp) == 1 else ""
    ivs = signal_intervals(tl, a, b)
    mine = [iv for iv in ivs if iv[0] in exp]

    def done(value, text, points=()):
        return _auto(field, value, TURN_SIGNAL, text, (a, b), points, params=params)

    if not mine:
        late = [iv for iv in signal_intervals(tl, b, T) if iv[0] in exp] if ctx.hard_brake else []
        if late and not ivs:
            d, s, _ = late[0]
            return done(False, HARD_BRAKE_ONLY_TEXT, [_point(s, "turnSignal", d)])
        if ivs and len(exp) == 1:
            d, s, _ = ivs[-1]
            return done(False, f"{side(exp[0])}이 아니라 {side(d)} 지시등을 켰어요", [_point(s, "turnSignal", d)])
        return done(False, f"사고 전 {sec(TS_WINDOW_MS)}초 동안 {label}지시등을 켜지 않았어요")

    d, s, e = mine[-1]    # 마지막으로 이어진 켜짐
    pts = [_point(s, "turnSignal", d)]
    if s > T - lead:
        need = "거의 서 있어서" if v_avg < LEAD_STILL_KMH else f"평균 {kmh(v_avg)}라"
        return done(False, f"사고 {sec(T - s)}초 전에야 {side(d)} 지시등을 켰어요 ({need} {sec(lead)}초 전에는 켜야 해요)", pts)
    if e - s < TS_MIN_ON_MS:
        return done(False, f"사고 {sec(T - s)}초 전 {side(d)} 지시등을 {sec(e - s)}초만 켰어요", pts)
    until = "사고 때까지 켜져 있음" if e >= b else f"{sec(e - s)}초 동안"
    return done(True, f"사고 {sec(T - s)}초 전 {side(d)} 지시등 켜짐 ({until})", pts)


# ---------- slowed_v0 (4.5) ----------

def slowed(tl, ctx):
    """parties.ego.slowed_before_entry. 진입 시각을 "충돌 1.5~3초 전"으로 가정 (D5).
    질문 조건(교차로·신호 없음)은 보지 않는다. 미리 계산해 두고 쓰는 쪽이 조건을 본다"""
    field, T = "parties.ego.slowed_before_entry", ctx.T
    ref = (ctx.at(REF_MS[0]), ctx.at(REF_MS[1]))
    pre = (ctx.at(PRE_FROM_MS), ctx.cut(MANUAL_PRE_TO_MS))
    window = (ref[0], pre[1])
    facts = {"intersection_entry_speed_kmh": tl.state("speedKmh", pre[0])}
    if tl.has_gap(*window):
        return _undetermined(field, SLOWED, evidence=GAP_TEXT, facts=facts)
    if tl.known("speedKmh", *ref) == 0 or tl.known("speedKmh", *pre) == 0:
        return _undetermined(field, SLOWED, evidence="사고 전 속도 기록이 없어요", facts=facts)

    stop_ms = tl.duration("speedKmh", *pre, lambda v: v <= STOP_KMH)
    v_ref, ref_s, ref_e = tl.peak("speedKmh", *ref, mode=max)
    v_pre, pre_s, _ = tl.peak("speedKmh", *pre, mode=min)
    brake_ms = tl.duration("brake", *pre, lambda v: v is True) if tl.known("brake", *pre) else None
    params = {"v_ref_kmh": v_ref, "v_pre_kmh": v_pre, "brake_pre_ms": brake_ms, "stop_ms": stop_ms}
    pts = [_point(ref_s, "speedKmh", v_ref), _point(pre_s, "speedKmh", v_pre)]

    def done(value, text, points=pts, **more):
        return _auto(field, value, SLOWED, text, window, points, facts={**facts, **more}, params=params)

    if stop_ms >= STOP_MIN_MS:
        return done(True, f"진입 전 {sec(stop_ms)}초 동안 멈췄어요", stopped_before_entry=True)
    change = f"사고 {sec(T - ref_e)}초 전 {kmh(v_ref)} → 직전 {kmh(v_pre)}로 줄였어요"
    if brake_ms:
        change += f" (브레이크 {sec(brake_ms)}초)"
    if v_pre <= SLOW_KMH or (v_pre <= SLOW_RATIO * v_ref and brake_ms is not None and brake_ms >= SLOW_BRAKE_MS):
        return done(True, change)
    keep = f"{kmh(tl.mean('speedKmh', *pre))} 안팎으로 달렸어요"
    if brake_ms == 0 and v_pre >= KEEP_RATIO * v_ref and v_pre >= KEEP_MIN_KMH:
        return done(False, f"사고 직전까지 브레이크 없이 {keep}")
    if v_pre < v_ref:
        return _undetermined(field, SLOWED, True, change, facts, params)
    return _undetermined(field, SLOWED, False, f"사고 직전까지 {keep}", facts, params)


# ---------- reverse_v0 (4.2) ----------

def reverse(tl, ctx):
    """parties.ego.movement = reverse. [-3000, 0]에 R이 없으면 None"""
    field, T = "parties.ego.movement", ctx.T
    a, b = ctx.at(REV_WINDOW_MS), T
    if tl.has_gap(a, b):
        return _undetermined(field, REVERSE, evidence=GAP_TEXT)
    r_ms = tl.duration("gear", a, b, lambda g: g == "R")
    if r_ms == 0:
        return None
    params = {"r_ms": r_ms}
    at_t = tl.state("gear", T) == "R"
    text = f"사고 직전 {sec(REV_WINDOW_MS)}초 중 {sec(r_ms)}초 동안 기어가 R(후진)이었어요"
    if at_t and r_ms >= REV_RATIO * (b - a):
        s = tl.intervals("gear", a, b, lambda g: g == "R")[-1][0]
        return _auto(field, "reverse", REVERSE, text, (a, b), [_point(s, "gear", "R")], params=params,
                     preselect={"situation.special": ["reverse:ego"]})
    if not at_t:
        e = tl.intervals("gear", a, b, lambda g: g == "R")[-1][1]
        text = f"사고 {sec(T - e)}초 전까지 후진 기어였어요"
    return _undetermined(field, REVERSE, "reverse", text, params=params)


# ---------- movement_v0 (4.3) ----------

def movement(tl, ctx):
    """parties.ego.movement. 위치 궤적이 없어 후진만 자동 답변하고 나머지는 추정값만 (4.3 표 순서)"""
    field, T = "parties.ego.movement", ctx.T

    # 1. 후진 확정 → 자동 답변 그대로 / 1-1. 후진 추정 (4.2 "그 밖")
    rv = reverse(tl, ctx)
    if rv and rv["determined"]:
        return rv
    if rv and rv["model_guess"]:
        return _undetermined(field, MOVEMENT, "reverse", rv["guess_evidence"], params=rv["params"])

    # 4번 조건(서 있었음)은 2·3번의 양쪽 지시등 경우에도 사실로 넘기므로 먼저 계산
    a = ctx.at(STILL_WINDOW_MS)
    still = (not tl.has_gap(a, T)
             and tl.duration("speedKmh", a, T, lambda v: v <= STILL_KMH) == T - a
             and tl.duration("gear", a, T, lambda g: g in STILL_GEARS) == T - a)
    still_facts = {"stationary_at_collision": True} if still else {}

    # 2·3. [-8000, -1500]에 LEFT / RIGHT가 1초 이상. 둘 다면 비상등일 수 있어 추정 안 함
    a, b = ctx.at(SIG_WINDOW_MS[0]), ctx.at(SIG_WINDOW_MS[1])
    if not tl.has_gap(a, b):
        ivs = signal_intervals(tl, a, b)
        q = {d: [iv for iv in ivs if iv[0] == d and iv[2] - iv[1] >= SIG_MIN_ON_MS] for d in ("LEFT", "RIGHT")}
        if q["LEFT"] and q["RIGHT"]:
            return _undetermined(field, MOVEMENT, evidence=BOTH_SIDES_TEXT, facts=still_facts)
        for d, guess in (("LEFT", "left_turn"), ("RIGHT", "right_turn")):
            if q[d]:
                return _undetermined(field, MOVEMENT, guess, f"사고 {sec(T - q[d][-1][1])}초 전부터 {side(d)} 지시등이 켜져 있었어요")

    # 4. [-3000, 0] 내내 2km/h 이하이고 기어 P/N/D → 서 있었음 (사실만 넘김, D7)
    if still:
        return _undetermined(field, MOVEMENT, evidence="사고 때 내 차는 서 있었어요", facts=still_facts)

    # 5. [-8000, 0]에 지시등이 한 번도 안 켜졌고 평균 15km/h 이상 → 직진
    a = ctx.at(STRAIGHT_WINDOW_MS)
    if not tl.has_gap(a, T) and tl.known("turnSignal", a, T) and not signal_intervals(tl, a, T):
        v = tl.mean("speedKmh", a, T)
        if v is not None and v >= STRAIGHT_MIN_KMH:
            return _undetermined(field, MOVEMENT, "straight", f"사고 전 {sec(STRAIGHT_WINDOW_MS)}초 동안 지시등을 켜지 않고 달렸어요",
                                 params={"v_avg_kmh": round(v, 1)})

    return _undetermined(field, MOVEMENT)


# ---------- lane_change_dir_v0 (4.6) ----------

def lane_change_dir(tl, ctx, movement):
    """parties.ego.lane_change_dir. 진행 방향이 lane_change이고 [-8000, -1500]에 한쪽 지시등만 켜졌으면 그 방향"""
    if movement != "lane_change":
        return None
    field, T = "parties.ego.lane_change_dir", ctx.T
    a, b = ctx.at(SIG_WINDOW_MS[0]), ctx.at(SIG_WINDOW_MS[1])
    if tl.has_gap(a, b):
        return _undetermined(field, LANE_CHANGE_DIR, evidence=GAP_TEXT)
    ivs = signal_intervals(tl, a, b)
    dirs = {d for d, _, _ in ivs}
    if len(dirs) != 1:
        return _undetermined(field, LANE_CHANGE_DIR)
    d, s, _ = ivs[0]
    return _auto(field, d.lower(), LANE_CHANGE_DIR, f"사고 {sec(T - s)}초 전 {side(d)} 지시등을 켰어요", (a, b),
                 [_point(s, "turnSignal", d)])


# ---------- 묶어 돌리기 ----------

def run_rules(tl, ctx, answers=None):
    """규칙 5개를 의존 순서대로 돌린 결과 목록 (해당 없는 규칙은 빠짐).
    answers: 사용자 답 {field: value}. 사용자 답이 있으면 자동 답변보다 우선해서 다음 규칙의 입력이 된다 (D9).
    진행 방향은 사용자 답 또는 자동 답변(후진)일 때만 지시등·진로 변경 방향 계산에 쓴다 (추정값은 안 씀)"""
    answers = answers or {}

    def decided(field, result):
        if field in answers:
            return answers[field]
        return result["value"] if result and result["determined"] else None

    mv = movement(tl, ctx)
    mv_value = decided("parties.ego.movement", mv)
    lcd = lane_change_dir(tl, ctx, mv_value)
    ts = turn_signal(tl, ctx, mv_value, decided("parties.ego.lane_change_dir", lcd))
    return [r for r in (mv, lcd, ts, slowed(tl, ctx)) if r]
