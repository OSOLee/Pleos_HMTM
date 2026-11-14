import os
import sys
import cv2
import json
import math
import numpy as np
from collections import Counter
import torch
from ultralytics import YOLO
from ultralytics.engine.results import Boxes
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import IterableSimpleNamespace, YAML

# 탐지 모델. 재학습 모델을 받으면 MTM_DETECTOR=models/<파일>.pt 로 바꿔서 돌림 (코드 수정 없이 전후 비교)
MODEL = os.environ.get("MTM_DETECTOR", "models/yolov8s.pt")
# 신호등을 못 잡는 모델(재학습 모델)을 쓸 때 신호등만 따로 잡는 모델. 비우면 쓰지 않음 (예: MTM_LIGHT_DETECTOR=models/yolov8s.pt)
# 보조 모델이 맡는 종류(COCO 이름, 쉼표로 구분). MTM_HELPER_DETECTOR=models/yolov8s.pt MTM_HELPER_CLASSES="person,bicycle,traffic light"
# 이면 주 모델의 사람·자전거는 버리고 보조 모델의 것을 쓴다 (블랙박스 모델은 보행자·자전거를 학습하지 않았음).
# MTM_LIGHT_DETECTOR는 예전 이름: 신호등만 맡기는 것과 같음
HELPER_MODEL = os.environ.get("MTM_HELPER_DETECTOR") or os.environ.get("MTM_LIGHT_DETECTOR", "")
HELPER_CLASSES = {c.strip() for c in os.environ.get("MTM_HELPER_CLASSES", "traffic light").split(",") if c.strip()}
HELPER_ID_BASE = 100   # 보조 모델 종류 번호에 더함. 주 모델 번호(0~)와 겹치지 않게
IMGSZ = int(os.environ.get("MTM_IMGSZ", "640"))   # 재학습 모델은 학습한 크기로 (예: MTM_IMGSZ=960)
CONF = 0.1
TRACKER = "src/analyze/bytetrack_low.yaml"
# 뒤 단계(stitch_tracks, finalize_tracks, light_states)는 COCO 종류 이름을 기준으로 짜여 있다.
# 재학습 모델(AI Hub 라벨, B의 make_yolo.py)은 이름이 달라서 여기서 COCO 이름으로 맞춘다.
# vehicle은 트럭·버스를 구분하지 않으므로 car로 둔다 (트럭·버스는 종류 질문으로 받음)
TO_COCO = {"vehicle": "car", "two_wheeler": "motorcycle", "two-wheeled-vehicle": "motorcycle",
           "pedestrian": "person", "bike": "bicycle", "traffic_light": "traffic light"}
KEEP_NAMES = {"car", "truck", "bus", "motorcycle", "bicycle", "person", "traffic light"}
SCENE_SIZE = (32, 18)
SCENE_THRESH = 10
# 흔들림을 보정한 영상의 기준. 보정 뒤에도 남는 흔들림과 카메라 바로 앞을 지나는 큰 차 때문에 차이가 10~12로
# 이어진다(cc_200711). 진짜 화면 전환은 15 이상이라 13으로 둠
SCENE_THRESH_STABILIZED = 13
GLITCH_MAX = 3   # 화면이 튄 뒤 이 프레임 수 안에 원래 장면으로 돌아오면 화면 전환이 아니라 잡음 (휴대폰 촬영)
RETURN_FACTOR = 1.5   # "돌아왔다"의 기준 = 전환 기준 × 이 값. 휴대폰이 살짝 움직여 돌아온 화면이 튀기 전과
                      # 12~13 다를 수 있음(cc_200520). 진짜 전환은 화면 전체가 바뀌어 훨씬 큼

# 추적기가 버린 탐지 이어 붙이기
# ByteTrack은 새 물체를 다음 프레임에도 잡혀야 궤적으로 확정한다. 들쭉날쭉 잡히는 이륜차·자전거는
# 확정되기 전에 버려져서, 평가 영상에서 이륜차·자전거 탐지의 절반 넘게가 추적 단계에서 사라졌다.
# 버려진 탐지를 따로 모아 가까운 것끼리 이어 조각으로 만든다.
LEFT_IOU = 0.3          # 어떤 궤적 박스와도 IoU가 이보다 작아야 버려진 탐지로 봄
LEFT_GAP = 8            # 이 프레임 수 안에 다시 잡히면 같은 조각
LEFT_DIST = 0.05        # 한 프레임 공백일 때 허용 거리 (공백이 길면 √공백 배)
LEFT_SIZE = (0.4, 2.5)  # 이전 탐지와 박스 넓이 비율 허용 범위
LEFT_MIN = 3            # 탐지가 이만큼 이상인 조각만 남김
LEFT_ID = 100000        # 조각 궤적 id 시작 번호 (추적기 id와 겹치지 않게)


PROGRESS_EVERY = 15   # 진행률을 알리는 간격 (프레임)

