"""차량 기록(samples) 검사와 읽기 (docs/api-spec.md 2.1 기록 해석, 4.1 공통)

기록 해석
- 각 기록 값은 다음 기록이 올 때까지 유지된다. 시각 t의 상태 = t 이전(t 포함) 마지막 기록.
- 두 기록 사이가 GAP_MS보다 벌어지면 그 사이는 "기록 없음"(값 None)이다.
- 첫 기록 앞, 끝(end) 뒤도 기록 없음이다.

모든 시각은 epoch ms 정수. 구간은 [a, b) (a 포함, b 제외).
"""
import bisect
import math

MAX_RANGE_MS = 120_000      # 한 사건에 올리는 구간 최대 길이
MIN_BEFORE_MS = 3_000       # t_event 앞에 있어야 할 기록 길이
MAX_SAMPLES = 20_000
GAP_MS = 2_000              # 두 기록 사이가 이보다 길면 빈 곳
BLINK_MAX_OFF_MS = 1_500    # 같은 방향 지시등 사이 OFF가 이 이하면 이어진 켜짐 (D4)

KEYS = ("t", "speedKmh", "gear", "turnSignal", "brake")
GEARS = ("P", "R", "N", "D")
SIGNALS = ("LEFT", "RIGHT", "OFF")
EGO_CLASSES = ("car", "truck", "bus", "two_wheeler")
EVENT_SOURCES = ("hard_brake", "manual")


class VehicleError(Exception):
    """차량 사건 요청 오류. API가 {"error": code, "message": message}로 바꾼다"""

    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_sample(i, s, lo, hi):
    def bad(why):
        raise VehicleError("sample_invalid", f"samples[{i}]: {why}")

    if not isinstance(s, dict):
        bad("항목은 객체여야 해요")
    missing = [k for k in KEYS if k not in s]
    if missing:
        bad(f"{', '.join(missing)} 값이 없어요")
    t = s["t"]
    if not _is_int(t):
        bad("t는 epoch 밀리초 정수여야 해요")
    if not lo <= t <= hi:
        bad("t가 range 밖이에요")
    v = s["speedKmh"]
    if v is not None and not (_is_num(v) and v >= 0):
        bad("speedKmh는 0 이상의 숫자 또는 null이어야 해요")
    if s["gear"] is not None and s["gear"] not in GEARS:
        bad("gear는 P, R, N, D 중 하나 또는 null이어야 해요")
    if s["turnSignal"] is not None and s["turnSignal"] not in SIGNALS:
        bad("turnSignal은 LEFT, RIGHT, OFF 중 하나 또는 null이어야 해요")
    if s["brake"] is not None and not isinstance(s["brake"], bool):
        bad("brake는 true, false 또는 null이어야 해요")
    return {k: s[k] for k in KEYS}


def validate(body):
    """POST /api/vehicle-cases 요청 검사 (2.1). 맞으면 정리한 dict, 틀리면 VehicleError"""
    if not isinstance(body, dict):
        raise VehicleError("request_invalid", "요청은 JSON 객체여야 해요")

    rng = body.get("range")
    if not (isinstance(rng, dict) and _is_int(rng.get("from")) and _is_int(rng.get("to"))):
        raise VehicleError("range_invalid", "range.from, range.to는 epoch 밀리초 정수여야 해요")
    lo, hi = rng["from"], rng["to"]
    if lo >= hi:
        raise VehicleError("range_invalid", "range.from은 range.to보다 앞이어야 해요")
    if hi - lo > MAX_RANGE_MS:
        raise VehicleError("range_invalid", f"기록 구간은 {MAX_RANGE_MS // 1000}초까지 올릴 수 있어요")

    te = body.get("t_event")
    if not _is_int(te):
        raise VehicleError("t_event_out_of_range", "t_event는 epoch 밀리초 정수여야 해요")
    if not (lo <= te - MIN_BEFORE_MS and te <= hi):
        raise VehicleError("t_event_out_of_range",
                           f"사고 시각은 기록 구간 안이어야 하고, 앞쪽 기록이 {MIN_BEFORE_MS // 1000}초 이상 있어야 해요")
    src = body.get("t_event_source")
    if src not in EVENT_SOURCES:
        raise VehicleError("request_invalid", "t_event_source는 hard_brake 또는 manual이어야 해요")

    samples = body.get("samples")
    if not isinstance(samples, list):
        raise VehicleError("request_invalid", "samples는 배열이어야 해요")
    if not samples:
        raise VehicleError("samples_empty", "차량 기록이 비어 있어요")
    if len(samples) > MAX_SAMPLES:
        raise VehicleError("samples_too_many", f"차량 기록은 {MAX_SAMPLES:,}개까지 올릴 수 있어요")
    out = []
    for i, s in enumerate(samples):
        s = _check_sample(i, s, lo, hi)
        if out and s["t"] < out[-1]["t"]:
            raise VehicleError("samples_unsorted", f"samples[{i}]: t가 앞 기록보다 이른 시각이에요 (오름차순이어야 해요)")
        out.append(s)

    if body.get("location") is not None:
        raise VehicleError("location_unsupported", "위치 데이터는 아직 받지 않아요 (location은 null)")

    vehicle = body.get("vehicle") or {}
    if not isinstance(vehicle, dict):
        raise VehicleError("request_invalid", "vehicle은 객체여야 해요")
    cls = vehicle.get("cls") or "car"
    if cls not in EGO_CLASSES:
        raise VehicleError("request_invalid", f"vehicle.cls는 {', '.join(EGO_CLASSES)} 중 하나여야 해요")
    client = body.get("client") or {}
    if not isinstance(client, dict):
        raise VehicleError("request_invalid", "client는 객체여야 해요")

    return {"range": {"from": lo, "to": hi}, "t_event": te, "t_event_source": src,
            "samples": out, "vehicle_cls": cls, "client": client}


