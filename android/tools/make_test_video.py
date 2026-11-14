r"""시험용 블랙박스 영상 만들기 (화면에 경과 초를 찍은 회색 영상). backend 가상환경의 OpenCV를 쓴다

  backend\.venv\Scripts\python android\tools\make_test_video.py 20261109_143012_F.mp4 --seconds 30

파일 이름의 YYYYMMDD_HHMMSS가 촬영 시작 시각 후보가 된다 (docs/design-blackbox.md 5.2).
콘솔로 주행 기록을 만들 때 이 시각에 맞춰 만든다 (docs/SETUP.md 5절 "수동으로 확인하는 방법").
"""
import argparse

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--fps", type=int, default=10)
    a = p.parse_args()
    w, h = 320, 180
    vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (w, h))
    for i in range(int(a.seconds * a.fps)):
        img = np.full((h, w, 3), 40, np.uint8)
        cv2.putText(img, f"t={i / a.fps:5.1f}s", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        vw.write(img)
    vw.release()
    print(f"완료: {a.out} ({a.seconds}초, {a.fps}fps)")


if __name__ == "__main__":
    main()
