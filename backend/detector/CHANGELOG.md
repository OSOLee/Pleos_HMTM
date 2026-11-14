# 변경 기록 (CHANGELOG)

## v0.17.0 (2026-11-02) AI Hub 7z 형식 지원
- AI Hub 교차로 데이터(TL_4, TS_4 등)는 확장자가 .zip이지만 **실제로는 7z 형식**이라 zip으로 열리지 않던 문제 수정
- `convert_cvat.py`: 파일 앞부분으로 형식을 판별해 폴더·zip·7z 모두 읽음. 7z는 필요한 사진 목록을 먼저 정한 뒤 7-Zip으로 한 번에 꺼냄 (7-Zip이 없으면 py7zr)
- 차종 이미지 잘라내기에서 박스가 사진 밖으로 나가면 건너뜀
- Colab 노트북 4-0 셀에 7-Zip 설치 추가

## v0.16.0 (2026-11-02) 드라이브의 압축 파일에서 바로 변환
- `convert_cvat.py`: `--labels`, `--images`에 **zip 파일을 그대로** 받음. 라벨로 고른 사진만 압축에서 꺼내므로 53GB TS_4를 풀거나 PC로 받을 필요 없음
- 압축 안의 한글 이름(cp949)을 바로잡아 교차로·악천후·시간대 폴더 구분 유지
- Colab 노트북 4-0 셀: 드라이브의 교차로 신호 데이터(Training)를 바로 추가 (기본 6,000장)

## v0.15.0 (2026-11-01) 교차로 신호 데이터 추가
- `convert_cvat.py`: 교차로 신호 체계 데이터(CVAT XML 바운딩박스)를 사고 영상 변환 결과에 이어서 추가. 파일 이름 앞에 `x_`, 카메라 단위 분할, 같은 영상에서 3초 간격, 교차로·악천후·시간대 폴더가 고르게 남도록 이미지 수 상한
- `cvat_classes.json`: car·bus·truck 등 7종 → vehicle, bike → two_wheeler, face·car_plate 제외. `--save-crops`로 차종별 차량 이미지를 잘라 저장 (M2 차종 분류용)
- `pseudo_label.py`: 이 데이터에 없는 **보행자 라벨을 COCO 사전학습 모델로 채움** (탑승자·차 안 사람 제외). bike 중 COCO가 자전거로 보는 박스는 bicycle로 수정
- Colab 노트북에 4-1 셀(보행자 채우기) 추가

## v0.14.0 (2026-11-01) 탐지 클래스 4개로 (2차 학습 준비)
- M1 객체 탐지는 움직이는 4종만: vehicle, two_wheeler, bicycle, person
- 신호등(M3 색 판별), 표지판(M4), 횡단보도(M5 SegFormer)는 다른 모델 담당이라 `aihub_classes.json`의 ignore로 이동
- 1차 학습(8개 클래스)의 신호등 0점 문제 정리. 신호등·표지판 라벨이 없는 시내도로·교차로 신호 데이터도 그대로 섞을 수 있게 됨
- 2차 학습은 `yolov8l.pt`에서 새로 시작 (클래스 수가 달라 1차 best.pt를 출발점으로 쓰지 않음)

## v0.13.0 (2026-10-29) 1차 학습 결과 반영
- `train.py`: test_metrics.json에 **평가 데이터에 있는 클래스만** 기록. 정답이 없는 클래스(traffic_light_green)에 YOLO가 전체 평균(0.2593)을 채워 넣어 점수가 있는 것처럼 보이던 문제 수정. 클래스별 AP50도 함께 기록
- 1차 학습(v8l_cctv_v1): T4, 95에폭(최고 65에폭), 평가 mAP50 0.460 / mAP50-95 0.259

## v0.12.0 (2026-10-29) 학습 전·후 비교 평가
- `eval_compare.py`: COCO 사전학습 모델(v8s, v8l)과 학습된 모델을 **같은 평가 데이터·같은 계산 방식**으로 비교. 클래스별 AP50, AP50-95, 재현율
- COCO 모델 예측을 우리 클래스로 바꿔 계산. 비교 가능한 4종(vehicle, two_wheeler, bicycle, person) 평균을 따로 표시

## v0.11.0 (2026-10-29) 드문 클래스 균형 분할
- `convert_aihub.py`: 영상 단위 분할을 무작위 대신 **드문 클래스 균형 분할**로 (기본값). 신호등·자전거·이륜차처럼 적은 클래스가 학습·검증·평가에 비율대로 들어가게 함
- 1차 변환에서 검증셋에 신호등·자전거가 하나도 없고 이륜차가 14개뿐이던 문제 대응. `--no-stratify`로 이전 방식 사용 가능

## v0.10.0 (2026-10-29) 어긋남 원인 보정
- 라벨 프레임 번호가 1부터 시작(AI Hub `_001.json`)하는 것을 자동 보정 (`--seq-start auto`). 30fps 영상에서 2프레임 밀리던 체계적 어긋남의 원인
- `align_offsets.py`: 멈춘 차는 비교에서 빼고 **움직이는 박스만** 비교 (멈춘 차가 많으면 차이가 묻혀 엉뚱한 값을 고르던 문제)
- 보정 효과가 0과 거의 같으면 `uncertain`으로 표시하고 보정하지 않음

