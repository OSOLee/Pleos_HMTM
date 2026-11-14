import os
import json
import math
from itertools import combinations
from statistics import median

# 접촉: 작은 박스 넓이 대비 겹침이 CONTACT_MIN 이상이거나, 두 박스가 TOUCH_GAP 안으로 맞닿음.
# 원래 겹침 0.3만 봤는데, 옆면끼리 부딪힌 차대차 충돌은 박스가 맞닿기만 하고 0.18~0.25만 겹쳐서 놓쳤다
# (cc_211119, 210224, 211217). 평가 17개로 정한 값이라 다른 영상에서 다시 확인할 것
CONTACT_MIN = 0.1
TOUCH_GAP = 0.005
DEPTH_TOL = 0.05
HOLD = 3
SPEED_WIN = 5
REF_WIN = 10
MOVING_SPEED = 0.02
STOP_RATIO = 0.4
STOP_WITHIN = 20
CAND_GAP = 0.1
CAND_N = 3
EARLY_SEC = 1.0    # 영상 시작 이 시간 안의 접촉은 순위를 뒤로 (처음부터 겹쳐 보이던 차)
FRAG_ID = 100000  # track_video.LEFT_ID와 같음. 이 id 이상은 추적기가 버린 탐지를 이어 붙인 조각


def skip_pair(ta, tb):
    """충돌로 보지 않는 쌍: 신호등이 끼었거나, 둘 다 보행자이거나(교통사고 판정에 의미 없음), 둘 다 멈춰 있음"""
    cls = (ta["cls"], tb["cls"])
    return ("traffic_light" in cls or cls == ("pedestrian", "pedestrian")
            or not (ta["moving"] or tb["moving"]))


def has_frag(*tids):
    """조각 궤적이 끼어 있는지. 조각은 잡음(주차 차, 행인의 깜빡이는 탐지)이 섞여 있어서
    추적기가 확정한 궤적끼리의 충돌보다 뒤로 미룬다"""
    return any(int(t) >= FRAG_ID for t in tids)

