"""사전학습 모델 기준 성능 확인: 영상에 그대로 돌려 클래스별 탐지 수와 샘플 프레임을 저장

사용법:
  python baseline.py videos/ --model yolov8s.pt --out runs/baseline/v8s     # 지금까지 쓰던 모델
  python baseline.py videos/ --model yolov8l.pt --out runs/baseline/v8l     # 학습 전 큰 모델
  python baseline.py videos/ --model runs/train/v8l_cctv_v1/weights/best.pt --out runs/baseline/v8l_ft   # 학습 후
결과: runs/baseline/<영상>/summary.json, detections.json, samples/*.jpg
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
from ultralytics import YOLO

from classes import CLASSES, CLASS_ID, COCO_TO_OURS

VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv"}


def class_map(model):
    """COCO 사전학습 모델이면 COCO 번호를, 학습된 모델이면 우리 클래스 번호를 우리 이름으로 바꾸는 표"""
    names = model.names
    if len(names) == 80:                                   # COCO 사전학습 모델
        return {coco: CLASSES[ours] for coco, ours in COCO_TO_OURS.items()}
    return {i: n for i, n in names.items() if n in CLASS_ID}  # 학습된 모델 (이름 그대로)


def run(model, video, out_dir, stride, conf, imgsz, sample_every, device):
    cmap = class_map(model)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "samples").mkdir(exist_ok=True)

    frames, counts, conf_sum = [], Counter(), defaultdict(float)
    idx = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            r = model.predict(img, conf=conf, imgsz=imgsz, classes=list(cmap), device=device, verbose=False)[0]
            objs = []
            for box, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                name = cmap[int(c)]
                objs.append({"cls": name, "conf": round(s, 3), "bbox": [round(v, 1) for v in box]})
                counts[name] += 1
                conf_sum[name] += s
            frames.append({"frame": idx, "t": round(idx / fps, 3) if fps else None, "objects": objs})
            if (idx // stride) % sample_every == 0:
                cv2.imwrite(str(out_dir / "samples" / f"{idx:06d}.jpg"), r.plot())
        idx += 1
    cap.release()

    summary = {
        "video": str(video), "model": str(model.ckpt_path), "fps": fps, "size": [w, h],
        "frames_total": idx, "frames_checked": len(frames), "stride": stride, "conf": conf, "imgsz": imgsz,
        "per_class": {k: {"count": counts[k], "avg_conf": round(conf_sum[k] / counts[k], 3) if counts[k] else None}
                      for k in CLASSES},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "detections.json").write_text(json.dumps(
        {"video": str(video), "fps": fps, "size": [w, h], "model": str(model.ckpt_path), "classes": CLASSES,
         "frames": frames}, ensure_ascii=False), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="영상 파일 또는 영상 폴더")
    ap.add_argument("--model", default="yolov8s.pt")
    ap.add_argument("--stride", type=int, default=5, help="N프레임마다 한 번 탐지")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--sample-every", type=int, default=20, help="탐지 N번마다 결과 이미지 저장")
    ap.add_argument("--device", default=0, help="GPU 번호 또는 cpu")
    ap.add_argument("--out", default="runs/baseline")
    a = ap.parse_args()

    src = Path(a.source)
    videos = sorted(p for p in src.iterdir() if p.suffix.lower() in VIDEO_EXT) if src.is_dir() else [src]
    model = YOLO(a.model)
    for v in videos:
        s = run(model, v, Path(a.out) / v.stem, a.stride, a.conf, a.imgsz, a.sample_every, a.device)
        line = ", ".join(f"{k} {s['per_class'][k]['count']}" for k in CLASSES)
        print(f"[{v.name}] {line}")


if __name__ == "__main__":
    main()
