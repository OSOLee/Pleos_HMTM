"""블랙박스 영상 탐지·추적 (1단계). 주 모델(블랙박스 학습)은 차량·이륜차, yolov8s는 사람·자전거·신호등을 맡는다.
사용: .venv/bin/python tools/blackbox_tracks.py <영상> [결과 폴더] [--video]
  --video: 상자를 그린 영상(tracked.mp4)도 저장
화면 전환 감지는 끈다 (블랙박스는 카메라가 움직여 장면이 계속 바뀜)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 저장소 루트 (src를 찾으려고)

# track_video가 import 때 환경변수를 읽으므로 먼저 정한다. 이미 정해 둔 값이 있으면 그것을 씀
os.environ.setdefault("MTM_DETECTOR", "models/bb_v1.pt")
os.environ.setdefault("MTM_IMGSZ", "640")
os.environ.setdefault("MTM_HELPER_DETECTOR", "models/yolov8s.pt")
os.environ.setdefault("MTM_HELPER_CLASSES", "person,bicycle,traffic light")

from src.analyze import track_video  # noqa: E402

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    video = args[0]
    out = args[1] if len(args) > 1 else os.path.join("outputs", "bb", os.path.splitext(os.path.basename(video))[0])
    track_video.run(video, out, save_video="--video" in sys.argv, scene_cut=False)
