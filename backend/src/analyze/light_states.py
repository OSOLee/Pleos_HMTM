"""신호등 궤적마다 프레임별 색을 기록한다 (tracks_final.json → lights.json)

  python src/analyze/light_states.py <영상> [결과 폴더]

색은 src/analyze/light_cnn.py의 작은 CNN으로 본다 (red / green / etc, etc는 노랑·꺼짐·뒷면 등 나머지).
정확도가 확정에 쓸 만큼 높지 않아서(시험 0.70) facts에서는 질문의 참고 정보로만 쓴다.
모델 파일(models/light_cnn.pt)이 없으면 색 없이 빈 기록을 남긴다.
"""
import json
import os
import sys

import cv2

sys.path.insert(0, os.getcwd())
from src.analyze import light_cnn

STEP = 3        # 몇 프레임마다 색을 볼지
PAD = 0.15      # 박스를 이만큼 넓혀 자름 (학습 데이터와 같게)
MIN_W = 10      # 이보다 좁은 박스는 색을 볼 수 없음 (픽셀)


def state_at(states, f):
    """f에 가장 가까운 기록 (없으면 None)"""
    return min(states, key=lambda s: abs(s["frame"] - f)) if states else None


def run(video, out_dir="outputs"):
    with open(os.path.join(out_dir, "tracks_final.json"), encoding="utf-8") as fp:
        tracks = json.load(fp)["tracks"]
    lights = {t: tr for t, tr in tracks.items() if tr["cls"] == "traffic_light"}
    want = {}   # 프레임 -> [(궤적, 박스)]
    for t, tr in lights.items():
        for r in tr["frames"][::STEP]:
            want.setdefault(r["frame"], []).append((t, r["bbox"]))

    states = {t: [] for t in lights}
    if want and os.path.exists(light_cnn.MODEL):
        cap = cv2.VideoCapture(video)
        for f in sorted(want):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, img = cap.read()
            if not ok:
                continue
            H, W = img.shape[:2]
            for t, (x, y, w, h) in want[f]:
                if w * W < MIN_W:
                    continue
                x1, y1 = int(max(0, (x - w * PAD) * W)), int(max(0, (y - h * PAD) * H))
                x2, y2 = int(min(W, (x + w * (1 + PAD)) * W)), int(min(H, (y + h * (1 + PAD)) * H))
                color, p = light_cnn.classify(img[y1:y2, x1:x2])
                states[t].append({"frame": f, "color": color, "p": p})
        cap.release()

    out = {"model": light_cnn.MODEL if os.path.exists(light_cnn.MODEL) else None,
           "params": {"step": STEP, "pad": PAD, "min_w": MIN_W}, "lights": states}
    path = os.path.join(out_dir, "lights.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    for t, s in states.items():
        print(f"신호등 {t}: " + " ".join(f"{x['frame']}:{x['color'][0]}" for x in s[:20]) + (" ..." if len(s) > 20 else ""))
    print(f"저장: {path}")
    return path


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "outputs")
