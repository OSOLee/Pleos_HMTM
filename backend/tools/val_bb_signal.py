"""블랙박스 신호등 추정(bb_signal)이 프레임 정답과 얼마나 맞는지 잰다.
정답 = 프레임 라벨의 traffic-light-red/green/etc 상자. 영상별로 '있음/없음'과 '많이 나온 색'을 정답으로 본다.
(라벨에 신호등이 없어도 영상엔 있을 수 있어서 '없음' 정답은 약한 기준이다)
사용: .venv/bin/python val_bb_signal.py <결과 폴더> [영상 수]"""
import glob
import json
import os
import random
import sys
import time
from collections import Counter

os.environ["MTM_DETECTOR"] = "models/yolov8s.pt"   # 보조 모델(yolov8s)의 신호등 탐지와 같음
os.environ["MTM_IMGSZ"] = "640"
os.environ.pop("MTM_HELPER_DETECTOR", None)
sys.path.insert(0, os.getcwd())
from src.analyze import bb_signal, track_video  # noqa: E402

OUT = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 40
ROOT = "data/aihub/bb_frame_labels"
os.makedirs(OUT, exist_ok=True)

gt = {}
for d in sorted(glob.glob(f"{ROOT}/*")):
    v = os.path.basename(d)
    if not os.path.exists(f"data/videos/bb/{v}.mp4"):
        continue
    c = Counter()
    for f in glob.glob(f"{d}/*.json"):
        for o in json.load(open(f, encoding="utf-8"))["objects"]:
            if o["category"].startswith("traffic-light"):
                c[o["category"].split("-")[-1]] += 1
    gt[v] = c
with_light = [v for v in gt if sum(gt[v].values()) >= 3]
without = [v for v in gt if sum(gt[v].values()) == 0]
rnd = random.Random(7)
rnd.shuffle(with_light); rnd.shuffle(without)
pick = with_light[: N * 3 // 4] + without[: N // 4]
print(f"정답 있는 영상 {len(with_light)}개, 없는 영상 {len(without)}개 중 {len(pick)}개 시험", flush=True)

rows = []
for i, v in enumerate(pick):
    t0 = time.time()
    d = f"{OUT}/{v}"
    track_video.run(f"data/videos/bb/{v}.mp4", d, scene_cut=False)
    r = bb_signal.run(f"data/videos/bb/{v}.mp4", d)
    g = gt[v]
    g_present = sum(g.values()) >= 3
    g_color = g.most_common(1)[0][0] if g_present else None
    q = r["questions"]
    row = {"video": v, "gt_present": g_present, "gt_color": g_color, "gt_counts": dict(g),
           "guess_present": q[0]["model_guess"], "guess_color": q[1]["model_guess"], "color_share": r["color_share"],
           "cands": len(r["candidates"]), "sec": round(time.time() - t0)}
    rows.append(row)
    json.dump(rows, open(f"{OUT}/val_rows.json", "w"), ensure_ascii=False, indent=1)
    print(f"VID {i + 1}/{len(pick)} {v} 정답 {g_present}/{g_color} 추정 {row['guess_present']}/{row['guess_color']}", flush=True)

pw = [r for r in rows if r["gt_present"]]
pn = [r for r in rows if not r["gt_present"]]
res = {"videos": len(rows),
       "present_when_gt_present": [sum(r["guess_present"] for r in pw), len(pw)],
       "present_when_gt_absent": [sum(r["guess_present"] for r in pn), len(pn)],
       "color_asked_given_present": [sum(r["guess_color"] is not None for r in pw), len(pw)],
       "color_right": [sum(r["guess_color"] == r["gt_color"] for r in pw), len(pw)],
       "color_right_among_guessed": [sum(r["guess_color"] == r["gt_color"] for r in pw if r["guess_color"]),
                                     sum(r["guess_color"] is not None for r in pw)],
       "gt_color_dist": dict(Counter(r["gt_color"] for r in pw))}
json.dump(res, open(f"{OUT}/val_result.json", "w"), ensure_ascii=False, indent=1)
print("RESULT", json.dumps(res, ensure_ascii=False), flush=True)
