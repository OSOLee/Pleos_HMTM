"""학습 전·후 모델을 같은 평가 데이터(정답 라벨)로 비교

COCO 사전학습 모델(yolov8s.pt, yolov8l.pt)은 클래스 체계가 달라 YOLO 기본 평가(val)를 바로 쓸 수 없다.
이 스크립트는 예측을 우리 클래스로 바꾼 뒤, 학습된 모델과 똑같은 방식으로 AP를 계산한다.

사용법:
  python eval_compare.py --data C:\\mtm_data\\work\\dataset_v1 --models yolov8s.pt yolov8l.pt C:\\mtm_data\\work\\best.pt
결과: 화면 표 + <data>/compare_<split>.json

비교 가능한 클래스: vehicle, two_wheeler, bicycle, person (COCO에도 있는 것)
신호등 색, 표지판 종류는 COCO 모델이 구분하지 못해 학습된 모델만 점수가 나온다.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from classes import CLASSES, CLASS_ID, COCO_TO_OURS

IOU_THRESHOLDS = [0.5 + 0.05 * i for i in range(10)]
COMPARABLE = ["vehicle", "two_wheeler", "bicycle", "person"]
IMG_EXT = {".jpg", ".jpeg", ".png"}


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def ap_101(tp_flags, confs, n_gt):
    """COCO 방식 101점 보간 AP"""
    if n_gt == 0:
        return None
    if not confs:
        return 0.0
    order = sorted(range(len(confs)), key=lambda i: -confs[i])
    tp = fp = 0
    prec, rec = [], []
    for i in order:
        if tp_flags[i]:
            tp += 1
        else:
            fp += 1
        prec.append(tp / (tp + fp))
        rec.append(tp / n_gt)
    for i in range(len(prec) - 2, -1, -1):          # 정밀도를 오른쪽 최댓값으로 (단조 감소)
        prec[i] = max(prec[i], prec[i + 1])
    total = 0.0
    for t in [i / 100 for i in range(101)]:
        p = 0.0
        for r, pr in zip(rec, prec):
            if r >= t:
                p = pr
                break
        total += p
    return total / 101


def evaluate(preds, gts):
    """preds/gts: {이미지: [(cls, conf, box)]} / {이미지: [(cls, box)]} -> 클래스별 AP50, AP50-95, 재현율"""
    res = {}
    for c in range(len(CLASSES)):
        n_gt = sum(1 for g in gts.values() for x in g if x[0] == c)
        if n_gt == 0:
            continue
        aps = []
        rec50 = 0.0
        for th in IOU_THRESHOLDS:
            flags, confs = [], []
            for img, plist in preds.items():
                gl = [x[1] for x in gts.get(img, []) if x[0] == c]
                used = [False] * len(gl)
                for cls, conf, box in sorted([p for p in plist if p[0] == c], key=lambda p: -p[1]):
                    best, bj = 0.0, -1
                    for j, g in enumerate(gl):
                        if not used[j]:
                            v = iou(box, g)
                            if v > best:
                                best, bj = v, j
                    ok = best >= th
                    if ok:
                        used[bj] = True
                    flags.append(ok)
                    confs.append(conf)
            aps.append(ap_101(flags, confs, n_gt))
            if th == 0.5:
                rec50 = sum(flags) / n_gt
        res[CLASSES[c]] = {"n_gt": n_gt, "AP50": round(aps[0], 4), "AP50-95": round(sum(aps) / len(aps), 4),
                           "recall50": round(rec50, 4)}
    return res


def load_gt(data, split):
    gts, sizes, images = {}, {}, []
    import cv2
    for p in sorted((data / "images" / split).iterdir()):
        if p.suffix.lower() not in IMG_EXT:
            continue
        img = cv2.imread(str(p))
        h, w = img.shape[:2]
        sizes[p.name] = (w, h)
        images.append(p)
        boxes = []
        lp = data / "labels" / split / f"{p.stem}.txt"
        if lp.exists():
            for line in lp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    c, cx, cy, bw, bh = line.split()
                    cx, cy, bw, bh = float(cx) * w, float(cy) * h, float(bw) * w, float(bh) * h
                    boxes.append((int(c), (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)))
        gts[p.name] = boxes
    return gts, images


def predict(model_path, images, imgsz, device, conf):
    from ultralytics import YOLO
    m = YOLO(model_path)
    names = m.names
    coco = len(names) == 80
    if coco:
        cmap = dict(COCO_TO_OURS)
    else:
        cmap = {i: CLASS_ID[n] for i, n in names.items() if n in CLASS_ID}
    preds = {}
    for p in images:
        r = m.predict(str(p), imgsz=imgsz, conf=conf, classes=list(cmap), device=device, verbose=False)[0]
        preds[p.name] = [(cmap[int(c)], float(s), tuple(b))
                         for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())]
    return preds, coco


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="convert_aihub.py 결과 폴더 (images/, labels/)")
    ap.add_argument("--split", default="test")
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--conf", type=float, default=0.001, help="AP 계산용으로 낮게 (YOLO 평가와 같은 방식)")
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    data = Path(a.data)
    gts, images = load_gt(data, a.split)
    print(f"{a.split}: 이미지 {len(images)}장, 정답 박스 {sum(len(v) for v in gts.values())}개\n")
    results = {}
    for mp in a.models:
        print(f"[{mp}] 예측 중...")
        preds, coco = predict(mp, images, a.imgsz, a.device, a.conf)
        r = evaluate(preds, gts)
        comp = [r[c]["AP50-95"] for c in COMPARABLE if c in r]
        results[mp] = {"coco_pretrained": coco, "per_class": r,
                       "mAP50-95_comparable": round(sum(comp) / len(comp), 4) if comp else None}

    cls_list = [c for c in CLASSES if any(c in v["per_class"] for v in results.values())]
    head = f"{'클래스':<22}" + "".join(f"{Path(m).name[:18]:>20}" for m in results)
    print("\n[AP50-95 (괄호: 재현율 @IoU0.5)]")
    print(head)
    for c in cls_list:
        row = f"{c:<22}"
        for m, v in results.items():
            x = v["per_class"].get(c)
            cell = "-" if (x is None or (v["coco_pretrained"] and c not in COMPARABLE)) else f"{x['AP50-95']:.3f} ({x['recall50']:.2f})"
            row += f"{cell:>20}"
        print(row)
    print(f"{'비교 가능 4종 평균':<22}" + "".join(f"{(v['mAP50-95_comparable'] or 0):>20.3f}" for v in results.values()))
    out = data / f"compare_{a.split}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
