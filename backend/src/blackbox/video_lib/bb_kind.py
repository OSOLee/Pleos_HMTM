# MTM(OSOLee/MTM) feature/server의 src/analyze/bb_kind.py 복사본. import만 video_lib로 바꿈 (docs/origin.md). MTM 쪽을 고친 뒤 다시 복사한다.
"""사고 상대가 보행자·자전거일 신호 (bb_partner.json → bb_kind.json)

  python src/analyze/bb_kind.py <결과 폴더> <영상>

사고 직전 2초(WINDOW 프레임)에서만 새 모델(bb_v2: 보행자·자전거를 더 잘 잡음)을 돌려, 사람·자전거가
확신도 MIN_CONF 이상·상자 넓이 MIN_AREA 이상으로 MIN_FRAMES 프레임 이상 나오면 "상대가 보행자·자전거일 수 있다"고 본다.
판정에 쓰는 탐지(bb_v1)는 그대로 두고 이 신호만 더한다 (tools/ped_trigger_report.py 실험, 286개 영상:
민감도 70%, 오경보 5%, 종류 정확도 90%).
탐지 해상도·최소 확신도는 run(imgsz=, conf=)로 정한다 (기본 640·0.1, 환경변수 MTM_KIND_IMGSZ·MTM_KIND_CONF). 전체 추적은 640으로 하고
상대 종류를 정하는 이 사고 직전 2~3초만 960으로 다시 탐지하는 방식(HMTM 배포 서버용)을 쓰려면 imgsz=960을 넘긴다.
출력 bb_kind.json: {"fired", "kind"(person|bicycle|None), "score", "frames", "impact_frame", "model", "imgsz", "conf", "reason"}
모델 파일이 없거나 사고 순간이 없으면 fired=false로 두고 이유를 적는다 (분석은 그대로 계속됨).
"""
import json
import os
import sys

MODEL = os.environ.get("MTM_KIND_MODEL", "models/bb_v2.pt")
IMGSZ = int(os.environ.get("MTM_KIND_IMGSZ", "640"))      # 탐지 해상도 (모델을 학습한 크기는 960)
CONF = float(os.environ.get("MTM_KIND_CONF", "0.1"))     # 탐지 최소 확신도 (신호 기준 MIN_CONF보다 낮게 두고 거기서 거름)
WINDOW, STRIDE, AFTER = 30, 3, 3        # 사고 직전 30프레임(2초), 3프레임마다, 사고 뒤 3프레임까지
MIN_CONF, MIN_AREA, MIN_FRAMES = 0.4, 0.003, 3
PERSON_BOX_MIN = 0.25      # 횡단보도 관계에 쓸 사람 박스의 최소 확신도
KINDS = {"person": "person", "pedestrian": "person", "bicycle": "bicycle", "bike": "bicycle"}


def _load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def decide(dets):
    """dets: [(확신도, 넓이, 프레임, 종류)] → (신호 여부, 종류, 점수). 종류는 기준을 넘긴 탐지 중 가장 높은 점수의 것"""
    ok = [d for d in dets if d[0] >= MIN_CONF and d[1] >= MIN_AREA]
    if len({d[2] for d in ok}) < MIN_FRAMES:
        return False, None, None
    best = max(ok, key=lambda d: d[0])
    return True, best[3], round(best[0], 3)


def run(case_dir, video, model_path=None, imgsz=None, conf=None):
    model_path = model_path or MODEL
    imgsz = imgsz or IMGSZ
    conf = CONF if conf is None else conf
    part = _load(os.path.join(case_dir, "bb_partner.json"))
    out = {"fired": False, "kind": None, "score": None, "frames": [], "impact_frame": part["impact_frame"],
           "model": os.path.basename(model_path), "imgsz": imgsz, "conf": conf, "reason": None}
    imp = part["impact_frame"]
    if imp is None:   # 사고 순간을 못 찾음: 촬영 차 움직임의 마지막 구간 끝을 본다 (bb_facts와 같은 기준)
        segs = _load(os.path.join(case_dir, "ego_motion.json"))["summary"].get("segments") or []
        imp = segs[-1]["to"] if segs else 0
        out["impact_frame"] = imp
    if not os.path.exists(model_path):
        out["reason"] = "model_missing"
    else:
        import cv2
        from ultralytics import YOLO
        yolo = YOLO(model_path)
        kinds = {int(k): KINDS.get(v) for k, v in yolo.names.items()}
        cap = cv2.VideoCapture(video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        W, H = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        frames = list(range(max(imp - WINDOW, 0), min(imp + AFTER, total), STRIDE))
        dets, persons = [], {}
        for f in frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, img = cap.read()
            if not ok:
                continue
            r = yolo.predict(img, conf=conf, imgsz=imgsz, agnostic_nms=True, verbose=False)[0]
            for b, s, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()):
                k = kinds.get(int(c))
                if k:
                    dets.append((s, (b[2] - b[0]) * (b[3] - b[1]) / (W * H), f, k))
                if k == "person" and s >= PERSON_BOX_MIN and s > persons.get(f, [0, 0, 0, 0, 0])[4]:
                    persons[f] = [round(v, 1) for v in b] + [round(s, 3)]    # 프레임마다 가장 확실한 사람 하나 (픽셀 좌표)
        out["fps"] = cap.get(cv2.CAP_PROP_FPS) or None
        cap.release()
        out["frames"] = frames
        # 횡단보도 위치 관계(bb_crosswalk)에 쓸 보행자 박스: 발 위치 = 박스 아래 가운데
        out["person_boxes"] = [{"frame": f, "box": b} for f, b in sorted(persons.items())]
        out["fired"], out["kind"], out["score"] = decide(dets)
    with open(os.path.join(case_dir, "bb_kind.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    return out


def load(case_dir):
    """저장된 신호 (없으면 None)"""
    p = os.path.join(case_dir, "bb_kind.json")
    return _load(p) if os.path.exists(p) else None


if __name__ == "__main__":
    r = run(sys.argv[1], sys.argv[2])
    print(r["fired"], r["kind"], r["score"], r["reason"])
