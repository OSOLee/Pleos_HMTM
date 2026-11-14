"""블랙박스 시험 공통: 짧은 시험 영상을 OpenCV로 만든다 (영상 파일은 저장소에 두지 않음)"""
import os

import numpy as np


def make_video(path, seconds=6.0, fps=5.0, size=(64, 48)):
    """seconds초짜리 작은 mp4 (프레임마다 밝기가 바뀌는 회색 화면). 경로를 돌려줌"""
    import cv2
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not w.isOpened():
        raise RuntimeError("시험 영상을 만들지 못했어요 (OpenCV mp4v)")
    n = int(round(seconds * fps))
    for i in range(n):
        frame = np.full((size[1], size[0], 3), (i * 7) % 255, dtype=np.uint8)
        w.write(frame)
    w.release()
    return path
