import argparse
import cv2
import json
import numpy as np

COLORS = {"road": (0, 200, 0), "parking_left": (255, 128, 0),
          "roadside_right": (255, 0, 255), "side_entry_left": (0, 255, 255),
          # 네 모서리로 만든 교차로 장면 (make_scene): 교차로는 노랑, 진입로는 방위마다 다른 색
          "intersection": (0, 255, 255), "appr_n": (0, 0, 255), "appr_e": (0, 200, 0),
          "appr_s": (255, 128, 0), "appr_w": (255, 0, 255)}

def to_px(pts, w, h):
    return np.array([[int(x * w), int(y * h)] for x, y in pts], np.int32)

def run(video, scene_path, out_path="outputs/scene_check.jpg"):
    with open(scene_path, encoding="utf-8") as f:
        scene = json.load(f)

    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, scene["frame_ref"])
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"프레임을 읽지 못했음: {video}")
    h, w = frame.shape[:2]

    overlay = frame.copy()
    for z in scene["zones"]:
        cv2.fillPoly(overlay, [to_px(z["polygon"], w, h)], COLORS.get(z["id"], (200, 200, 200)))
    frame = cv2.addWeighted(overlay, 0.35, frame, 0.65, 0)   # 칠한 이미지 35% + 원본 65%
    for z in scene["zones"]:                            # 영역 경계: 같은 색 테두리
        cv2.polylines(frame, [to_px(z["polygon"], w, h)], True, COLORS.get(z["id"], (200, 200, 200)), 3)

    cv2.polylines(frame, [to_px(scene["roi"], w, h)], True, (255, 255, 255), 2)      # 분석 영역: 흰 테두리
    for ln in scene["lines"]:
        cv2.polylines(frame, [to_px(ln["points"], w, h)], False, (0, 0, 255), 4)      # 선: 빨강

    for z in scene["zones"]:                            # 영역 이름을 꼭짓점 평균 위치에 표시
        cx = int(np.mean([p[0] for p in z["polygon"]]) * w)
        cy = int(np.mean([p[1] for p in z["polygon"]]) * h)
        cv2.putText(frame, z["id"], (cx - 60, cy), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5)
        cv2.putText(frame, z["id"], (cx - 60, cy), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    cv2.imwrite(out_path, frame)
    print(f"저장: {out_path}")
    return out_path

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="scene.json 영역을 기준 프레임에 겹쳐 그리기")
    ap.add_argument("--video", default="data/videos/sample.mp4")
    ap.add_argument("--scene", default="scenes/sample.json")
    ap.add_argument("--out", default="outputs/scene_check.jpg")
    args = ap.parse_args()
    run(args.video, args.scene, args.out)