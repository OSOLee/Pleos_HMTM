"""사용자가 표시한 당사자 박스에서 시작해 앞뒤로 따라가 궤적을 만든다

YOLO가 당사자(주로 이륜차·자전거)를 놓쳤을 때 쓴다. 사용자는 한 프레임에서 당사자 박스와 종류만 정하고,
나머지 프레임은 OpenCV MIL 추적기로 따라간다. 만든 궤적은 tracks_final.json에 YOLO 궤적과 같은 형식으로
추가하므로 충돌·영역·사실 단계는 그대로 쓴다.

answers.json 예시:
  {"user_tracks": {"9001": {"frame": 88, "bbox": [0.31, 0.62, 0.05, 0.12], "cls": "bicycle"}},
   "collision.parties": ["1", "9001"]}
"""
import json
import math
import os

import cv2

from src.analyze.build_facts import CLS_OPTIONS
from src.analyze.finalize_tracks import MOVE_MIN

USER_ID_MIN = 9001   # 사용자 궤적 id. YOLO 궤적 id와 겹치지 않게 크게 잡음 (detect_collision이 int로 정렬)
WORK_W = 960         # 추적할 때 프레임을 이 폭으로 줄임 (메모리·속도)
VIT_MODEL = "models/object_tracking_vittrack_2023sep.onnx"   # opencv_zoo의 Vit 추적기 (없으면 MIL)
VIT_MIN_SCORE = 0.3  # Vit 추적 점수가 이보다 낮으면 놓친 것으로 보고 멈춤
STOP_SIM = 0.3       # (MIL) 처음 박스와 색 히스토그램 상관이 이보다 낮은 프레임이
STOP_RUN = 3         # (MIL) 이만큼 이어지면 놓친 것으로 보고 멈춤 (MIL은 스스로 멈추지 않고 배경에 붙음)
CLASSES = CLS_OPTIONS   # 직접 표시할 때 고르는 종류 = 종류 질문 보기 (농기계 포함)

try:   # Vit가 프레임마다 내는 OpenCV 경고("Targets are not supported ...")를 끔
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:
    pass


def check(taps, n_frames):
    """사용자가 표시한 박스가 규칙에 맞는지. n_frames: 분석한 프레임 수 (화면 전환이 있으면 그 앞까지).
    예전에는 범위 밖 프레임을 마지막 프레임으로 바꿔 조용히 다른 장면에서 추적했음"""
    for tid, t in taps.items():
        if not isinstance(t.get("frame"), int) or not 0 <= t["frame"] < n_frames:
            raise ValueError(f"{tid}의 프레임 {t.get('frame')!r}이 분석한 프레임 범위(0~{n_frames - 1}) 밖이에요")
        if not tid.isdigit() or int(tid) < USER_ID_MIN:
            raise ValueError(f"사용자 궤적 id는 {USER_ID_MIN} 이상의 숫자여야 해요: {tid}")
        if t.get("cls") not in CLASSES:
            raise ValueError(f"{tid}의 종류 {t.get('cls')!r}가 {CLASSES}에 없어요")
        x, y, w, h = t["bbox"]
        if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x + w <= 1.001 and y + h <= 1.001):
            raise ValueError(f"{tid}의 박스 {t['bbox']}가 화면(0~1) 밖이에요")


def read_frames(video, last):
    """0~last 프레임을 WORK_W 폭으로 줄여 읽는다"""
    cap = cv2.VideoCapture(video)
    frames = []
    while len(frames) <= last:
        ok, img = cap.read()
        if not ok:
            break
        h, w = img.shape[:2]
        frames.append(cv2.resize(img, (WORK_W, round(h * WORK_W / w))))
    cap.release()
    return frames


def hist(img, box):
    H, W = img.shape[:2]
    x, y, w, h = (int(v) for v in box)
    crop = img[max(0, y):min(H, y + h), max(0, x):min(W, x + w)]
    if crop.size == 0:
        return None
    hs = cv2.calcHist([cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)], [0, 1], None, [16, 8], [0, 180, 0, 256])
    return cv2.normalize(hs, hs).flatten()


def new_tracker():
    """Vit 모델 파일이 있으면 Vit, 없으면 MIL. 반환: (추적기, 종류)"""
    if os.path.exists(VIT_MODEL):
        params = cv2.TrackerVit_Params()
        params.net = VIT_MODEL
        return cv2.TrackerVit_create(params), "vit"
    return cv2.TrackerMIL_create(), "mil"


def follow(frames, f0, bbox, step):
    """f0의 박스에서 시작해 step(+1/-1) 방향으로 따라가다가 놓치면 멈춘다.
    Vit: 추적 점수가 VIT_MIN_SCORE 미만이면 멈춤
    MIL: 박스 안 색이 처음과 STOP_RUN 프레임 연속으로 많이 다르면 그 구간을 버리고 멈춤"""
    H, W = frames[0].shape[:2]
    x, y, w, h = bbox
    b0 = (int(x * W), int(y * H), max(2, int(w * W)), max(2, int(h * H)))
    tracker, kind = new_tracker()
    tracker.init(frames[f0], b0)
    ref = hist(frames[f0], b0)
    out, bad = {}, 0
    f = f0 + step
    while 0 <= f < len(frames):
        ok, b = tracker.update(frames[f])
        if not ok:
            break
        if kind == "vit":
            if tracker.getTrackingScore() < VIT_MIN_SCORE:
                break
        else:
            hb = hist(frames[f], b)
            sim = cv2.compareHist(ref, hb, cv2.HISTCMP_CORREL) if hb is not None and ref is not None else -1
            bad = bad + 1 if sim < STOP_SIM else 0
            if bad >= STOP_RUN:
                for k in range(1, bad):
                    out.pop(f - step * k, None)
                break
        out[f] = [b[0] / W, b[1] / H, b[2] / W, b[3] / H]
        f += step
    return out


def make_track(boxes, cls, fps):
    frames = []
    for f in sorted(boxes):
        x, y, w, h = boxes[f]
        frames.append({"frame": f, "t": round(f / fps, 3),
                       "bbox": [round(x, 4), round(y, 4), round(w, 4), round(h, 4)],
                       "pos": [round(x + w / 2, 4), round(y + h, 4)],
                       "conf": None, "yolo_cls": None, "interp": False, "source": "user"})
    p0 = frames[0]["pos"]
    move = max(math.hypot(r["pos"][0] - p0[0], r["pos"][1] - p0[1]) for r in frames)
    return {"cls": cls, "cls_from": "user", "cls_votes": {cls: len(frames)}, "moving": move >= MOVE_MIN,
            "max_move": round(move, 3), "members": [], "source": "user", "frames": frames}


def add(out_dir, video, taps, n_frames):
    """taps의 궤적을 만들어 tracks_final.json에 추가한다. n_frames: 분석한 프레임 수"""
    check(taps, n_frames)
    path = os.path.join(out_dir, "tracks_final.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    frames = read_frames(video, n_frames - 1)
    for tid, t in taps.items():
        f0 = t["frame"]
        boxes = {f0: t["bbox"], **follow(frames, f0, t["bbox"], -1), **follow(frames, f0, t["bbox"], 1)}
        data["tracks"][tid] = make_track(boxes, t["cls"], data["fps"])
        print(f"사용자 궤적 {tid} ({t['cls']}): {min(boxes)}~{max(boxes)}프레임, "
              f"{'이동' if data['tracks'][tid]['moving'] else '정지'}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
