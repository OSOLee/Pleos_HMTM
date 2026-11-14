"""영상 시각 ↔ 차량 기록 시각 (docs/design-blackbox.md 5절)

거친 시작 시각 S0(파일 이름 등)을 고르고, 내 차 움직임(ego_motion.speed_proxy)과 차량 속도를 비교해 시차 offset을 찾는다.
영상 t초 = S0 + offset + t×1000 (차량 ms).

  start_candidates(filename, meta, video_path)  촬영 시작 시각 후보 [{source, start_ms}]
  pick_start(candidates)                        믿을 순서대로 하나: filename > metadata > app > mtime
  vehicle_window(start_ms, duration_s)          차량 기록 구간 [S0 − 15초, S0 + 길이 + 15초], 최대 300초 (Q12)
  sync(...)                                     {"start_ms", "start_source", "offset_ms", "grade", ...}

등급 (5.3)
  fine    속도 모양 상관 ≥ 0.7이고 충격 기준점(차량 급감속 최대)과 0.5초 안에서 맞음 → 차량 규칙 전부 씀 (offset 보정)
  coarse  시작 시각이 파일 이름·메타데이터·앱 값이고 차량 기록이 충돌 시각 T를 덮음 → 시각에 덜 민감한 규칙만 씀
  none    시작 시각이 없거나 수정 시각뿐(복사하면 바뀜), 또는 차량 기록이 T를 못 덮음 → 차량 규칙을 쓰지 않음.
          영상의 사고 순간이 불확실하면(collision_uncertain=True, analyzer.collision_review) 차량 기록이 있어도 none
          (reason collision_uncertain, t_collision_ms null: 타이밍에 기대는 차량 값을 쓰지 않음)

none의 reason과 한 문장(reason_text)을 남긴다. 차량 기록을 올렸는데 영상 구간과 하나도 겹치지 않으면 vehicle_clock_mismatch
(전에는 no_vehicle_record로 보였음), 겹치지만 충돌 앞 3초를 못 덮으면 vehicle_record_not_covering. 둘 다 vehicle_gap에 얼마나
어긋났는지를 남긴다. 촬영 시작 시각·차량 기록 시각이 서버 시각과 하루 넘게 다르면 clock_warnings (src/vehicle/clock.py, 명세 6.1).

시각은 epoch ms. 파일 이름 시각은 시간대 표시가 없어 기본 한국 시각(UTC+9)으로 본다.
mp4 메타데이터(mvhd creation_time)는 UTC로 본다. 파일 이름·메타데이터 시각을 녹화 시작으로 본다 (확인 필요, 5.2).
"""
import datetime as dt
import os
import re
import struct

import numpy as np

from src.vehicle import clock

MARGIN_MS = 15_000            # 영상 앞뒤 여유 (5.5)
MTIME_MARGIN_MS = 60_000      # 시작 시각이 수정 시각뿐일 때 여유 (앱 notes 5절과 같음)
MAX_WINDOW_MS = 300_000       # 블랙박스 사건 차량 기록 구간 최대 (확정 Q12)
MIN_BEFORE_MS = 3_000         # T 앞에 차량 기록이 이만큼 있어야 coarse (rules의 3초 구간)
DEFAULT_TZ_MIN = 9 * 60       # 파일 이름 시각의 시간대 (Asia/Seoul, 서머타임 없음)
SOURCE_ORDER = ("user", "filename", "metadata", "app", "mtime")
COARSE_SOURCES = ("user", "filename", "metadata", "app")
MIN_YEAR, MAX_YEAR = 2000, 2100
MP4_EPOCH = dt.datetime(1904, 1, 1, tzinfo=dt.timezone.utc)
NAME_TIME = re.compile(r"(?<!\d)(20\d\d)[-_.]?(\d\d)[-_.]?(\d\d)[-_T ]?(\d\d)[-_:.]?(\d\d)[-_:.]?(\d\d)(?!\d)")
# 정밀 맞추기 (5.3). 기준값은 임시값(확정 Q11): 실차 영상으로 조정한다
FINE_CORR = 0.7               # 속도 모양 상관이 이 이상이고
IMPACT_TOL_MS = 500           # 충격 기준점(차량 급감속 최대)과 이 안에서 맞으면 fine
SEARCH_MS = 15_000            # offset 찾는 범위 ±L
MTIME_SEARCH_MS = 60_000      # 시작 시각이 수정 시각뿐이면 ±60초
GRID_MS = 100                 # 비교 간격 (차량 기록 100ms)
MAX_GAP_MS = 500              # 차량 기록이 이보다 멀면 그 점은 비교하지 않음
MIN_OVERLAP_S = 5.0           # 겹치는 길이가 이만큼(또는 영상의 MIN_OVERLAP_FRAC) 안 되면 그 offset은 버림
MIN_OVERLAP_FRAC = 0.5
DECEL_WINDOW_MS = 300         # 급감속 기울기 구간
IMPACT_DECEL = 10.0           # km/h/s. 이보다 완만하면 충격 기준점 없음
PEAK_SEP_MS = 1_000           # offset 후보끼리 떨어진 거리
FINE_METHOD = "speed_xcorr+impact"
PARAMS = {"margin_ms": MARGIN_MS, "max_window_ms": MAX_WINDOW_MS, "min_before_ms": MIN_BEFORE_MS,
          "default_tz_min": DEFAULT_TZ_MIN, "method": "coarse_start_v0",
          "fine_corr": FINE_CORR, "impact_tol_ms": IMPACT_TOL_MS, "search_ms": SEARCH_MS,
          "mtime_search_ms": MTIME_SEARCH_MS, "grid_ms": GRID_MS, "impact_decel_kmh_s": IMPACT_DECEL}


