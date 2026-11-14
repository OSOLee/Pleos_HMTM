# MTM(OSOLee/MTM) feature/server의 src/analyze/bb_crosswalk.py 복사본. import만 video_lib로 바꿈 (docs/origin.md). MTM 쪽을 고친 뒤 다시 복사한다.
"""보행자와 횡단보도의 위치 관계: 사고 직전 사람 박스(bb_kind.json) + 횡단보도 모델 → bb_crosswalk.json  (M5, B의 학습 모델)

  python src/analyze/bb_crosswalk.py <결과 폴더> <영상>

bb_kind가 사고 직전에 잡은 사람 박스의 발 위치(박스 아래 가운데, 픽셀)와 횡단보도 박스를 비교한다 (scene_crosswalk.relate_crosswalk, B 참고 구현):
발이 박스 안인 프레임이 60% 이상 → crosswalk(확정), 횡단보도가 보이면 near_crosswalk(추정), 거의 안 보이면 아무것도 내지 않음(질문).
출력 bb_crosswalk.json: {"ped_place": {"value", "confidence", "guess"} 또는 None, "dist_from_crosswalk_m": 같은 모양 또는 None, "hints", "reason"}
보행자 신호(bb_kind)가 없거나 모델이 없으면 둘 다 None.
모델에 넘기는 최소 확신도는 run(conf=)로 정한다 (기본 scene_crosswalk.CW_PRED_CONF = 0.15).
"""
import json
import os
import sys

MODEL = os.environ.get("MTM_CROSSWALK_MODEL", "models/crosswalk.pt")


def _load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def _fact(f):
    return {"value": f.value, "confidence": round(f.confidence, 3), "guess": bool(f.guess)} if f else None


def run(case_dir, video, model_path=None, imgsz=960, conf=None):
    model_path = model_path or MODEL
    out = {"ped_place": None, "dist_from_crosswalk_m": None, "hints": None, "reason": None, "model": os.path.basename(model_path)}
    kind = _load(os.path.join(case_dir, "bb_kind.json")) if os.path.exists(os.path.join(case_dir, "bb_kind.json")) else None
    boxes = (kind or {}).get("person_boxes") or []
    if not kind or not kind.get("fired") or kind.get("kind") != "person" or not boxes:
        out["reason"] = "no_pedestrian"
    elif not os.path.exists(model_path):
        out["reason"] = "model_missing"
    else:
        import cv2
        from ultralytics import YOLO
        from src.blackbox.video_lib import scene_crosswalk as sc
        cap = cv2.VideoCapture(video)
        fps = kind.get("fps") or cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames, feet = [], {}
        for pb in boxes:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pb["frame"])
            ok, img = cap.read()
            if ok:
                t = pb["frame"] / fps
                x1, y1, x2, y2 = pb["box"][:4]
                frames.append((t, img))
                feet[t] = ((x1 + x2) / 2, y2)
        cap.release()
        facts = sc.relate_crosswalk(YOLO(model_path), frames, feet, kind["impact_frame"] / fps, imgsz=imgsz,
                                    conf=sc.CW_PRED_CONF if conf is None else conf)
        out["ped_place"] = _fact(facts.get("parties.other.ped_place"))
        out["dist_from_crosswalk_m"] = _fact(facts.get("parties.other.dist_from_crosswalk_m"))
        first = next(iter(facts.values()), None)
        out["hints"] = first.hints if first else None
        if not facts:
            out["reason"] = "crosswalk_unclear"      # 사람 박스가 3프레임 미만이거나 횡단보도가 거의 안 보임 → 질문
    with open(os.path.join(case_dir, "bb_crosswalk.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    r = run(sys.argv[1], sys.argv[2])
    print(r["ped_place"], r["dist_from_crosswalk_m"], r["reason"])
