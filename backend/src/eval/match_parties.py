import os
import sys
import json
from collections import Counter

MATCH_IOU = 0.3   # 라벨 박스와 이만큼 겹쳐야 같은 물체로 봄
MERGE_MIN = 3     # 한 궤적이 A, B 각각에 이 프레임 수 이상
MERGE_SHARE = 0.3 # 각 당사자 매칭의 이 비율 이상 걸려야 이어붙임으로 봄
PAIR_OPTIONS = 5  # build_facts.PAIR_OPTIONS와 같음 (질문 보기로 넣는 충돌 수)
BORN_OPTIONS = 3  # build_facts.BORN_OPTIONS와 같음

def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def align_gt(gt, out_dir):
    """흔들림을 보정한 결과 폴더(stabilize.json이 있음)면 정답 라벨 박스를 보정한 영상 좌표(첫 프레임)로 옮긴 사본.
    궤적은 보정한 영상에서 나왔는데 라벨은 원래 영상 좌표라 그대로 비교하면 카메라가 움직인 만큼 어긋난다"""
    path = os.path.join(out_dir, "stabilize.json")
    if not os.path.exists(path):
        return gt
    import numpy as np
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    W, H = st["size"]
    to_ref = {r["frame"]: np.array(r["to_ref"]) for r in st["log"] if "to_ref" in r}
    out = dict(gt, frames=[])
    for fr in gt["frames"]:
        M = to_ref.get(fr["frame"], np.eye(3))
        objs = []
        for o in fr["objects"]:
            x, y, w, h = o["bbox"]
            pts = np.array([[x * W, y * H, 1], [(x + w) * W, y * H, 1], [x * W, (y + h) * H, 1], [(x + w) * W, (y + h) * H, 1]]).T
            q = M @ pts
            q = q[:2] / q[2]
            x1, y1, x2, y2 = q[0].min() / W, q[1].min() / H, q[0].max() / W, q[1].max() / H
            objs.append(dict(o, bbox=[round(x1, 4), round(y1, 4), round(x2 - x1, 4), round(y2 - y1, 4)],
                             pos=[round((x1 + x2) / 2, 4), round(y2, 4)]))
        out["frames"].append(dict(fr, objects=objs))
    return out


def match(gt, tracks):
    """라벨 프레임마다 A·B 박스와 가장 많이 겹치는 궤적을 찾는다"""
    by_tf = {t: {r["frame"]: r for r in tr["frames"]} for t, tr in tracks.items()}
    rows = {"A": [], "B": []}
    for fr in gt["frames"]:
        f = fr["frame"]
        for o in fr["objects"]:
            if o["party"] not in rows:
                continue
            best_iou, best_t = max(((iou(o["bbox"], by_tf[t][f]["bbox"]), t)
                                    for t in tracks if f in by_tf[t]), default=(0.0, None))
            rows[o["party"]].append({"frame": f, "cls": o["cls"], "iou": round(best_iou, 3),
                                     "track": best_t if best_iou >= MATCH_IOU else None})
    out = {}
    for p, rs in rows.items():
        hits = Counter(r["track"] for r in rs if r["track"])
        out[p] = {"track": hits.most_common(1)[0][0] if hits else None,
                  "tracks": dict(hits), "labeled": len(rs), "matched": sum(hits.values()),
                  "frames": rs}
    # 한 궤적이 A와 B 둘 다에 걸리면 두 차가 하나로 이어붙여진 것
    def heavy(p):   # 그 당사자 매칭에서 큰 몫을 차지하는 궤적
        r = out[p]
        return {t for t, c in r["tracks"].items() if c >= MERGE_MIN and c >= MERGE_SHARE * r["matched"]}
    out["merged_tracks"] = sorted(heavy("A") & heavy("B"))
    return out


def run(gt_path, out_dir):
    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)
    with open(os.path.join(out_dir, "tracks_final.json"), encoding="utf-8") as f:
        tracks = json.load(f)["tracks"]
    m = match(align_gt(gt, out_dir), tracks)

    picked, options = None, []
    coll_path = os.path.join(out_dir, "collision.json")
    if os.path.exists(coll_path):
        with open(coll_path, encoding="utf-8") as f:
            col = json.load(f)
        ev = col["events"]
        if ev:
            picked = sorted([ev[0]["a"], ev[0]["b"]])
            confirmed = ev[0].get("confirmed", True)
            if not confirmed or len(ev) > 1:   # build_facts가 질문을 만드는 조건과 같음
                pairs = ((ev if confirmed else col.get("candidates", []))[:PAIR_OPTIONS]
                         + col.get("born_candidates", [])[:BORN_OPTIONS])
                options = [sorted([k["a"], k["b"]]) for k in pairs]
    truth = sorted(t for t in (m["A"]["track"], m["B"]["track"]) if t)
    valid = len(truth) == 2 and not m["merged_tracks"]
    m["picked"] = picked
    m["options"] = options
    m["parties_ok"] = valid and picked == truth
    m["in_options"] = valid and truth in options

    print(f"=== {gt['video']} ===")
    for p in ("A", "B"):
        r = m[p]
        print(f"  라벨 {p}: 궤적 {r['track']} | 겹친 궤적 {r['tracks']} | 라벨 {r['labeled']}장 중 {r['matched']}장 매칭")
    if m["merged_tracks"]:
        print(f"  주의: 한 궤적이 A와 B 둘 다에 걸림 {m['merged_tracks']} (두 차가 이어붙여짐)")
    print(f"  파이프라인이 고른 당사자 {picked} | 맞음: {m['parties_ok']} | 질문 보기에 정답: {m['in_options']}")

    out_path = os.path.join(out_dir, "party_match.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    return m


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])