def box_iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def link_leftovers(left):
    """left: {프레임: [기록, ...]} 버려진 탐지 → 이어 붙인 조각 목록 (각 조각은 기록 목록)"""
    frags = []
    for f in sorted(left):
        for rec in left[f]:
            best, best_d = None, None
            for fr in frags:
                last = fr[-1]
                gap = f - last["frame"]
                if not 0 < gap <= LEFT_GAP:
                    continue
                d = math.hypot(rec["pos"][0] - last["pos"][0], rec["pos"][1] - last["pos"][1])
                ratio = (rec["bbox"][2] * rec["bbox"][3]) / max(last["bbox"][2] * last["bbox"][3], 1e-9)
                if d <= LEFT_DIST * math.sqrt(gap) and LEFT_SIZE[0] <= ratio <= LEFT_SIZE[1] \
                        and (best is None or d < best_d):
                    best, best_d = fr, d
            if best is not None:
                best.append(rec)
            else:
                frags.append([rec])
    return [fr for fr in frags if len(fr) >= LEFT_MIN]


def fill_gaps(frag, fps):
    """조각 안의 빈 프레임을 선형으로 채운다 (finalize_tracks가 길이를 탐지 횟수로 재기 때문)"""
    out = [frag[0]]
    for a, b in zip(frag, frag[1:]):
        for f in range(a["frame"] + 1, b["frame"]):
            k = (f - a["frame"]) / (b["frame"] - a["frame"])
            bbox = [round(a["bbox"][i] + (b["bbox"][i] - a["bbox"][i]) * k, 4) for i in range(4)]
            out.append({"frame": f, "t": round(f / fps, 3), "cls": a["cls"], "conf": None,
                        "bbox": bbox, "pos": [round(bbox[0] + bbox[2] / 2, 4), round(bbox[1] + bbox[3], 4)],
                        "filled": True})
        out.append(b)
    return out


