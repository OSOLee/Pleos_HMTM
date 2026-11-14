"""라벨이 빠진 클래스를 사전학습 모델로 채우기 (교차로 신호 데이터의 보행자 등)

교차로 신호 데이터에는 보행자 라벨이 없다. 그대로 학습하면 화면 속 보행자를 '배경'으로 배워
보행자 탐지가 나빠진다. COCO 사전학습 모델로 보행자를 찾아 라벨에 추가한다.
또 이 데이터의 bike(이륜차)에는 자전거가 섞여 있어, COCO 모델이 자전거로 보는 박스는 bicycle로 고친다.

사용법 (GPU가 있는 Colab에서 돌리는 것을 권장, CPU면 오래 걸림):
  python pseudo_label.py --data C:\\mtm_data\\work\\dataset_v2 --prefix x_ --model yolov8l.pt --device cpu
결과: 해당 라벨 파일에 보행자 박스 추가, <data>/report_pseudo.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from classes import CLASS_ID

COCO_PERSON, COCO_BICYCLE = 0, 1
TW, BI, PE = CLASS_ID["two_wheeler"], CLASS_ID["bicycle"], CLASS_ID["person"]


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def inside(pt, box):
    return box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]


def to_xyxy(cx, cy, w, h):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def merge(existing, persons, bicycles, refine_bicycle=True, overlap=0.3):
    """existing: [(cls, xyxy)] 정규화 좌표. persons/bicycles: [xyxy]
    -> (새 라벨 목록, 추가한 보행자 수, 자전거로 고친 수)
    - 이륜차·자전거 박스 안에 중심이 있는 사람은 탑승자라 넣지 않음
    - 기존 박스와 많이 겹치는 사람도 넣지 않음 (차 안 사람, 중복)"""
    out = list(existing)
    added = fixed = 0
    if refine_bicycle:
        for i, (c, b) in enumerate(out):
            if c == TW and any(iou(b, bb) >= 0.4 for bb in bicycles):
                out[i] = (BI, b)
                fixed += 1
    riders = [b for c, b in out if c in (TW, BI)]
    for p in persons:
        center = ((p[0] + p[2]) / 2, (p[1] + p[3]) / 2)
        if any(inside(center, r) for r in riders):
            continue
        if any(iou(p, b) >= overlap for _, b in out):
            continue
        out.append((PE, p))
        added += 1
    return out, added, fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--prefix", default="x_", help="이 접두어로 시작하는 이미지만 (교차로 신호 데이터)")
    ap.add_argument("--model", default="yolov8l.pt")
    ap.add_argument("--conf", type=float, default=0.5, help="보행자로 인정할 최소 신뢰도 (높을수록 잘못 넣는 일이 줄어듦)")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--device", default="0")
    ap.add_argument("--no-bicycle", action="store_true", help="자전거 고치기를 끔")
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.model)
    data = Path(a.data)
    stats = Counter()
    images = sorted(p for p in (data / "images").rglob(f"{a.prefix}*") if p.suffix.lower() in {".jpg", ".png", ".jpeg"})
    print(f"대상 이미지 {len(images):,}장")
    for i, img in enumerate(images, 1):
        split = img.parent.name
        lp = data / "labels" / split / f"{img.stem}.txt"
        existing = []
        if lp.exists():
            for line in lp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    c, cx, cy, w, h = line.split()
                    existing.append((int(c), to_xyxy(float(cx), float(cy), float(w), float(h))))
        r = model.predict(str(img), imgsz=a.imgsz, conf=a.conf, classes=[COCO_PERSON, COCO_BICYCLE],
                          device=a.device, verbose=False)[0]
        persons, bicycles = [], []
        for b, c in zip(r.boxes.xyxyn.tolist(), r.boxes.cls.tolist()):
            (persons if int(c) == COCO_PERSON else bicycles).append(tuple(b))
        new, added, fixed = merge(existing, persons, bicycles, refine_bicycle=not a.no_bicycle)
        lines = [f"{c} {(b[0] + b[2]) / 2:.6f} {(b[1] + b[3]) / 2:.6f} {b[2] - b[0]:.6f} {b[3] - b[1]:.6f}" for c, b in new]
        lp.write_text("\n".join(lines), encoding="utf-8")
        stats["persons_added"] += added
        stats["bicycles_fixed"] += fixed
        stats["images"] += 1
        if i % 200 == 0:
            print(f"  {i:,}/{len(images):,}  보행자 +{stats['persons_added']:,}, 자전거로 수정 {stats['bicycles_fixed']:,}")
    rep = dict(stats, model=a.model, conf=a.conf)
    (data / "report_pseudo.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
