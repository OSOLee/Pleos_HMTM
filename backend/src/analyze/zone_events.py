import os
import sys
import json
import math
import cv2
import numpy as np

MIN_SEG = 3         # 이보다 짧은 영역 구간은 경계 근처 흔들림으로 보고 앞 구간에 흡수
SPEED_WIN = 5       # 진입 속도를 잴 프레임 수 (detect_colleision과 같은 값) 
STOP_SPEED = 0.01   # 이보다 느리면 멈춘 것으로 봄
STOP_HOLD = 5       # 이 프레임 수 이상 연속으로 느려야 일시정지
# 멈춘 곳이 교차로 진입점에서 박스 높이의 이 배수 안이어야 "진입 전 정지". 멀리 서 있다 출발한 차는 빼려고
# (cc_200711: 주차장 안쪽 4.3배 거리에 서 있던 차가 서행 −10을 받았음. 실제 일시정지 3건은 1.0배 이하)
STOP_NEAR = 2.0
ENTRY_MARGIN = 0.02 # 교차로 경계를 이만큼 넓히고 좁혀 진입 시점을 다시 잼 (모서리를 누를 때의 오차)

def poly(pts):
    return np.array(pts, np.float32)

def inside(pt, p):
    return cv2.pointPolygonTest(p, (float(pt[0]), float(pt[1])), False) >= 0

def zone_of(pt, zones, roi):
    if not inside(pt, roi):
        return "out_of_roi"
    for zid, p in zones:
        if inside(pt, p):
            return zid
    return "unknown"

def segments(frames, zones, roi):
    raw = []
    for r in frames:
        z = zone_of(r["pos"], zones, roi)
        if raw and raw[-1]["zone"] == z:
            raw[-1]["end"] = r["frame"]
        else:
            raw.append({"zone": z, "start": r["frame"], "end": r["frame"]})

    cleaned = []
    for s in raw:
        length = s["end"] - s["start"] + 1
        if cleaned and (length < MIN_SEG or cleaned[-1]["zone"] == s["zone"]):
            cleaned[-1]["end"] = s["end"]
        else:
            cleaned.append(dict(s))
    return cleaned

def speed_at(frames, f, fps):
    by_f = {r["frame"]: r for r in frames}
    f0 = max(f - SPEED_WIN, frames[0]["frame"])
    if f0 == f:
        return None
    p, q = by_f[f0]["pos"], by_f[f]["pos"]
    return round(math.hypot(q[0] - p[0], q[1] - p[1]) / ((f - f0) / fps), 3)

def stopped_in(frames, f1, f2, fps):
    """f1~f2(진입 프레임) 사이에, 진입점 가까이에서 STOP_HOLD 프레임 이상 멈춘 적이 있는지.
    구간이 짧아 판단할 수 없으면 None"""
    if f2 - f1 < SPEED_WIN + STOP_HOLD:
        return None
    by_f = {r["frame"]: r for r in frames}
    entry = by_f[f2]["pos"]
    run = 0
    for f in range(f1 + SPEED_WIN, f2 + 1):
        s = speed_at(frames, f, fps)
        run = run + 1 if s is not None and s < STOP_SPEED else 0
        if run >= STOP_HOLD:
            r = by_f[f]
            if math.hypot(r["pos"][0] - entry[0], r["pos"][1] - entry[1]) <= STOP_NEAR * r["bbox"][3]:
                return True
    return False

def robust_stop(frames, f1, entries, fps):
    """진입 전 멈춤을 경계를 넓히고 좁힌 진입 프레임(ENTRY_MARGIN)으로도 재서, 결과가 갈리면 None (모름).
    멈춘 곳이 진입점 근처인지로 보기 때문에 모서리가 조금만 달라도 바뀐다 → B의 서행(slowed_down) 감산이
    질문 없이 붙었다 빠졌다 함 (모서리 민감도 실험: cc_180304 손떨림 4%, cc_200711)"""
    res = {stopped_in(frames, f1, f, fps) for f in entries if f is not None and f > f1}
    return res.pop() if len(res) == 1 else None


def offset_poly(pts, d):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    out = []
    for x, y in pts:
        n = math.hypot(x - cx, y - cy)
        out.append([x + d * (x - cx) / n, y + d * (y - cy) / n])
    return out

def first_entry(frames, p):
    was_out = False
    for r in frames:
        if inside(r["pos"], p):
            if was_out:
                return r["frame"]
        else:
            was_out = True
    return None

