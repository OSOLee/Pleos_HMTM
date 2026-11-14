# MTM(OSOLee/MTM) feature/server의 src/analyze/bb_scene.py 복사본. import만 video_lib로 바꿈 (docs/origin.md). MTM 쪽을 고친 뒤 다시 복사한다.
"""장면(교차로 모양) 분류 신호: 영상 + 사고 순간 → bb_scene.json  (M6, B의 학습 모델)

  python src/analyze/bb_scene.py <결과 폴더> <영상>

사고 직전 2초에서 0.5초 간격으로 장면 5장을 뽑아 클래스 확률을 평균내 한 번 판단한다 (scene_crosswalk.classify_scene, B 참고 구현).
출력 bb_scene.json: {"label": cross_signal|cross_nosignal|t_junction|straight|None, "confidence", "guess"(항상 True: 영상 단위 정확도 66%라
자동 결정에 쓰지 않음, B 평가 기록), "scores", "frames", "reason"}. 학습에 없는 장소(고속도로 등)나 모델이 없으면 label=None.
"""
import json
import os
import sys

MODEL = os.environ.get("MTM_SCENE_MODEL", "models/scene_cls.pt")
WINDOW_S = 2.0     # scene_crosswalk.SCENE_WINDOW와 같음 (사고 2초 전 ~ 사고 순간, 0.5초 간격 5장면)


def _load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def run(case_dir, video, model_path=None):
    model_path = model_path or MODEL
    part = _load(os.path.join(case_dir, "bb_partner.json"))
    out = {"label": None, "confidence": None, "guess": True, "scores": None, "frames": 0, "reason": None,
           "model": os.path.basename(model_path)}
    imp = part["impact_frame"]
    if imp is None:
        segs = _load(os.path.join(case_dir, "ego_motion.json"))["summary"].get("segments") or []
        imp = segs[-1]["to"] if segs else 0
    if not os.path.exists(model_path):
        out["reason"] = "model_missing"
    else:
        import cv2
        from ultralytics import YOLO
        from src.blackbox.video_lib import scene_crosswalk as sc
        cap = cv2.VideoCapture(video)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        t_imp = imp / fps
        frames, t = [], max(t_imp - WINDOW_S, 0.0)
        while t <= t_imp + 1e-6 and int(t * fps) < total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, img = cap.read()
            if ok:
                frames.append((t, img))
            t += sc.SCENE_STEP
        cap.release()
        facts = sc.classify_scene(YOLO(model_path), frames, t_imp)
        if facts:
            f = next(iter(facts.values()))
            out.update(label=f.hints["scene"], confidence=round(f.confidence, 3), guess=bool(f.guess),
                       scores=f.hints["scores"], frames=f.hints["frames"])
        else:
            out["reason"] = "no_frames_or_unsupported_place"
    with open(os.path.join(case_dir, "bb_scene.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    r = run(sys.argv[1], sys.argv[2])
    print(r["label"], r["confidence"], r["reason"])
