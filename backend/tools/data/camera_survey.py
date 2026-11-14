"""블랙박스·CCTV 영상 전체에 카메라 판단(camera_check + stabilize.check)을 돌려 앱이 어떻게 처리하는지 센다

  python tools/data/camera_survey.py data/videos/bb_lights data/videos/cc > outputs/카메라판단.md

사용자가 홈 화면에서 "CCTV"를 골랐다고 보고 안전장치가 어떻게 처리하는지 본다 (블랙박스를 고르면 바로 unsupported).
앱 처리(run_app.py와 같은 순서):
  cctv / unknown       → 보정 없이 고정 CCTV로 분석
  blackbox + 보정 가능 → 흔들리는 CCTV로 보고 보정해서 분석
  blackbox + 보정 불가 → unsupported (블랙박스 안내)
폴더 이름 앞부분(bb_ / cc_)을 정답으로 본다. 영상별 숫자는 outputs/camera_survey.json
"""
import glob
import json
import os
import sys
from multiprocessing import Pool

import cv2
import numpy as np

sys.path.insert(0, os.getcwd())
from src.analyze import camera_check, stabilize


def flows_of(video):
    cap = cv2.VideoCapture(video)
    flows, prev, f = [], None, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if f % camera_check.STEP == 0:
            gray = cv2.cvtColor(cv2.resize(frame, camera_check.SIZE), cv2.COLOR_BGR2GRAY)
            if prev is not None:
                flows.append(camera_check.background_flow(prev, gray))
            prev = gray
        f += 1
    cap.release()
    return flows


def judge(video):
    flows = flows_of(video)
    if not flows:
        return {"video": video, "error": "읽지 못함"}
    cam = camera_check.decide(flows)
    out = {"video": video, "truth": os.path.basename(video)[:2], "camera": cam,
           "flow_median": round(float(np.median(flows)), 3), "move_run": camera_check.longest_run(flows)}
    if cam == "blackbox":
        ok, med = stabilize.check(video)
        out["inliers"] = med
        out["app"] = "보정해서 분석" if ok else "unsupported"
    else:
        out["app"] = "고정 CCTV로 분석"
    return out


if __name__ == "__main__":
    videos = sorted(v for d in sys.argv[1:] for v in glob.glob(os.path.join(d, "*.mp4")))
    with Pool(max(1, (os.cpu_count() or 2) - 1)) as p:
        rows = p.map(judge, videos)
    with open("outputs/camera_survey.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    apps = ["고정 CCTV로 분석", "보정해서 분석", "unsupported"]
    print("# 카메라 판단 전체 확인\n")
    print("사용자가 CCTV를 골랐을 때 안전장치(camera_check + stabilize.check)가 어떻게 처리하는지. "
          "블랙박스를 CCTV로 잘못 골랐을 때 얼마나 막는지와, 진짜 CCTV를 막지 않는지를 본다.\n")
    print("| 실제 | 영상 수 | " + " | ".join(apps) + " |")
    print("|---|---|" + "---|" * len(apps))
    for t, name in (("bb", "블랙박스"), ("cc", "CCTV")):
        rs = [r for r in rows if r.get("truth") == t]
        print(f"| {name} | {len(rs)} | " + " | ".join(str(sum(r['app'] == a for r in rs)) for a in apps) + " |")
    print()
    for t, a, title in (("bb", "고정 CCTV로 분석", "블랙박스인데 고정 CCTV로 분석"),
                        ("bb", "보정해서 분석", "블랙박스인데 흔들리는 CCTV로 보정"),
                        ("cc", "unsupported", "CCTV인데 블랙박스로 막힘")):
        bad = [r for r in rows if r.get("truth") == t and r.get("app") == a]
        print(f"## {title} ({len(bad)}개)\n")
        for r in bad:
            print(f"- {os.path.basename(r['video'])} | 판단 {r['camera']} | 흐름 중앙값 {r['flow_median']} | "
                  f"연속 이동 {r['move_run']} | 맞는 점 {r.get('inliers', '-')}")
        print()
    errs = [r for r in rows if "error" in r]
    if errs:
        print("## 읽지 못한 영상\n")
        for r in errs:
            print("-", r["video"])
