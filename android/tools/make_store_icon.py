r"""스토어 제출용 앱 아이콘 512x512 PNG (Pleos 앱 제출 가이드: PNG/JPEG, 1MB 이하, 512x512)

  backend\.venv\Scripts\python android\tools\make_store_icon.py docs\images\app_icon_512.png [--dark]

res/drawable/ic_launcher_*.xml(108dp)과 같은 도형을 OpenCV로 그린다 (모서리 둥근 정사각형 안, 바탕 전체).
"""
import argparse

import cv2
import numpy as np

LIGHT = dict(bg="#0064FF", body="#FFFFFF", lens="#0064FF", ego="#FFFFFF", other="#99C1FF", rec="#FF4D4F")
DARK = dict(bg="#1D1E21", body="#0082FF", lens="#1D1E21", ego="#FFFFFF", other="#5A5C63", rec="#FF6B6D")


def bgr(h):
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def draw(colors, size=512, ss=4):
    n = size * ss
    k = n / 108.0                      # 108dp 캔버스 → 픽셀
    p = lambda v: int(round(v * k))
    img = np.zeros((n, n, 3), np.uint8)
    img[:] = bgr(colors["bg"])
    # 몸체 (모서리 6)
    x0, y0, x1, y1, r = p(24), p(36), p(84), p(72), p(6)
    body = bgr(colors["body"])
    cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), body, -1)
    cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), body, -1)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        cv2.circle(img, (cx, cy), r, body, -1, cv2.LINE_AA)
    c = (p(54), p(54))
    cv2.circle(img, c, p(14), bgr(colors["lens"]), -1, cv2.LINE_AA)
    cv2.circle(img, c, p(10), bgr(colors["other"]), -1, cv2.LINE_AA)
    # 내 차 60%: 12시부터 시계 방향 216도 (OpenCV 각도는 3시 기준 시계 방향)
    cv2.ellipse(img, c, (p(10), p(10)), 0, -90, -90 + 216, bgr(colors["ego"]), -1, cv2.LINE_AA)
    cv2.circle(img, (p(76), p(43)), p(3), bgr(colors["rec"]), -1, cv2.LINE_AA)
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--dark", action="store_true")
    a = ap.parse_args()
    cv2.imwrite(a.out, draw(DARK if a.dark else LIGHT))
    print("저장", a.out)


if __name__ == "__main__":
    main()