def _ms(d):
    return int(d.timestamp() * 1000)


def from_filename(name, tz_min=DEFAULT_TZ_MIN):
    """파일 이름의 YYYYMMDD_HHMMSS 꼴 시각 → epoch ms. 없거나 날짜가 틀리면 None"""
    m = NAME_TIME.search(os.path.basename(name or ""))
    if not m:
        return None
    try:
        d = dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone(dt.timedelta(minutes=tz_min)))
    except ValueError:
        return None
    return _ms(d)


def _boxes(f, end):
    while f.tell() + 8 <= end:
        start = f.tell()
        size, kind = struct.unpack(">I4s", f.read(8))
        head = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            head = 16
        elif size == 0:
            size = end - start
        if size < head:
            return
        yield kind, start + head, start + size
        f.seek(start + size)


def mp4_creation_ms(path):
    """mp4 moov/mvhd의 creation_time(1904년부터 초, UTC) → epoch ms. 없거나 0·이상한 값이면 None"""
    try:
        with open(path, "rb") as f:
            end = os.fstat(f.fileno()).st_size
            for kind, a, b in _boxes(f, end):
                if kind != b"moov":
                    continue
                f.seek(a)
                for k2, a2, _ in _boxes(f, b):
                    if k2 != b"mvhd":
                        continue
                    f.seek(a2)
                    ver = f.read(1)[0]
                    f.read(3)
                    secs = struct.unpack(">Q", f.read(8))[0] if ver == 1 else struct.unpack(">I", f.read(4))[0]
                    if secs == 0:
                        return None
                    d = MP4_EPOCH + dt.timedelta(seconds=secs)
                    return _ms(d) if MIN_YEAR <= d.year < MAX_YEAR else None
    except (OSError, struct.error, IndexError, OverflowError):
        return None
    return None