class Timeline:
    """기록을 "다음 기록까지 유지" 방식으로 읽는다.

    end: 마지막 기록이 유지되는 끝 시각 (보통 range.to). 없으면 마지막 기록 시각.
    """

    def __init__(self, samples, end=None):
        self.rows = list(samples)
        self.ts = [s["t"] for s in self.rows]
        last = self.ts[-1] if self.ts else 0
        self.end = last if end is None else max(end, last)

    def _bounds(self, i):
        s = self.ts[i]
        e = self.ts[i + 1] if i + 1 < len(self.ts) else self.end
        return s, e

    def pieces(self, key, a, b):
        """[a, b)를 덮는 조각 [(s, e, value, kind)]. kind: data / gap(기록 사이 빈 곳) / edge(첫 기록 앞·끝 뒤)
        data가 아닌 조각의 value는 None"""
        out = []
        if a >= b:
            return out
        if not self.ts:
            return [(a, b, None, "edge")]
        if a < self.ts[0]:
            out.append((a, min(b, self.ts[0]), None, "edge"))
        i = max(0, bisect.bisect_right(self.ts, a) - 1)
        while i < len(self.ts):
            s, e = self._bounds(i)
            if s >= b:
                break
            cs, ce = max(s, a), min(e, b)
            if ce > cs:
                if e - s > GAP_MS:
                    out.append((cs, ce, None, "gap" if i + 1 < len(self.ts) else "edge"))
                else:
                    out.append((cs, ce, self.rows[i][key], "data"))
            i += 1
        if b > self.end:
            s = max(a, self.end)
            if out and out[-1][3] == "edge" and out[-1][1] == s:
                out[-1] = (out[-1][0], b, None, "edge")
            else:
                out.append((s, b, None, "edge"))
        return out

    def state(self, key, t):
        """t 이전(포함) 마지막 기록의 값. 기록이 없는 곳이면 None"""
        i = bisect.bisect_right(self.ts, t) - 1
        if i < 0:
            return None
        s, e = self._bounds(i)
        if i + 1 == len(self.ts):
            e = max(e, t)   # 마지막 기록은 end를 조금 넘어도 GAP_MS 안이면 유지된 것으로 봄
        return None if e - s > GAP_MS else self.rows[i][key]

    def gaps(self):
        """두 기록 사이가 GAP_MS보다 벌어진 곳 [{"from", "to"}] (data_quality.gaps)"""
        return [{"from": a, "to": b} for a, b in zip(self.ts, self.ts[1:]) if b - a > GAP_MS]

    def has_gap(self, a, b):
        """[a, b)에 기록 없는 곳이 있는지 (4.1 기록 품질).
        기록 사이 빈 곳은 조금이라도 걸치면, 첫 기록 앞·끝 뒤는 구간 안에서 GAP_MS보다 길면 빈 곳"""
        for s, e, _, kind in self.pieces("t", a, b):
            if kind == "gap" or (kind == "edge" and e - s > GAP_MS):
                return True
        return False

    def duration(self, key, a, b, pred):
        """[a, b)에서 값이 있고 pred(값)이 참인 시간 (ms)"""
        return sum(e - s for s, e, v, kind in self.pieces(key, a, b) if kind == "data" and v is not None and pred(v))

    def known(self, key, a, b):
        """[a, b)에서 값(null 아님)이 있는 시간 (ms)"""
        return self.duration(key, a, b, lambda v: True)

    def mean(self, key, a, b):
        """[a, b)의 시간 가중 평균. 값이 없으면 None"""
        tot = w = 0
        for s, e, v, kind in self.pieces(key, a, b):
            if kind == "data" and v is not None:
                tot += v * (e - s)
                w += e - s
        return tot / w if w else None

    def peak(self, key, a, b, mode=max):
        """[a, b)의 최댓값(mode=max) 또는 최솟값(min)과 그 값이 마지막으로 나온 조각 (value, s, e). 값이 없으면 None"""
        best = None
        for s, e, v, kind in self.pieces(key, a, b):
            if kind == "data" and v is not None and (best is None or mode(v, best[0]) == v):
                best = (v, s, e)
        return best

    def intervals(self, key, a, b, pred):
        """[a, b)에서 pred(값)이 참인 이어진 구간 [(s, e)]"""
        out = []
        for s, e, v, kind in self.pieces(key, a, b):
            if kind == "data" and v is not None and pred(v):
                if out and out[-1][1] == s:
                    out[-1] = (out[-1][0], e)
                else:
                    out.append((s, e))
        return out


def signal_intervals(tl, a, b, max_off=BLINK_MAX_OFF_MS):
    """[a, b)의 지시등 켜짐 [(방향, s, e)], 시각순. 깜빡임 보정(4.1):
    같은 방향 켜짐 사이가 max_off 이하이고 그 사이에 반대 방향 켜짐이 없으면 하나로 이음"""
    raw = sorted((s, e, d) for d in ("LEFT", "RIGHT")
                 for s, e in tl.intervals("turnSignal", a, b, lambda v, d=d: v == d))
    out = []
    for s, e, d in raw:
        if out and out[-1][0] == d and s - out[-1][2] <= max_off:
            out[-1] = (d, out[-1][1], e)
        else:
            out.append((d, s, e))
    return out