def intersection_entry(segs, frames, zone_types, zone_dirs, alt, fps):
    for i, (prev, cur) in enumerate(zip(segs, segs[1:])):
        if zone_types.get(cur["zone"]) != "intersection":
            continue
        if prev["zone"] in ("out_of_roi", "unknown"):
            return "unknown"

        f = cur["start"]
        nxt = segs[i + 2] if i + 2 < len(segs) else None
        exit_to = nxt["zone"] if nxt and zone_types.get(nxt["zone"]) == "approach" else None
        f_out = first_entry(frames, alt[0]) if alt else None
        f_in = first_entry(frames, alt[1]) if alt else None
        return {"frame": f, "t": round(f / fps, 3), "from": prev["zone"],
                "from_direction": zone_dirs.get(prev["zone"]),
                "exit_to": exit_to, "exit_direction": zone_dirs.get(exit_to),
                "exit_frame": nxt["start"] if exit_to else None,
                "frame_outer": f_out, "frame_inner": f_in,
                "speed": speed_at(frames, f, fps),
                "stopped_before": robust_stop(frames, prev["start"], (f, f_out, f_in), fps)}
    if any(zone_types.get(s["zone"]) == "intersection" for s in segs):
        return "unknown"
    return None

def run(scene_path, out_dir="outputs"):
    tracks_path = os.path.join(out_dir, "tracks_final.json")
    coll_path = os.path.join(out_dir, "collision.json")
    out_path = os.path.join(out_dir, "zones.json")

    with open(tracks_path, encoding="utf-8") as f:
        data = json.load(f)
    with open(scene_path, encoding="utf-8") as f:
        scene = json.load(f)
    with open(coll_path, encoding="utf-8") as f:
        coll = json.load(f)
    fps = data["fps"]
    
    tracks = data["tracks"]
    zones = [(z["id"], poly(z["polygon"])) for z in scene["zones"]]
    zone_types = {z["id"]: z["type"] for z in scene["zones"]}
    zone_dirs = {z["id"]: z.get("direction") for z in scene["zones"]}
    inter = next((z for z in scene["zones"] if z["type"] == "intersection"), None)
    alt = ((poly(offset_poly(inter["polygon"], ENTRY_MARGIN)),
            poly(offset_poly(inter["polygon"], - ENTRY_MARGIN))) if inter else None)
    roi = poly(scene["roi"])

    parties = {t for e in coll["events"] for t in (e["a"], e["b"])}

    timelines, events, entries = {}, [], {}
    for tid, tr in tracks.items():
        if not tr["moving"] and tid not in parties: # 정지 물체도 당사자면 기록함
            continue
        segs = segments(tr["frames"], zones, roi)
        timelines[tid] = {"cls": tr["cls"], "segments": segs}
        entries[tid] = intersection_entry(segs, tr["frames"], zone_types, zone_dirs, alt, fps)
        for prev, cur in zip(segs, segs[1:]):
            events.append({
                    "type": "enter_zone",
                    "track": tid,
                    "from": prev["zone"],
                    "zone": cur["zone"],
                    "zone_type": zone_types.get(cur["zone"]),
                    "frame": cur["start"],
                    "t": round(cur["start"] / fps, 3),
            })

    collisions = []
    for e in coll["events"]:
        f0 = e["frame"]
        parties = {}
        for t in (e["a"], e["b"]):
            rec = next((r for r in tracks[t]["frames"] if r["frame"] == f0), None)
            parties[t] = zone_of(rec["pos"], zones, roi) if rec else "unknown"
        collisions.append({
                "frame": f0,
                "a": e["a"],
                "b": e["b"],
                "zone": zone_of(e["pos"], zones, roi),
                "party_zones": parties,
        })

    print("=== 영역 타임라인 ===")
    for tid, tl in timelines.items():
        path = " → ".join(
            f"{s['zone']}({s['start']}~{s['end']})" for s in tl["segments"]
        )
        print(f"ID {tid:>3} {tl['cls']:<12} | {path}")
    print("\n=== 영역 이동 이벤트 ===")
    for ev in events:
        print(
            f"프레임 {ev['frame']:>3} | ID {ev['track']} : {ev['from']} → {ev['zone']}"
        )
    print("\n=== 교차로 진입 ===")
    for tid, en in entries.items():
        if en is not None:
            print(f"ID {tid:>3} : {en}")
    print("\n=== 충돌 지점 ===")
    for c in collisions:
        print(
            f"프레임 {c['frame']} | {c['a']} ↔ {c['b']} | 충돌 위치 {c['zone']} | 당사자 위치 {c['party_zones']}"
        )

    out = {
        "schema_version": "0.2",
        "video": data["video"],
        "scene": scene_path,
        "road_type": scene.get("road_type", "unknown"),
        "params": {"min_seg": MIN_SEG, "speed_win": SPEED_WIN,
                   "stop_speed": STOP_SPEED, "stop_hold": STOP_HOLD, "stop_near": STOP_NEAR,
                   "entry_margin": ENTRY_MARGIN},
        "zone_types": zone_types,
        "timelines": timelines,
        "events": events,
        "intersection_entries": entries,
        "collisions": collisions,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")
    return out_path


if __name__ == "__main__":
    scene_path = sys.argv[1] if len(sys.argv) > 1 else "scenes/sample.json"
    run(scene_path)
