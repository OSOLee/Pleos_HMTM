"""같은 사고의 복사본 영상에 기준 영상의 교차로 모서리를 옮긴다 (일관성 측정용)

  python tools/evaluate/map_corners.py <기준 영상> <복사본 영상>   # → scenes/cc_<복사본 날짜>_corners.json

복사본은 색을 바꾸거나, 줄이고 검은 테두리를 붙이거나, 어안 효과를 넣은 것이다. 두 영상의 배경(프레임 중앙값)에서
ORB 특징점을 맞추고 RANSAC으로 호모그래피를 구해 네 모서리를 옮긴다. 색이 바뀐 복사본도 맞도록 흑백 + 대비
평탄화(CLAHE)를 쓴다. 맞은 점이 MIN_INLIERS보다 적으면 실패로 보고 저장하지 않는다.
어안 효과처럼 휘어진 복사본은 호모그래피로 정확히 옮길 수 없다. 결과 그림을 꼭 눈으로 확인할 것.
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.getcwd())
from src.make_scene import build_scene

BG_FRAMES = 15
MIN_INLIERS = 25


def background(video):
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    imgs = []
    for k in range(BG_FRAMES):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(k * (n - 1) / (BG_FRAMES - 1)))
        ok, img = cap.read()
        if ok:
            imgs.append(img)
    cap.release()
    bg = np.median(np.stack(imgs), axis=0).astype(np.uint8)
    gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def run(ref, copy):
    """반환: (저장 경로, 맞은 점 수). 실패하면 (None, 맞은 점 수)"""
    ra, rb = background(f"data/videos/cc/{ref}.mp4"), background(f"data/videos/cc/{copy}.mp4")
    orb = cv2.ORB_create(4000)
    ka, da = orb.detectAndCompute(ra, None)
    kb, db = orb.detectAndCompute(rb, None)
    if da is None or db is None:
        return None, 0
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < MIN_INLIERS:
        return None, len(good)
    src = np.float32([ka[m.queryIdx].pt for m in good])
    dst = np.float32([kb[m.trainIdx].pt for m in good])
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inl = int(mask.sum()) if mask is not None else 0
    if H is None or inl < MIN_INLIERS:
        return None, inl

    with open(f"scenes/cc_{ref.split('_')[2]}_corners.json", encoding="utf-8") as f:
        scene = json.load(f)
    (ha, wa), (hb, wb) = ra.shape, rb.shape
    pts = np.float32([[x * wa, y * ha] for x, y in scene["corners"]]).reshape(-1, 1, 2)
    moved = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
    corners = [(min(max(float(x) / wb, 0.0), 1.0), min(max(float(y) / hb, 0.0), 1.0)) for x, y in moved]
    out = build_scene(corners, f"data/videos/cc/{copy}.mp4", closed=scene.get("closed_side"))
    out["mapped_from"] = {"video": ref, "inliers": inl}
    path = f"scenes/cc_{copy.split('_')[2]}_corners.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return path, inl


if __name__ == "__main__":
    p, n = run(sys.argv[1], sys.argv[2])
    print(f"{'저장: ' + p if p else '실패'} (맞은 점 {n})")
