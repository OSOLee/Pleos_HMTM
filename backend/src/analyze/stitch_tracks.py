import os
import json
import math
from collections import Counter

MAX_GAP = 20      # 이어붙일 수 있는 최대 공백 (프레임)
MAX_DIST = 0.2    # 앞 조각 끝 ~ 뒤 조각 시작 최대 거리 (정규화 좌표)

STATIC_SPEED = 0.002  # 프레임당 이동량이 이보다 작으면 정지 조각
STATIC_DIST = 0.05    # 정지 조각 뒤에 이어붙일 수 있는 최대 거리

HEAD_WIN = 10     # 진행 방향을 잴 때 쓰는 조각 끝/시작 프레임 수
HEAD_MOVE = 0.03  # 그 구간에서 이만큼 이상 움직여야 방향을 믿음
HEAD_MAX = 100    # 앞 조각 끝과 뒤 조각 시작의 방향 차이가 이보다 크면 다른 차

FRAG_ID = 100000  # track_video.LEFT_ID와 같음. 이 id 이상은 추적기가 버린 탐지를 이어 붙인 조각

def dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])

def is_static(recs):
    x0, y0 = recs[0]["pos"]
    move = max(math.hypot(r["pos"][0] - x0, r["pos"][1] - y0) for r in recs)
    span = recs[-1]["frame"] - recs[0]["frame"]
    return span == 0 or move / span < STATIC_SPEED

def is_light(recs):
    return Counter(r["cls"] for r in recs).most_common(1)[0][0] == "traffic light"

def heading(recs):
    (x0, y0), (x1, y1) = recs[0]["pos"], recs[-1]["pos"]
    if math.hypot(x1 - x0, y1 - y0) < HEAD_MOVE:
        return None
    return math.degrees(math.atan2(y1 - y0, x1 - x0))

def turn(a, b):
    return abs((a - b + 180) % 360 - 180)

def run(out_dir="outputs"):
    in_path = os.path.join(out_dir, "tracks.json")
    out_path = os.path.join(out_dir, "tracks_stitched.json")

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)
    tracks = data["tracks"]
    order = sorted(tracks, key=lambda tid: tracks[tid][0]["frame"])

    merged = {}    # 대표 ID -> 이어붙인 기록 목록
    members = {}   # 대표 ID -> 합쳐진 원래 ID 목록

    for tid in order:
        recs = tracks[tid]
        start = recs[0]
        if int(tid) >= FRAG_ID:
            # 버린 탐지를 이은 조각은 추적기 궤적과 잇지 않는다. 이으면 멈춘 차 궤적에 잡음이 붙어
            # "움직이는 궤적"이 되고 가짜 충돌이 크게 늘었다 (cc_200511: 주차 차끼리 확정 충돌 6개)
            merged[tid] = list(recs)
            members[tid] = [tid]
            continue
        light = is_light(recs)
        h_new = heading(recs[:HEAD_WIN])

        best, best_d, best_gap = None, None, None
        for root, mrecs in merged.items():
            if int(root) >= FRAG_ID:
                continue
            end = mrecs[-1]
            gap = start["frame"] - end["frame"]
            if gap <= 0 or gap > MAX_GAP:
                continue
            if is_light(mrecs) != light:
                continue
            d = dist(end["pos"], start["pos"])
            static = is_static(mrecs)
            limit = STATIC_DIST if static else MAX_DIST
            if d > limit:
                if static and d <= MAX_DIST:
                    print(f"거부: {root} <- {tid} (정지 조각 뒤 거리 {d:.3f} > {STATIC_DIST})")
                continue
            h_end = heading(mrecs[-HEAD_WIN:])
            if h_end is not None and h_new is not None and turn(h_end, h_new) > HEAD_MAX:
                print(f'거부: {root} <- {tid} (방향 차이 {turn(h_end, h_new):.0f}° > {HEAD_MAX}°)')
                continue
            if best is None or d < best_d:
                best, best_d, best_gap = root, d, gap

        if best is None:
            merged[tid] = list(recs)
            members[tid] = [tid]
        else:
            merged[best].extend(recs)
            members[best].append(tid)
            print(f"연결: {best} ← {tid}  (공백 {best_gap}프레임, 거리 {best_d:.3f})")

    print("\n=== 이어붙인 결과 ===")
    for root, recs in merged.items():
        cnt = Counter(rec["cls"] for rec in recs)
        print(f"ID {root:>3} | 프레임 {recs[0]['frame']:>3}~{recs[-1]['frame']:>3} "
            f"| 조각 {members[root]} | {dict(cnt)}")

    data["tracks"] = merged
    data["stitch"] = {"max_gap": MAX_GAP, "max_dist": MAX_DIST,
                      "static_speed": STATIC_SPEED, "static_dist": STATIC_DIST,
                      "head_win": HEAD_WIN, "head_move": HEAD_MOVE, "head_max": HEAD_MAX,
                      "members": members}
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"저장: {out_path}")
    return out_path

if __name__ == "__main__":
    run()