def run(video, out_dir="outputs", save_video=False, stabilized=False, progress=None, scene_cut=True):
    """progress: (처리한 프레임 수, 전체 프레임 수)를 받는 함수. 서버가 "분석 중 40%"를 보여 줄 때 씀"""
    thresh = SCENE_THRESH_STABILIZED if stabilized else SCENE_THRESH
    if not scene_cut:   # 블랙박스: 카메라가 움직여 장면이 계속 바뀌므로 화면 전환으로 보지 않음
        thresh = float("inf")
    os.makedirs(out_dir, exist_ok=True)

    model = YOLO(MODEL)
    names = {int(i): TO_COCO.get(n, n) for i, n in model.names.items()}
    # 보조 모델이 맡는 종류는 주 모델에서 뺀다 (둘 다 쓰면 같은 물체가 두 번 잡힘)
    keep = [i for i, n in names.items() if n in KEEP_NAMES and not (HELPER_MODEL and n in HELPER_CLASSES)]
    if not keep and not HELPER_MODEL:
        raise SystemExit(f"탐지 모델 {MODEL}의 종류 {sorted(model.names.values())} 중 쓸 수 있는 게 없어요")
    # 탐지(predict)와 추적(BYTETracker)을 나눠 부른다. 추적기가 쓰지 않은 탐지를 알 수 있게 하려고
    # (model.track()은 둘을 한 번에 해서 버린 탐지가 보이지 않음). YOLO는 프레임당 한 번만 돈다
    helper, helper_ids = None, []
    if HELPER_MODEL:
        helper = YOLO(HELPER_MODEL)
        helper_ids = [i for i, n in helper.names.items() if n in HELPER_CLASSES]
        for i in helper_ids:
            names[HELPER_ID_BASE + i] = helper.names[i]   # 합친 탐지에서 이 번호를 그 종류로 읽음
    tracker = BYTETracker(IterableSimpleNamespace(**YAML.load(TRACKER)))
    cap = cv2.VideoCapture(video)

    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    writer = None
    if save_video:
        video_out = os.path.join(out_dir, "tracked.mp4")
        writer = cv2.VideoWriter(video_out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    history = {}
    left = {}        # 프레임 → 추적기가 쓰지 않은 탐지 기록
    frame_no = 0
    prev_gray = None
    cut_frame = None
    suspect = None   # [튄 프레임 번호, 튀기 전 그림, 기다린 프레임 수]: GLITCH_MAX 안에 돌아오면 잡음
    glitches = []

    def scene_diff(a, b):
        # 검은 테두리는 빼고 비교: 흔들림을 보정한 영상(stabilize.py)은 테두리가 매 프레임 움직여서
        # 화면 전환으로 잘못 잡혔다. 일반 영상의 고정 검은 띠에는 영향 없음
        valid = (a > 8) & (b > 8)
        d = np.abs(a.astype(float) - b.astype(float))
        return d[valid].mean() if valid.any() else 0.0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if progress and frame_no % PROGRESS_EVERY == 0:
            progress(frame_no, total)

        gray = cv2.cvtColor(cv2.resize(frame, SCENE_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        if suspect is not None:
            t, ref, waited = suspect
            if scene_diff(gray, ref) > thresh * RETURN_FACTOR:   # 아직 튀기 전 장면으로 돌아오지 않음
                if waited + 1 >= GLITCH_MAX:            # 끝내 안 돌아옴 → 진짜 화면 전환
                    cut_frame = frame_no = t
                    print(f"화면 전환 감지: 프레임 {t} → 여기서 분석 중단")
                    break
                suspect[2] += 1
                frame_no += 1
                continue
            glitches.extend(range(t, frame_no))         # 휴대폰 촬영이 잠깐 튄 것 (cc_200520의 19~20프레임)
            print(f"잠깐 튄 잡음: 프레임 {t}~{frame_no - 1} (건너뜀)")
            suspect = None
        elif prev_gray is not None and scene_diff(gray, prev_gray) > thresh:
            suspect = [frame_no, prev_gray, 0]          # 다음 프레임들을 보고 정함. 그동안 탐지하지 않음
            frame_no += 1
            continue
        prev_gray = gray

        r = model.predict(frame, conf=CONF, classes=keep, agnostic_nms=True,
                          imgsz=IMGSZ, verbose=False)[0]
        if helper is not None:
            hr = helper.predict(frame, conf=CONF, classes=helper_ids, imgsz=640, verbose=False)[0]
            if len(hr.boxes):   # 주 모델의 탐지에 보조 모델의 상자를 이어 붙여 같은 추적기에 넣음
                extra = hr.boxes.data.clone().to(r.boxes.data.device)
                extra[:, -1] += HELPER_ID_BASE
                r.boxes = Boxes(torch.cat([r.boxes.data, extra]), r.orig_shape)
                r.names = names   # 상자를 그릴 때 보조 모델 종류 번호(100~)도 읽게
        dets = r.boxes.cpu().numpy()
        tracks = tracker.update(dets, frame)   # 행마다 [x1, y1, x2, y2, id, 점수, 클래스, 쓴 탐지 번호]

        def record(x1, y1, x2, y2, c, cf):
            return {"frame": frame_no, "t": round(frame_no / fps, 3), "cls": names[int(c)],
                    "conf": round(float(cf), 3),
                    "bbox": [round(float(x1) / w, 4), round(float(y1) / h, 4),
                             round(float(x2 - x1) / w, 4), round(float(y2 - y1) / h, 4)],
                    "pos": [round(float(x1 + x2) / 2 / w, 4), round(float(y2) / h, 4)]}

        used, boxes = set(), []
        for x1, y1, x2, y2, tid, cf, c, idx in tracks:
            rec = record(x1, y1, x2, y2, c, cf)
            history.setdefault(int(tid), []).append(rec)
            boxes.append(rec["bbox"])
            used.add(int(idx))
        for i, ((x1, y1, x2, y2), cf, c) in enumerate(zip(dets.xyxy, dets.conf, dets.cls)):
            rec = record(x1, y1, x2, y2, c, cf)
            if i not in used and all(box_iou(rec["bbox"], b) < LEFT_IOU for b in boxes):
                left.setdefault(frame_no, []).append(rec)

        if writer:
            writer.write(r.plot())
        frame_no += 1

    cap.release()
    if writer:
        writer.release()
    if suspect is not None and cut_frame is None:   # 마지막 프레임이 튄 채로 끝남
        cut_frame = frame_no = suspect[0]

    frags = link_leftovers(left)
    for k, frag in enumerate(frags):
        history[LEFT_ID + k] = [dict(rec, source="leftover") for rec in fill_gaps(frag, fps)]
    print(f"버려진 탐지 {sum(len(v) for v in left.values())}개 → 조각 {len(frags)}개 추가 (id {LEFT_ID}부터)")

    print("\n=== ID 요약 ===")
    for tid, recs in sorted(history.items()):
        first, last = recs[0], recs[-1]
        major = Counter(rec["cls"] for rec in recs).most_common(1)[0][0]
        print(f"ID {tid:>3} | {major:<10} | 프레임 {first['frame']:>3}~{last['frame']:>3} ({len(recs):>3}회) | 시작 {first['pos']} → 끝 {last['pos']}")

    out = {
        "schema_version": "0.2",
        "video": video,
        "fps": fps,
        "detector": MODEL,
        "helper": {"model": HELPER_MODEL, "classes": sorted(HELPER_CLASSES)} if HELPER_MODEL else None,
        "detector_names": {str(i): n for i, n in model.names.items()},   # 모델 원래 종류 이름 (cls는 COCO 이름으로 맞춘 것)
        "imgsz": IMGSZ,
        "tracker": TRACKER,
        "leftover": {"iou": LEFT_IOU, "gap": LEFT_GAP, "dist": LEFT_DIST, "size": list(LEFT_SIZE),
                     "min": LEFT_MIN, "id_from": LEFT_ID, "fragments": len(frags)},
        "frames_analyzed": frame_no,
        "scene_cut_frame": cut_frame,
        "glitch_frames": glitches,   # 한 프레임만 튀어서 건너뛴 프레임 (탐지 없음)
        "tracks": {str(tid): recs for tid, recs in sorted(history.items())},
    }

    out_path = os.path.join(out_dir, "tracks.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"저장: {out_path}")
    return out_path

if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else "data/videos/sample.mp4"
    run(video)