## v0.9.0 (2026-10-28) 라벨-프레임 시간 어긋남 보정
- `align_offsets.py`: 영상마다 -6~+6 프레임을 옮겨 보며 사전학습 YOLO 박스와 라벨 박스의 IoU가 가장 높은 오프셋을 찾음. 영상 fps, 라벨 프레임 번호 범위도 기록
- `convert_aihub.py --offsets`: 영상별 오프셋을 적용해 프레임 추출. `--min-align`으로 보정 후에도 안 맞는 영상 제외
- 빠르게 움직이는 물체에서 박스가 앞서거나 뒤처지던 문제 대응 (시험 영상에서 2프레임 어긋남을 찾아 IoU 0.875 → 1.0)

## v0.8.0 (2026-10-28) 실제 AI Hub 라벨에 맞춤
- `aihub_classes.json`: 실제 category 이름 반영 (vehicle, two-wheeled-vehicle, bike, pedestrian, traffic-light-red/green/etc, traffic-sign)
- `convert_aihub.py --keep-prefix`: 영상 이름 접두어로 CCTV·3인칭(`cc_3_`)만 사용 (기본값). 1인칭 CCTV(`cc_1_`) 자동 제외
- 제외 목록은 영상 이름 일부(예: `150101`)만 적어도 일치하면 제외. 보고서에 제외·필터된 영상 이름 목록 표시

## v0.7.0 (2026-10-28) 탐지 클래스 8개 확정
- 클래스: vehicle, two_wheeler, bicycle, person, traffic_light_red, traffic_light_green, traffic_light_other, traffic_sign
- 표지판 추가 (AI Hub '표지판'), 횡단보도는 정적 요소(SegFormer) 담당으로 제외
- 학습 전 비교용 COCO 매핑에 정지 표지 → traffic_sign 추가

## v0.6.0 (2026-10-27) TS_영상 원천 지원
- `convert_aihub.py --videos`: TS_영상(mp4)에서 라벨의 프레임 번호로 필요한 장면만 뽑아 jpg로 저장. TS_이미지보다 다운로드 용량이 수십 배 작음
- 라벨 프레임 번호(15fps 기준)를 영상 fps에 맞춰 자동 환산 (30fps 영상 확인)
- `--preview N`: 박스를 그린 확인용 이미지 저장 (라벨과 프레임이 맞는지 눈으로 확인)
- 보고서에 원천 없는 라벨 수, 영상 읽기 실패, 프레임 크기 불일치 추가

## v0.5.0 (2026-10-27) AI Hub 변환기, 클래스 변경
- `convert_aihub.py`: TL_이미지(박스 라벨) + TS_이미지(원천) → YOLO 데이터. 프레임 간격 샘플링, 영상 단위 학습/검증/평가 분할, 평가용 영상 제외 목록, 이미지 수 상한, data.yaml·report.json·dataset.zip 생성
- 클래스 7개로 변경: vehicle, two_wheeler, bicycle, person, 신호등 적·녹·기타 (데이터셋에 트럭·버스 구분이 없음)
- `aihub_classes.json`: AI Hub category 이름 → 우리 클래스 매핑 (표지판·횡단보도는 제외)
- Colab 노트북: 변환기가 만든 data.yaml을 그대로 사용

## v0.4.0 (2026-10-27) AI Hub 라벨 점검
- `inspect_aihub.py`: 라벨 JSON만으로 클래스별 박스 수, CCTV/블랙박스 비율, 이미지 크기, 영상당 프레임 수, 폴더별 파일 수 요약
- 라벨 형식을 몰라도 `bbox`·`category`, `filming_way` 항목을 찾아 집계

## v0.3.0 (2026-10-26) Colab 학습 지원
- `colab_train.ipynb`: GPU 확인 → 드라이브 연결 → 데이터 복사 → 학습 → 이어서 학습 → 결과 확인 순서의 노트북
- `train.py`: `--project`(결과 저장 위치, 드라이브 지정 가능), `--save-period`(N에폭마다 가중치 저장) 추가

## v0.2.0 (2026-10-26) YOLOv8l로 변경
- 학습 출발 모델을 `yolov8l.pt`로 변경 (COCO mAP50-95 52.9, 기존 v8s 44.9)
- 학습 결과 이름 기본값 `v8l_cctv_v1`
- `baseline.py`: COCO 모델과 학습된 모델(우리 클래스) 모두 지원. 기본 모델은 기존 `yolov8s.pt`
- README: 모델 비교표, 3개 모델 비교 평가 순서

## v0.1.0 (2026-10-20) 학습 준비
- 클래스 정의 6개 (`classes.py`), COCO 사전학습 모델 클래스 매핑
- `baseline.py`: 사전학습 모델 기준 성능 측정, 클래스별 탐지 수, 샘플 프레임, detections.json
- `train.py`: 파인튜닝, 끝나면 test 분할 평가 결과 저장
- `data.yaml` 템플릿, 서버 준비 방법
- 남은 일: AI Hub 라벨 변환기 (`convert_aihub.py`) — 데이터셋 라벨 형식 확인 후 작성