def _is_ms(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def start_candidates(filename=None, meta=None, video_path=None, duration_s=None):
    """촬영 시작 시각 후보. meta(앱이 보낸 것): {"recorded_at": [{source, start_ms}], "mtime_ms", "tz_offset_min"}.
    수정 시각(mtime_ms)은 녹화 끝으로 보고 길이를 뺀다"""
    meta = meta or {}
    tz = meta.get("tz_offset_min")
    tz = tz if isinstance(tz, int) and not isinstance(tz, bool) and -720 <= tz <= 840 else DEFAULT_TZ_MIN
    out = []
    t = from_filename(filename, tz)
    if t:
        out.append({"source": "filename", "start_ms": t})
    if video_path:
        t = mp4_creation_ms(video_path)
        if t:
            out.append({"source": "metadata", "start_ms": t})
    for c in meta.get("recorded_at") or []:
        if isinstance(c, dict) and _is_ms(c.get("start_ms")):
            src = c.get("source")
            src = src if src in ("filename", "metadata", "user") else "app"
            if not any(o["source"] == src for o in out):   # 서버가 읽은 값이 있으면 그 값을 씀
                out.append({"source": src, "start_ms": c["start_ms"]})
    mt = meta.get("mtime_ms")
    if _is_ms(mt) and duration_s:
        out.append({"source": "mtime", "start_ms": int(mt - duration_s * 1000)})
    return sorted(out, key=lambda c: SOURCE_ORDER.index(c["source"]))


def pick_start(candidates):
    return candidates[0] if candidates else None


def vehicle_window(start_ms, duration_s, margin_ms=MARGIN_MS):
    """차량 기록 구간 [S0 − 여유, S0 + 길이 + 여유]. 길이가 최대(300초)를 넘으면 끝을 줄인다 (앞쪽 여유는 지킴)"""
    lo = start_ms - margin_ms
    hi = start_ms + int(round((duration_s or 0) * 1000)) + margin_ms
    return {"from": lo, "to": min(hi, lo + MAX_WINDOW_MS)}


def margin_for(start_source):
    """차량 기록 여유: 시작 시각이 수정 시각뿐이면 넓게 (5.5 "M을 늘림", 5.3의 ±60초)"""
    return MTIME_MARGIN_MS if start_source == "mtime" else MARGIN_MS


REASON_TEXT = {
    "no_start_time": "영상 촬영 시각을 몰라 차량 기록과 맞추지 못했어요",
    "no_vehicle_record": "차량 기록이 없어요",
    "no_collision_time": "영상에서 부딪힌 순간을 찾지 못해 차량 기록과 맞추지 못했어요",
    "collision_uncertain": "영상의 부딪힌 순간이 확실하지 않아 차량 기록과 맞추지 않았어요",
    "start_time_unreliable": "영상 촬영 시각이 파일 수정 시각뿐이라 차량 기록과 맞추지 않았어요",
    "vehicle_record_not_covering": "차량 기록이 부딪힌 순간 앞뒤를 덮지 않아요",
    "vehicle_clock_mismatch": "차량 기록 시각과 영상 촬영 시각이 크게 어긋나 차량 기록을 쓰지 않았어요",
}


def _gap_text(gap_ms):
    s = abs(gap_ms) / 1000
    amount = f"{s / 3600:.1f}시간" if s >= 3600 else f"{s / 60:.0f}분" if s >= 60 else f"{s:.0f}초"
    return f"차량 기록이 영상보다 {amount} {'뒤예요' if gap_ms > 0 else '앞이에요'}"


def vehicle_gap(need, uploaded):
    """차량 기록 구간(uploaded)이 필요한 구간(need)에서 얼마나 떨어졌는지. gap_ms: 기록이 앞이면 음수, 뒤면 양수, 겹치면 0"""
    if uploaded["to"] < need["from"]:
        gap = uploaded["to"] - need["from"]
    elif uploaded["from"] > need["to"]:
        gap = uploaded["from"] - need["to"]
    else:
        gap = 0
    return {"need": need, "vehicle_range": {"from": uploaded["from"], "to": uploaded["to"]}, "gap_ms": gap}


def _covers(vehicle_range, t_ms):
    return vehicle_range["from"] <= t_ms - MIN_BEFORE_MS and t_ms <= vehicle_range["to"]


# ---------- 정밀 맞추기 (5.3) ----------

def _speed_series(samples):
    pts = [(s["t"], s["speedKmh"]) for s in samples or [] if s.get("speedKmh") is not None]
    if len(pts) < 2:
        return None, None
    t, v = zip(*pts)
    return np.asarray(t, dtype=float), np.asarray(v, dtype=float)


def _at(vt, vv, q):
    """차량 속도를 시각 q(ms 배열)에서 읽음. 가장 가까운 기록이 MAX_GAP_MS보다 멀면 쓰지 않음"""
    i = np.clip(np.searchsorted(vt, q), 1, len(vt) - 1)
    gap = np.minimum(np.abs(q - vt[i - 1]), np.abs(vt[i] - q))
    ok = (q >= vt[0]) & (q <= vt[-1]) & (gap <= MAX_GAP_MS)
    return np.interp(q, vt, vv), ok


def _video_series(ego_motion, duration_s):
    """영상 speed_proxy를 GRID_MS 간격으로. 모양이 틀렸거나 짧으면 None"""
    em = ego_motion or {}
    t, sp = em.get("t") or [], em.get("speed_proxy") or []
    if len(t) < 2 or len(t) != len(sp):
        return None, None
    t, sp = np.asarray(t, dtype=float), np.asarray(sp, dtype=float)
    end = min(t[-1], duration_s) if duration_s else t[-1]
    grid = np.arange(max(t[0], 0.0), end + 1e-9, GRID_MS / 1000)
    if len(grid) * GRID_MS / 1000 < MIN_OVERLAP_S:
        return None, None
    return grid, np.interp(grid, t, sp)


def _corr(a, b):
    if a.std() < 1e-6 or b.std() < 1e-6:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def speed_xcorr(start_ms, grid, vs, vt, vv, search_ms):
    """offset을 −L~+L에서 GRID_MS씩 옮기며 상관 (둘 다 표준화하는 것과 같음). [(offset_ms, 상관)]"""
    need = max(MIN_OVERLAP_S, MIN_OVERLAP_FRAC * len(grid) * GRID_MS / 1000) / (GRID_MS / 1000)
    out = []
    for off in range(-search_ms, search_ms + 1, GRID_MS):
        vals, ok = _at(vt, vv, start_ms + off + grid * 1000)
        if ok.sum() < need:
            continue
        r = _corr(vs[ok], vals[ok])
        if r is not None:
            out.append((off, r))
    return out


def _peaks(scores, n=3):
    """상관이 큰 offset 후보 (서로 1초 넘게 떨어진 것) n개"""
    out = []
    for off, r in sorted(scores, key=lambda x: -x[1]):
        if all(abs(off - o["offset_ms"]) > PEAK_SEP_MS for o in out):
            out.append({"offset_ms": off, "score": round(r, 3)})
        if len(out) == n:
            break
    return out


def impact_time(vt, vv, around_ms, search_ms):
    """차량 급감속 최대 시각 (속도 기울기 최소). around_ms ± search_ms 안. 기울기가 IMPACT_DECEL보다 완만하면 None"""
    grid = np.arange(max(vt[0], around_ms - search_ms), min(vt[-1], around_ms + search_ms) + 1, GRID_MS, dtype=float)
    if len(grid) < 3:
        return None
    h = DECEL_WINDOW_MS / 2
    a, oka = _at(vt, vv, grid - h)
    b, okb = _at(vt, vv, grid + h)
    slope = np.where(oka & okb, (b - a) / (DECEL_WINDOW_MS / 1000), np.inf)   # km/h per s
    i = int(np.argmin(slope))
    if not np.isfinite(slope[i]) or slope[i] > -IMPACT_DECEL:
        return None
    return {"t_ms": int(grid[i]), "decel_kmh_s": round(float(-slope[i]), 1)}


def fine_match(start_ms, start_source, collision_t, samples, ego_motion, duration_s):
    """속도 모양 상관 + 충격 기준점. 반환 {"ok", "reason", "offset_ms", "score", "offset_candidates", "impact"}"""
    out = {"ok": False, "reason": None, "offset_ms": None, "score": None, "offset_candidates": [], "impact": None}
    vt, vv = _speed_series(samples)
    grid, vs = _video_series(ego_motion, duration_s)
    if vt is None:
        out["reason"] = "no_vehicle_speed"
        return out
    if grid is None:
        out["reason"] = "no_ego_motion"
        return out
    search = MTIME_SEARCH_MS if start_source == "mtime" else SEARCH_MS
    scores = speed_xcorr(start_ms, grid, vs, vt, vv, search)
    if not scores:
        out["reason"] = "no_speed_variation"           # 영상이나 차량이 내내 서 있음, 또는 기록이 겹치지 않음
        return out
    out["offset_candidates"] = _peaks(scores)
    best = out["offset_candidates"][0]
    out["offset_ms"], out["score"] = best["offset_ms"], best["score"]
    t_video = start_ms + int(round(collision_t * 1000))  # offset 0에서의 충돌 시각
    imp = impact_time(vt, vv, t_video, search)
    if imp is not None:
        imp["offset_ms"] = imp["t_ms"] - t_video
        imp["matched"] = abs(imp["offset_ms"] - best["offset_ms"]) <= IMPACT_TOL_MS
    out["impact"] = imp
    if best["score"] < FINE_CORR:
        out["reason"] = "low_correlation"
    elif imp is None:
        out["reason"] = "no_impact"
    elif not imp["matched"]:
        out["reason"] = "impact_mismatch"
    else:
        out["ok"] = True
    return out


def sync(candidates, collision_t, vehicle_range=None, samples=None, ego_motion=None, duration_s=None,
         uploaded_range=None, server_ms=None, collision_uncertain=False):
    """시각 맞추기. collision_t: 영상 충돌 시각(초) 또는 None. vehicle_range: 영상 구간으로 자른 차량 기록 {from, to} 또는 None.
    samples·ego_motion이 있으면 먼저 정밀 맞추기(fine)를 해 보고, 안 되면 거친 시작 시각(coarse/none, offset 0).
    uploaded_range: 자르기 전 올린 차량 기록 구간 (어긋난 정도·시계 경고용), server_ms: 서버가 받은 시각 (시계 경고용)
    collision_uncertain: 영상의 사고 순간이 불확실 (analyzer.collision_review) → 차량 기록이 있어도 none / collision_uncertain"""
    if collision_uncertain and collision_t is not None:
        out = _sync(candidates, None, None, None, None, duration_s, None)
        if out["reason"] != "no_start_time" and (vehicle_range or uploaded_range):   # 기록이 없으면 no_vehicle_record 그대로
            out["reason"] = "collision_uncertain"
    else:
        out = _sync(candidates, collision_t, vehicle_range, samples, ego_motion, duration_s, uploaded_range)
    if out["grade"] == "none" and uploaded_range and out["reason"] in ("vehicle_record_not_covering",
                                                                       "vehicle_clock_mismatch"):
        if out["t_collision_ms"] is not None:
            need = {"from": out["t_collision_ms"] - MIN_BEFORE_MS, "to": out["t_collision_ms"]}
        else:
            need = {"from": out["start_ms"], "to": out["start_ms"] + int(round((duration_s or 0) * 1000))}
        out["vehicle_gap"] = vehicle_gap(need, uploaded_range)
    out["reason_text"] = REASON_TEXT.get(out["reason"]) if out["grade"] == "none" else None
    if out.get("vehicle_gap") and out["vehicle_gap"]["gap_ms"]:
        out["reason_text"] += f" ({_gap_text(out['vehicle_gap']['gap_ms'])})"
    out["clock_warnings"] = clock.warnings(server_ms, out["start_ms"], out["start_source"], uploaded_range)
    return out


def _sync(candidates, collision_t, vehicle_range, samples, ego_motion, duration_s, uploaded_range):
    best = pick_start(candidates)
    out = {"start_ms": best["start_ms"] if best else None, "start_source": best["source"] if best else None,
           "offset_ms": 0, "method": PARAMS["method"], "score": None, "grade": "none", "reason": None,
           "t_collision_ms": None, "candidates": candidates, "params": PARAMS, "fine": None, "vehicle_gap": None}
    if best is None:
        out["reason"] = "no_start_time"
        return out
    if collision_t is not None:
        out["t_collision_ms"] = best["start_ms"] + int(round(collision_t * 1000))
    if vehicle_range is None:
        out["reason"] = "vehicle_clock_mismatch" if uploaded_range else "no_vehicle_record"   # 올렸지만 영상 구간 밖
        return out
    if out["t_collision_ms"] is None:
        out["reason"] = "no_collision_time"
        return out

    fine = fine_match(best["start_ms"], best["source"], collision_t, samples, ego_motion, duration_s)
    out["fine"] = {k: v for k, v in fine.items() if k != "ok"}
    out["score"] = fine["score"]
    if fine["ok"]:
        t = out["t_collision_ms"] + fine["offset_ms"]
        if _covers(vehicle_range, t):
            out.update(offset_ms=fine["offset_ms"], method=FINE_METHOD, grade="fine", t_collision_ms=t)
            return out
        out["fine"]["reason"] = "vehicle_record_not_covering"

    if best["source"] not in COARSE_SOURCES:
        out["reason"] = "start_time_unreliable"      # 수정 시각뿐: 복사하면 바뀌어 수 분 틀릴 수 있음
    elif not _covers(vehicle_range, out["t_collision_ms"]):
        out["reason"] = "vehicle_record_not_covering"
    else:
        out["grade"] = "coarse"
    return out
