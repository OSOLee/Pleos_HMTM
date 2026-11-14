import json
import math
import argparse

FRAME = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

def border_pos(p):
    x, y = p
    if y <= 1e-9:
        return x
    if x >= 1 - 1e-9:
        return 1 + y
    if y >= 1 - 1e-9:
        return 2 + (1 - x)
    return 3 + (1 - y)

def to_border(c, p):
    dx, dy = p[0] - c[0], p[1] - c[1]
    ts = []
    if dx > 0:
        ts.append((1 - c[0]) / dx)
    if dx < 0:
        ts.append(-c[0] / dx)
    if dy > 0:
        ts.append((1 - c[1]) / dy)
    if dy < 0:
        ts.append(-c[1] / dy)
    t = min(ts)
    return (min(max(c[0] + t * dx, 0.0), 1.0), min(max(c[1] + t * dy, 0.0), 1.0))

def build_scene(corners, video, frame_ref=0, road_type="intersection", closed=None):
    """closed: 삼거리(T자형)에서 길이 없는 쪽의 방위(north/east/south/west). 그쪽에는 진입로를 만들지 않는다.
    None이면 사거리"""
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    pts = sorted(corners, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    edges = [(pts[i], pts[(i + 1) % 4]) for i in range(4)]

    mids = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in edges]
    by_y = sorted(range(4), key=lambda i: mids[i][1])
    names = {by_y[0]: "north", by_y[3]: "south"}
    left, right = sorted(by_y[1:3], key=lambda i: mids[i][0])
    names[left], names[right] = "west", "east"

    zones = [{"id": "intersection", "type": "intersection",
              "polygon": [[round(x, 4), round(y, 4)] for x, y in pts]}]
    for i, (p, q) in enumerate(edges):
        if names[i] == closed:
            continue
        pb, qb = to_border((cx, cy), p), to_border((cx, cy), q)
        sp, sq = border_pos(pb), border_pos(qb)
        span = (sq - sp) % 4

        mid = sorted([k for k in FRAME if 0 < (border_pos(k) - sp) % 4 < span],
                     key=lambda k: -((border_pos(k) - sp) % 4))
        poly = [p, q, qb] + mid + [pb]
        zones.append({"id": "appr_" + names[i][0], "type": "approach", "direction": names[i],
                      "polygon": [[round(x, 4), round(y, 4)] for x, y in poly]})
    return {
        "schema_version": "0.3",
        "video": video,
        "frame_ref": frame_ref,
        "road_type": road_type,
        "junction_type": "t" if closed else "cross",
        "closed_side": closed,
        "source": "corners",
        "corners": [[round(x, 4), round(y, 4)] for x, y in pts],
        "roi": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        "zones": zones,
        "lines": [],
        "signals": [],
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="교차로 네 모서리로 scene.json 만들기")
    ap.add_argument("--video", required=True)
    ap.add_argument("--corners", required=True, help='네 모서리 "x,y, x,y, x,y, x,y" (0~1, 순서 상관없음)')
    ap.add_argument("--out", required=True)
    ap.add_argument("--frame-ref", type=int, default=0)
    ap.add_argument("--road-type", default="intersection")
    ap.add_argument("--closed", choices=["north", "east", "south", "west"], help="삼거리에서 길이 없는 쪽 (화면 기준)")
    args = ap.parse_args()

    corners = [tuple(float(v) for v in c.split(",")) for c in args.corners.split()]
    if len(corners) != 4:
        raise SystemExit("모서리는 정확히 4개여야 함")
    scene = build_scene(corners, args.video, args.frame_ref, args.road_type, args.closed)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=1)
    print(f"저장: {args.out}")
    for z in scene["zones"]:
        print(f"  {z['id']:<13} {z['polygon']}")