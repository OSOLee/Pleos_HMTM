"""라벨 박스와 영상 프레임의 시간 어긋남(프레임 오프셋)을 영상마다 자동으로 찾기

빠르게 움직이는 차에서 박스가 앞서거나 뒤처지는 문제는, 라벨이 붙은 프레임과 영상에서 뽑은 프레임이
몇 프레임 어긋나서 생긴다. 라벨 번호가 1부터 시작하면 먼저 보정하고(AI Hub는 001부터), 남은 어긋남을 영상마다 -N~+N 프레임 옮겨 보며
사전학습 YOLO 박스와 "움직이는" 라벨 박스가 가장 잘 겹치는 오프셋을 고른다.
멈춘 차는 오프셋과 관계없이 항상 겹치므로 비교에서 뺀다. 0과 차이가 작으면 uncertain으로 두고 보정하지 않는다.

사용법:
  python align_offsets.py --labels C:\\mtm_data\\TL_img --videos C:\\mtm_data\\TS --out C:\\mtm_data\\work\\offsets.json
  python convert_aihub.py ... --offsets C:\\mtm_data\\work\\offsets.json
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from convert_aihub import VID_EXT, find_frames, load_json, video_key

LABEL_CATS = {"vehicle", "two-wheeled-vehicle", "bike", "pedestrian"}
COCO_MOVING = [0, 1, 2, 3, 5, 7]   # person, bicycle, car, motorcycle, bus, truck


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def label_boxes(fr):
    out = []
    for ob in fr.get("objects", []) or []:
        if str(ob.get("category", "")).strip().lower() in LABEL_CATS and len(ob.get("bbox", [])) >= 4:
            x, y, w, h = [float(t) for t in ob["bbox"][:4]]
            if w * h >= 400:                       # 아주 작은 박스는 비교에서 제외
                out.append((x, y, x + w, y + h))
    return out


def moving_boxes(fr, nxt, min_move):
    """다음 라벨 프레임에서 중심이 min_move 픽셀 이상 움직인 박스만 (멈춘 차는 오프셋과 무관해서 비교를 흐림)"""
    cur, nb = label_boxes(fr), label_boxes(nxt) if nxt else []
    if not nb:
        return cur
    c = lambda b: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    out = []
    for b in cur:
        bx, by = c(b)
        d = min(((bx - c(n)[0]) ** 2 + (by - c(n)[1]) ** 2) ** 0.5 for n in nb)
        if d >= min_move:
            out.append(b)
    return out


def score(lab, det):
    """라벨 박스마다 가장 잘 겹치는 탐지 박스의 IoU 평균"""
    if not lab:
        return None
    return sum(max((iou(l, d) for d in det), default=0.0) for l in lab) / len(lab)


class YoloDetector:
    def __init__(self, model, device, imgsz):
        from ultralytics import YOLO
        self.m, self.device, self.imgsz = YOLO(model), device, imgsz

    def __call__(self, img):
        r = self.m.predict(img, imgsz=self.imgsz, conf=0.2, classes=COCO_MOVING, device=self.device, verbose=False)[0]
        return [tuple(b) for b in r.boxes.xyxy.tolist()]


def estimate(video_path, frames, label_fps, search, samples, detect, min_move=3.0, margin=0.02):
    """한 영상의 추가 오프셋(영상 프레임 단위). 라벨 번호 시작값(0/1)은 먼저 보정한다"""
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    vfps = cap.get(cv2.CAP_PROP_FPS) or label_fps
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    seq = lambda f: int(f.get("sequence_frame_number", 0) or 0)
    allf = sorted(frames, key=seq)
    start = seq(allf[0]) if allf else 0
    nxt = {id(f): allf[i + 1] if i + 1 < len(allf) else None for i, f in enumerate(allf)}
    cand = [(f, moving_boxes(f, nxt[id(f)], min_move)) for f in allf]
    cand = [(f, mb) for f, mb in cand if mb]
    if not cand:
        cap.release()
        return None
    # 움직이는 박스가 많은 프레임 위주로 고르게 샘플
    stride = max(1, len(cand) // samples)
    cand = cand[::stride][:samples]
    base = {id(f): int(round((seq(f) - start) * vfps / label_fps)) for f, _ in cand}
    need = {b + o for b in base.values() for o in range(-search, search + 1) if b + o >= 0}
    imgs, i, last = {}, 0, max(need)
    while i <= last:
        ok, img = cap.read()
        if not ok:
            break
        if i in need:
            imgs[i] = img
        i += 1
    cap.release()
    dets = {k: detect(v) for k, v in imgs.items()}
    result = {}
    for o in range(-search, search + 1):
        ss = [score(mb, dets[base[id(f)] + o]) for f, mb in cand if base[id(f)] + o in dets]
        ss = [s for s in ss if s is not None]
        if ss:
            result[o] = sum(ss) / len(ss)
    if not result:
        return None
    best = max(result, key=result.get)
    # 0과 차이가 거의 없으면 보정하지 않음 (우연한 차이로 엉뚱한 값을 고르는 것 방지)
    uncertain = best != 0 and result[best] - result.get(0, 0.0) < margin
    seqs = [seq(f) for f in frames]
    return {"offset": 0 if uncertain else best, "best_raw": best, "uncertain": uncertain, "seq_start": start,
            "moving_samples": len(cand), "score": round(result[best], 3), "score_at_0": round(result.get(0, 0.0), 3),
            "video_fps": round(vfps, 3), "video_frames": nframes, "label_seq_min": min(seqs), "label_seq_max": max(seqs),
            "scores": {str(k): round(v, 3) for k, v in sorted(result.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--videos", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="yolov8s.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--label-fps", type=float, default=15.0)
    ap.add_argument("--search", type=int, default=6, help="앞뒤로 찾아볼 영상 프레임 수")
    ap.add_argument("--samples", type=int, default=8, help="영상마다 비교할 라벨 프레임 수")
    ap.add_argument("--keep-prefix", default="cc_3_")
    a = ap.parse_args()

    vid_index = {p.stem: p for p in Path(a.videos).rglob("*") if p.suffix.lower() in VID_EXT}
    videos = defaultdict(list)
    for lp in Path(a.labels).rglob("*.json"):
        data = load_json(lp)
        if data is None:
            continue
        frs = []
        find_frames(data, frs)
        for fr in frs:
            videos[video_key(fr, lp)].append(fr)
    names = [v for v in sorted(videos) if v in vid_index and (not a.keep_prefix or v.startswith(a.keep_prefix))]
    print(f"라벨과 영상이 모두 있는 영상 {len(names)}개")

    detect = YoloDetector(a.model, a.device, a.imgsz)
    out, dist = {}, Counter()
    for i, v in enumerate(names, 1):
        r = estimate(vid_index[v], videos[v], a.label_fps, a.search, a.samples, detect)
        if r:
            out[v] = r
            dist[r["offset"]] += 1
            tag = " (차이 미미, 보정 안 함)" if r["uncertain"] else ""
            print(f"[{i}/{len(names)}] {v}: 시작번호 {r['seq_start']}, offset {r['offset']:+d}{tag} "
                  f"(IoU {r['score_at_0']} -> {r['score']}), fps {r['video_fps']}, 움직이는 표본 {r['moving_samples']}")
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n[오프셋 분포] " + ", ".join(f"{k:+d}: {n}개" for k, n in sorted(dist.items())))
    print(f"저장: {a.out}")


if __name__ == "__main__":
    main()
