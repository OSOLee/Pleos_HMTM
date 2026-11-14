import os
import json
import math
from collections import Counter

MIN_FRAMES = 15  # 이보다 짧은 궤적은 잡음으로 보고 제외
TW_MIN = 3  # motorcycle/bicycle이 이 횟수 이상이면 two_wheeler
MOVE_MIN = 0.03  # 시작점에서 최대 이동 거리가 이보다 작으면 정지 물체
# 사람(person)으로 잡혔는데 1초에 자기 키의 이 배 이상 움직이면 자전거·오토바이를 탄 사람일 수 있음.
# 위에서 내려다본 이륜차는 탈것은 못 잡고 사람만 잡는 경우가 많다 (평가 영상의 이륜차·자전거 당사자 6궤적 중 5개가
# 0.93~1.65, 걷는 사람 20궤적 중 17개가 0.44 이하). 화면 거리가 아니라 키로 나눠서 카메라와의 거리 영향을 줄임
RIDER_HS = 0.8
NAME_MAP = {
    "car": "car",
    "truck": "truck",
    "bus": "bus",
    "motorcycle": "two_wheeler",
    "bicycle": "bicycle",
    "person": "pedestrian",
    "traffic light": "traffic_light",
}


def decide_cls(votes):
    """반환: (종류, 정한 방법). 방법은 majority(다수결) 또는 two_wheeler_rule
    (오토바이·자전거 표가 TW_MIN개 이상이라 다수결 결과를 뒤집음. 틀릴 수 있어서 build_facts가 질문으로 확인)"""
    major = NAME_MAP.get(votes.most_common(1)[0][0], "unknown")
    moto = votes.get("motorcycle", 0)
    bike = votes.get("bicycle", 0)
    if moto >= TW_MIN or bike >= TW_MIN:
        tw = "two_wheeler" if moto >= bike else "bicycle"
        return tw, ("majority" if tw == major else "two_wheeler_rule")
    return major, "majority"


def heights_per_sec(recs, fps, win=5):
    """5프레임 간격 이동 속도를 박스 높이로 나눈 값의 중앙값 (1초에 자기 키의 몇 배를 움직이나)"""
    vals = []
    for a, b in zip(recs, recs[win:]):
        h = (a["bbox"][3] + b["bbox"][3]) / 2
        if h > 0:
            d = math.hypot(b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1])
            vals.append(d / ((b["frame"] - a["frame"]) / fps) / h)
    vals.sort()
    return vals[len(vals) // 2] if vals else 0.0


def max_move(recs):
    x0, y0 = recs[0]["pos"]
    return max(math.hypot(r["pos"][0] - x0, r["pos"][1] - y0) for r in recs)


def interpolate(frames, fps):
    out = [frames[0]]
    for prev, cur in zip(frames, frames[1:]):
        gap = cur["frame"] - prev["frame"]
        for k in range(1, gap):
            a = k / gap
            f = prev["frame"] + k
            out.append(
                {
                    "frame": f,
                    "t": round(f / fps, 3),
                    "bbox": [
                        round(p + (c - p) * a, 4)
                        for p, c in zip(prev["bbox"], cur["bbox"])
                    ],
                    "pos": [
                        round(p + (c - p) * a, 4)
                        for p, c in zip(prev["pos"], cur["pos"])
                    ],
                    "conf": None,
                    "yolo_cls": None,
                    "interp": True,
                }
            )
        out.append(cur)
    return out


def run(out_dir="outputs"):
    in_path = os.path.join(out_dir, "tracks_stitched.json")
    out_path = os.path.join(out_dir, "tracks_final.json")

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)

    final, dropped = {}, {}
    for tid, recs in data["tracks"].items():
        if len(recs) < MIN_FRAMES:
            dropped[tid] = f"short ({len(recs)} frames)"
            continue

        votes = Counter(r["cls"] for r in recs)
        move = max_move(recs)
        cls, cls_from = decide_cls(votes)
        if cls == "pedestrian" and heights_per_sec(recs, data["fps"]) >= RIDER_HS:
            cls_from = "fast_person"   # 값은 그대로 두고 build_facts가 종류를 물음
        final[tid] = {
            "cls": cls,
            "cls_from": cls_from,
            "cls_votes": dict(votes),
            "moving": move >= MOVE_MIN,
            "max_move": round(move, 3),
            "members": data["stitch"]["members"][tid],
            "frames": interpolate(
                [
                    {
                        "frame": r["frame"],
                        "t": r["t"],
                        "bbox": r["bbox"],
                        "pos": r["pos"],
                        "conf": r["conf"],
                        "yolo_cls": r["cls"],
                        "interp": False,
                    }
                    for r in recs
                ],
                data["fps"],
            ),
        }

    print("=== 최종 궤적 ===")
    for tid, tr in final.items():
        fr = tr["frames"]
        print(
            f"ID {tid:>3} | {tr['cls']:<12} | {'이동' if tr['moving'] else '정지'} "
            f"(최대 {tr['max_move']:.3f}) | 프레임 {fr[0]['frame']:>3}~{fr[-1]['frame']:>3} | {tr['cls_votes']}"
        )
    print("\n=== 제외 ===")
    for tid, why in dropped.items():
        print(f"ID {tid:>3} | {why}")

    out = {
        "schema_version": "0.2",
        "source": "yolo",
        "video": data["video"],
        "fps": data["fps"],
        "detector": data["detector"],
        "tracker": data["tracker"],
        "scene_cut_frame": data.get("scene_cut_frame"),
        "params": {
            "min_frames": MIN_FRAMES,
            "tw_min": TW_MIN,
            "move_min": MOVE_MIN,
            "stitch": {
                "max_gap": data["stitch"]["max_gap"],
                "max_dist": data["stitch"]["max_dist"],
            },
        },
        "tracks": final,
        "dropped": dropped,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")
    return out_path

if __name__ == "__main__":
    run()