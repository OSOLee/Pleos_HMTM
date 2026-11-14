"""블랙박스 영상의 신호등 추정 (tracks.json → bb_signal.json)

  python src/analyze/bb_signal.py <영상> <결과 폴더>

블랙박스의 신호등 탐지는 정확도가 낮아서(yolov8s로 37%) 확정에 쓰지 않는다. 대신 사용자에게
"신호등이 있었나요? / 앞 신호는 무슨 색이었나요?"를 묻고, 탐지가 본 값을 미리 골라 둔다 (model_guess).
추정이 틀려도 사용자가 바꾸면 되므로, 모르면 None(미리 고르지 않음)으로 둔다.

질문 필드 이름은 임시다 (B의 facts 규격이 정해지면 맞춘다):
  road.signal_present   신호등이 있었는지 (CCTV와 같은 이름)
  ego.signal_color      촬영 차 앞의 신호 색
"""
import json
import os
import sys
from collections import Counter

import cv2
import numpy as np

sys.path.insert(0, os.getcwd())
from src.analyze import light_cnn

MIN_DETS = 5          # 신호등 궤적으로 칠 최소 탐지 수 (한두 번 스친 오탐을 뺌)
MIN_CONF = 0.25       # 궤적의 탐지 신뢰도 중앙값이 이보다 낮으면 뺌
MIN_W = 10            # 색을 볼 수 있는 상자 최소 너비 (픽셀)
STEP = 2              # 몇 프레임마다 색을 볼지
PAD = 0.15            # 상자를 넓혀 자름 (light_cnn 학습 때와 같게)
MAIN_N = 3            # 색을 보는 후보 수 (크기·길이가 큰 순)
COLOR_MIN_SHARE = 0.6  # 이 비율 이상 같은 색이어야 색을 미리 고름
# 색 추정은 미리 고르지 않는다. 블랙박스 영상 30개 검증에서 정답과 같은 비율이 30%(미리 고른 23개 중 9개)로,
# 늘 "초록"이라 답하는 것(63%)보다 낮았다. 한 화면에 다른 방향 신호등이 같이 잡히고 색 판독기도 약해서다.
# 판독 결과는 질문 참고(light_hints)로만 붙인다. 정확도가 오르면 True로.
GUESS_COLOR = False
COLORS = {"red": "빨강", "green": "초록", "etc": "노랑 또는 꺼짐·모름"}


def candidates(tracks):
    """신호등 궤적 중 믿을 만한 것: [(점수, 궤적 id, 기록 목록)] 큰 순"""
    out = []
    for tid, recs in tracks.items():
        if not recs or recs[0]["cls"] != "traffic light":
            continue
        real = [r for r in recs if not r.get("filled")]
        if len(real) < MIN_DETS:
            continue
        conf = float(np.median([r["conf"] for r in real if r["conf"] is not None]))
        if conf < MIN_CONF:
            continue
        area = float(np.median([r["bbox"][2] * r["bbox"][3] for r in real]))
        out.append((area * len(real), tid, real, conf, area))
    return sorted(out, key=lambda c: -c[0])


def run(video, out_dir):
    with open(os.path.join(out_dir, "tracks.json"), encoding="utf-8") as fp:
        tracks = json.load(fp)["tracks"]
    cands = candidates(tracks)[:MAIN_N]
    cap = cv2.VideoCapture(video)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)); W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    want = {}
    for _, tid, recs, _, _ in cands:
        for r in recs[::STEP]:
            want.setdefault(r["frame"], []).append((tid, r["bbox"]))
    states = {tid: [] for _, tid, *_ in cands}
    if want and os.path.exists(light_cnn.MODEL):
        frame_no = 0
        last = max(want)
        while frame_no <= last:      # 이 영상들은 seek이 안 되어 처음부터 읽는다
            ok, img = cap.read()
            if not ok:
                break
            for tid, (x, y, w, h) in want.get(frame_no, []):
                if w * W < MIN_W:
                    continue
                x1, y1 = int(max(0, (x - w * PAD) * W)), int(max(0, (y - h * PAD) * H))
                x2, y2 = int(min(W, (x + w * (1 + PAD)) * W)), int(min(H, (y + h * (1 + PAD)) * H))
                color, p = light_cnn.classify(img[y1:y2, x1:x2])
                states[tid].append({"frame": frame_no, "color": color, "p": round(float(p), 3)})
            frame_no += 1
    cap.release()

    # 가장 두드러진(크고 오래 보인) 후보의 색을 대표로 쓴다
    guess_color, share, main = None, None, None
    for _, tid, recs, conf, area in cands:
        reads = [s["color"] for s in states[tid]]
        if len(reads) >= 3:
            c, n = Counter(reads).most_common(1)[0]
            main = tid
            share = n / len(reads)
            if GUESS_COLOR and share >= COLOR_MIN_SHARE:
                guess_color = c
            break
    questions = [
        {"field": "road.signal_present", "question": "영상에 신호등이 있었나요?", "answer_type": "choice",
         "options": [True, False], "choices": ["있어요", "없어요"], "model_guess": bool(cands)},
        {"field": "ego.signal_color", "question": "촬영 차 앞 신호등은 무슨 색이었나요?", "answer_type": "choice",
         "options": ["red", "green", "etc", "unknown"], "choices": ["빨강", "초록", "노랑 또는 꺼짐", "모르겠어요"],
         "model_guess": guess_color, "depends_on": {"road.signal_present": True},
         "light_hints": {str(t): states[t][:30] for t in states}},
    ]
    out = {"params": {"min_dets": MIN_DETS, "min_conf": MIN_CONF, "step": STEP, "color_min_share": COLOR_MIN_SHARE},
           "candidates": [{"id": tid, "dets": len(recs), "conf": round(conf, 3), "area": round(area, 5)}
                          for _, tid, recs, conf, area in cands],
           "main": main, "color_share": share, "questions": questions}
    path = os.path.join(out_dir, "bb_signal.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    r = run(sys.argv[1], sys.argv[2])
    print(f"신호등 후보 {len(r['candidates'])}개, 유무 추정 {r['questions'][0]['model_guess']}, "
          f"색 추정 {r['questions'][1]['model_guess']} (같은 색 비율 {r['color_share']})")
