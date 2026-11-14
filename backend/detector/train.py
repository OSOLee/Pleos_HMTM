"""YOLO 파인튜닝 (학교·연구실 GPU 서버용)

사용법:
  python train.py --data data.yaml --epochs 100                      # 기본: yolov8l.pt
  python train.py --data data.yaml --device 0,1                       # GPU 2장
  python train.py --data data.yaml --batch 8                          # GPU 메모리 부족(CUDA out of memory) 시
  python train.py --resume runs/train/cctv_v1/weights/last.pt             # 끊긴 학습 이어서
학습이 끝나면 test 분할로 평가해 runs/train/<이름>/test_metrics.json 저장
"""
import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.yaml")
    ap.add_argument("--model", default="yolov8l.pt", help="사전학습 가중치 (yolov8s/m/l/x.pt 등, 처음 실행 시 자동 다운로드)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=960, help="멀리 있는 작은 차량 때문에 640보다 크게")
    ap.add_argument("--batch", type=int, default=-1, help="-1이면 GPU 메모리에 맞춰 자동")
    ap.add_argument("--device", default="0")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--name", default="v8l_cctv_v1")
    ap.add_argument("--project", default="runs/train", help="결과 저장 폴더 (Colab은 구글 드라이브 경로 권장)")
    ap.add_argument("--save-period", type=int, default=5, help="N에폭마다 가중치 따로 저장 (-1이면 끔)")
    ap.add_argument("--resume", default=None)
    a = ap.parse_args()

    if a.resume:
        YOLO(a.resume).train(resume=True)
        return

    model = YOLO(a.model)
    model.train(
        data=a.data, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=a.device, workers=a.workers,
        project=a.project, name=a.name, exist_ok=False, save_period=a.save_period,
        patience=30,          # 검증 성능이 30에폭 동안 안 오르면 조기 종료
        seed=0, deterministic=True,
        fliplr=0.5,           # 좌우 반전은 허용
        flipud=0.0,           # CCTV는 위아래가 고정이라 상하 반전 끔
        plots=True,
    )
    best = Path(a.project) / a.name / "weights" / "best.pt"
    metrics = YOLO(best).val(data=a.data, split="test", imgsz=a.imgsz, device=a.device, plots=True)
    names = metrics.names
    # 평가 데이터에 실제로 있는 클래스만 기록 (없는 클래스는 YOLO가 전체 평균으로 채워 넣어 오해를 부름)
    idx = [int(i) for i in metrics.box.ap_class_index]
    out = {
        "weights": str(best), "mAP50": round(float(metrics.box.map50), 4), "mAP50-95": round(float(metrics.box.map), 4),
        "per_class": {names[c]: {"AP50": round(float(metrics.box.ap50[k]), 4), "AP50-95": round(float(metrics.box.ap[k]), 4)}
                      for k, c in enumerate(idx)},
        "classes_without_labels": [names[c] for c in names if c not in idx],
    }
    (Path(a.project) / a.name / "test_metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
