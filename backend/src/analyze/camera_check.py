import os
import sys
import json
import cv2
import numpy as np

STEP = 5           # 몇 프레임 간격으로 비교할지
SIZE = (320, 180)  # 흐름 계산용으로 줄인 크기
FLOW_MIN = 0.5     # 배경 흐름 중앙값(픽셀)이 이보다 크면 그 구간은 카메라가 움직인 것
MOVE_RUN = 3       # 움직인 구간 비율이 이만큼 연속되면 이동 카메라 (blackbox)
FIXED_MAX = 0.3  # 모든 구간이 이보다 작으면 고정 카메라 (cctv), 사이는 unknown

def background_flow(prev, cur):
    flow = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 3, 15, 3,  5, 1.2, 0)
    mag = np.linalg.norm(flow, axis=2)
    return float(np.median(mag))

def longest_run(flows):
    best = run = 0
    for f in flows:
        run = run + 1 if f > FLOW_MIN else 0
        best = max(best, run)
    return best

def decide(flows):
    if longest_run(flows) >= MOVE_RUN:
        return "blackbox"
    if max(flows) <= FIXED_MAX:
        return "cctv"
    return "unknown"

def run(video, out_dir="outputs"):
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "camera.json")

    cap = cv2.VideoCapture(video)
    flows, prev, frame_no = [], None, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_no % STEP == 0:
            gray = cv2.cvtColor(cv2.resize(frame, SIZE), cv2.COLOR_BGR2GRAY)
            if prev is not None:
                flows.append(round(background_flow(prev, gray), 3))
            prev = gray
        frame_no += 1
    cap.release()

    if not flows:
        raise SystemExit(f"영상을 읽지 못했음: {video}")

    run_len = longest_run(flows)
    camera_type = decide(flows)

    print(f"=== 영상 종류: {os.path.basename(video)} ===")
    print(f"비교 구간 {len(flows)}개 | 흐름 중앙값 {np.median(flows):.3f} | 최대 {max(flows):.3f}")
    print(f"최장 연속 이동 {run_len} 구간 -> {camera_type}")
    print("구간별 흐름", flows)

    out = {
        "schema_version": "0.2",
        "video": video,
        "camera_type": camera_type,
        "longest_move_run": run_len,
        "flow_median": round(float(np.median(flows)), 3),
        "flow_max": max(flows),
        "params": {"step": STEP, "size": SIZE, "flow_min": FLOW_MIN,
                   "move_run": MOVE_RUN, "fixed_max": FIXED_MAX},
        "flows": flows,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"저장: {out_path}")
    return out_path

if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else "data/videos/sample.mp4"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "outputs"
    run(video, out_dir)