def run(out_dir="outputs", pair=None, frame=None):
    """pair: 사용자가 고른 두 궤적 id. 주면 자동 검출 결과 대신 이 쌍을 충돌로 쓴다
    frame: 사용자가 정한 충돌 프레임 (당사자를 직접 표시한 프레임). 없으면 검출 결과나 가장 가까운 프레임"""
    in_path = os.path.join(out_dir, "tracks_final.json")
    out_path = os.path.join(out_dir, "collision.json")

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)
    fps = data["fps"]
    tracks = data["tracks"]

    by_tf = {tid: {r["frame"]: r for r in tr["frames"]} for tid, tr in tracks.items()}

    def area(b):
        return b[2] * b[3]

    def inter(a, b):
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
        return max(0, x2 - x1,) * max(0, y2 - y1)

    def contact(a, b):
        m = min(area(a), area(b))
        return inter(a, b) / m if m > 0 else 0.0

    def gap(a, b):
        dx = max(0, max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2]))
        dy = max(0, max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3]))
        return math.hypot(dx, dy)

    def closest(a, b):
        common = sorted(set(by_tf[a]) & set(by_tf[b]))
        if not common:
            raise SystemExit(f"{a}번과 {b}번이 같이 보이는 프레임이 없어요")
        return min(common, key=lambda f: gap(by_tf[a][f]["bbox"], by_tf[b][f]["bbox"]))

    def touching(a, b, f):
        ra, rb = by_tf[a][f], by_tf[b][f]
        hit = contact(ra["bbox"], rb["bbox"]) >= CONTACT_MIN or gap(ra["bbox"], rb["bbox"]) <= TOUCH_GAP
        return hit and abs(ra["pos"][1] - rb["pos"][1]) <= DEPTH_TOL

    def speed(tid, f):
        recs = by_tf[tid]
        if f not in recs or f - SPEED_WIN not in recs:
            return None
        p, q = recs[f]["pos"], recs[f - SPEED_WIN]["pos"]
        return round(math.hypot(p[0] - q[0], p[1] - q[1]) / (SPEED_WIN / fps), 3)

    def approach_speed(tid, f0):
        vals = [s for f in range(f0 - REF_WIN, f0 + 1) if (s := speed(tid, f)) is not None]
        return median(vals) if vals else None

    def find_stop(tid, f0, ref):
        run = 0
        for f in range(f0, f0 + STOP_WITHIN + 1):
            s = speed(tid, f)
            if s is not None and s <= ref * STOP_RATIO:
                run += 1
                if run == HOLD:
                    return f - HOLD + 1
            else:
                run = 0
        return None

    def make_event(a, b, f0, confirmed):
        ref = {t: approach_speed(t, f0) for t in (a, b)}
        stop = {t: (find_stop(t, f0, ref[t]) if ref[t] is not None and ref[t] >= MOVING_SPEED else None)
                for t in (a, b)}
        r0a, r0b = by_tf[a][f0], by_tf[b][f0]
        return {
            "type": "collision",
            "frame": f0,
            "t": round(f0 / fps, 3),
            "a": a, "b": b,
            "cls": {a: tracks[a]["cls"], b: tracks[b]["cls"]},
            "pos": [round((r0a["pos"][0] + r0b["pos"][0]) / 2, 4),
                    round((r0a["pos"][1] + r0b["pos"][1]) / 2, 4)],
            "contact": round(contact(r0a["bbox"], r0b["bbox"]), 3),
            "approach_speed": {t: (round(v, 3) if v is not None else None) for t, v in ref.items()},
            # 둘 다 접촉 전에 움직이고 있었는지. 가짜 충돌은 서 있는 차 앞을 지나가며 박스만 겹친 경우가 많음
            "both_moving": all(v is not None and v >= MOVING_SPEED for v in ref.values()),
            "stop_frame": stop,
            "confirmed": confirmed,
            "interp": bool(r0a.get("interp") or r0b.get("interp")),
        }

    def candidate():
        rows = []
        for a, b in combinations(sorted(tracks, key=int), 2):
            ta, tb = tracks[a], tracks[b]
            if skip_pair(ta, tb):
                continue
            apart, first_close, best = False, None, None
            for f in sorted(set(by_tf[a]) & set(by_tf[b])):
                g = gap(by_tf[a][f]["bbox"], by_tf[b][f]["bbox"])
                if g > CAND_GAP:
                    apart = True
                    continue
                if not apart:
                    continue
                if first_close is None:
                    first_close = f
                if best is None or g < best[0]:
                    best = (g, f)
            if first_close is not None:
                rows.append({"a": a, "b": b, "frame": best[1], "first_close": first_close,
                             "min_gap": round(best[0], 4), "both_moving": ta["moving"] and tb["moving"]})
        rows.sort(key=lambda r: (has_frag(r["a"], r["b"]), not r["both_moving"], r["first_close"], r["min_gap"]))
        return rows[:CAND_N]

    def born_touch():
        """한쪽이 상대와 닿은 채로 처음 나타난 쌍 (충돌 뒤에야 탐지된 당사자)"""
        rows = []
        for a, b in combinations(sorted(tracks, key=int), 2):
            ta, tb = tracks[a], tracks[b]
            if skip_pair(ta, tb):
                continue
            common = sorted(set(by_tf[a]) & set(by_tf[b]))
            if len(common) < HOLD or common[0] not in (ta["frames"][0]["frame"], tb["frames"][0]["frame"]):
                continue
            if not all(touching(a, b, f) for f in common[:HOLD]):
                continue
            e = make_event(a, b, common[0], False)
            if any(e["stop_frame"].values()):
                rows.append({"a": a, "b": b, "frame": common[0], "born": True, "both_moving": e["both_moving"]})
        # 확정 충돌과 같은 순위로 정렬 (질문 보기에는 앞의 몇 개만 들어감, build_facts.BORN_OPTIONS)
        rows.sort(key=lambda r: (not r["both_moving"], has_frag(r["a"], r["b"]), r["frame"]))
        return rows

    events = []
    for a, b in combinations(sorted(tracks, key=int), 2):
        if skip_pair(tracks[a], tracks[b]):
            continue

        common = sorted(set(by_tf[a]) & set(by_tf[b]))
        was_apart = False
        run, run_start = 0, None
        for f in common:
            if not touching(a, b, f):
                was_apart = True
                run = 0
                continue
            if not was_apart:
                continue

            if run == 0:
                run_start = f
            run += 1
            if run < HOLD:
                continue

            f0 = run_start
            ref = {t: approach_speed(t, f0) for t in (a, b)}
            stop = {t: (find_stop(t, f0, ref[t]) if ref[t] is not None and ref[t] >= MOVING_SPEED else None)
                    for t in (a, b)}
            if not any(stop.values()):
                print(f"후보 기각: {a} <-> {b} 프레임 {f0} (정지 없음)")
                run = 0
                continue
            
            events.append(make_event(a, b, f0, True))
            break

    # 순위: 영상 첫 EARLY_SEC 안의 접촉은 뒤로 → 둘 다 접촉 전에 움직인 충돌 → 확정 궤적끼리의 충돌 → 시간순.
    # 맨 앞이 자동으로 고르는 충돌이고, 앞의 몇 개가 "부딪힌 두 객체" 질문의 보기가 된다 (build_facts.PAIR_OPTIONS).
    # 사고 영상은 다가오는 장면부터 잘려 있어서 첫 1초 안의 "접촉"은 처음부터 화면에서 겹쳐 보이던 차인 경우가 많음
    # (평가 24개: cc_180420 11프레임, 211119 9프레임, 180629 14프레임이 진짜 충돌을 밀어냄 → 맞게 고른 영상 9 → 12, 잃은 것 없음)
    events.sort(key=lambda e: (e["frame"] < EARLY_SEC * fps, not e["both_moving"], has_frag(e["a"], e["b"]), e["frame"]))
    born = born_touch()
    cands = []
    if not events:
        cands = candidate()
        if cands:
            c = cands[0]
            events.append(make_event(c["a"], c["b"], c["frame"], False))
            print(f"충돌을 찾지 못해 후보 {c['a']} <-> {c['b']} (프레임 {c['frame']})를 임시로 씀. 사용자 확인 필요")

    auto = None
    if pair:
        a, b = sorted((str(t) for t in pair), key=int)
        if a not in tracks or b not in tracks:
            raise SystemExit(f"고른 궤적이 없어요: {a}, {b}")
        known = [k for k in events + cands + born if {k["a"], k["b"]} == {a, b}]
        if frame is not None and frame in by_tf[a] and frame in by_tf[b]:
            f0 = frame
        else:
            f0 = known[0]["frame"] if known else closest(a, b)
        auto = [{"a": e["a"], "b": e["b"], "frame": e["frame"]} for e in events]
        events = [make_event(a, b, f0, True)]
        events[0]["source"] = "user"
        print(f"사용자가 고른 쌍 {a} <-> {b}를 충돌로 씀 (프레임 {f0})")
    print("=== 충돌 ===")
    if not events:
        print("검출된 충돌 없음")
    for e in events:
        a, b = e["a"], e["b"]
        print(f"접촉 시작 프레임 {e['frame']} ({e['t']}초) | {a}({e['cls'][a]}) <-> {b}({e['cls'][b]}) "
            f"| 접촉 {e['contact']} | 위치 {e['pos']}")
        print(f"   접근 속도 {e['approach_speed']} | 정지 프레임 {e['stop_frame']}")
    for k in born:
        print(f"닿은 채 나타난 쌍: {k['a']} <-> {k['b']} (프레임 {k['frame']}, 질문 보기에만 추가)")

    out = {
        "schema_version": "0.2",
        "source": data["source"],
        "video": data["video"],
        "params": {"contact_min": CONTACT_MIN, "touch_gap": TOUCH_GAP, "depth_tol": DEPTH_TOL, "hold": HOLD,
                "speed_win": SPEED_WIN, "ref_win": REF_WIN, "moving_speed": MOVING_SPEED,
                "stop_ratio": STOP_RATIO, "stop_within": STOP_WITHIN,
                "cand_gap": CAND_GAP, "cand_n": CAND_N},
        "events": events,
        "candidates": cands,
        "born_candidates": born,
        "auto_events": auto,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")

if __name__ == "__main__":
    run()