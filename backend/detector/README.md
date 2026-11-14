# MTM 객체 탐지 (B)

CCTV 영상에서 차량·이륜차·사람을 찾는 YOLO 모델. 출력은 A의 추적 단계로 넘어간다.

## 클래스

`vehicle`, `two_wheeler`, `bicycle`, `person` (4개, `classes.py`, `aihub_classes.json`)

신호등 색은 M3, 표지판은 M4, 차선·횡단보도·도로영역은 M5(SegFormer) 담당이다.

AI Hub 교통사고 영상 데이터는 차량이 하나로 묶여 있어 승용차·트럭·버스를 구분하지 않는다. 대신 신호등 색을 학습한다.

## 모델

| 모델 | 용도 | COCO mAP50-95 | 파라미터 |
|---|---|---|---|
| `yolov8s.pt` | 지금까지 쓰던 사전학습 모델 (비교 기준) | 44.9 | 11.2M |
| `yolov8l.pt` | 파인튜닝 출발점 | 52.9 | 43.7M |

`yolov8l.pt`는 처음 실행할 때 자동으로 내려받는다.

## 순서

1. **기준 성능**: 사전학습 모델을 우리 영상에 그대로 돌려 본다 (`baseline.py`)
2. **데이터 변환** (교차로 신호 데이터는 `convert_cvat.py`로 같은 폴더에 추가, Colab에서 `pseudo_label.py`로 보행자 채우기): `inspect_aihub.py`로 라벨 점검 → `convert_aihub.py`로 TL_이미지 + TS_영상(권장) 또는 TS_이미지를 YOLO 형식으로 변환. `--preview`로 박스 위치 먼저 확인
3. **학습**: `train.py`
4. **평가**: 같은 test 영상에서 v8s(기존) / v8l(학습 전) / v8l(학습 후) 세 모델 비교

## Colab으로 학습

`colab_train.ipynb`를 Colab에서 열어 위에서부터 실행한다. 데이터와 `detector` 폴더는 구글 드라이브 `MyDrive/MTM/`에 올려 두고, 결과는 드라이브에 저장되어 런타임이 끊겨도 남는다.

## 서버 준비

```bash
nvidia-smi                                  # GPU 확인
python3 -m venv .venv && source .venv/bin/activate
pip install -U ultralytics
python -c "import torch; print(torch.cuda.is_available())"   # True여야 함
```

학습은 접속이 끊겨도 계속 돌도록 `tmux`(또는 `screen`) 안에서 실행한다.

```bash
tmux new -s train
python train.py --data data.yaml --epochs 100
# 빠져나오기: Ctrl+b, d   다시 붙기: tmux attach -t train
```

## 주의

- AI Hub 데이터, 영상, 가중치(`*.pt`), 학습 결과(`runs/`)는 커밋하지 않는다 (`.gitignore`)
- 데이터는 **영상 단위로** train/val/test를 나눈다. 프레임 단위로 섞으면 성능이 부풀려진다
