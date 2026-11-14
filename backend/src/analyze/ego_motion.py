"""촬영 차(블랙박스)의 움직임 추정 (영상 → ego_motion.json)

  python src/analyze/ego_motion.py <영상> <결과 폴더>

배경의 특징점을 프레임마다 따라가 화면 전체가 어떻게 움직였는지(이동·회전·확대)를 구한다.
차량·사람 상자 안의 점은 빼서(결과 폴더에 tracks.json이 있으면) 다른 차의 움직임이 섞이지 않게 한다.

프레임마다 기록하는 값 (영상 너비 480 픽셀로 줄인 기준):
  mag    배경 점들이 움직인 거리의 중앙값 (px). 촬영 차가 빨리 갈수록 큼. 속도의 대리 지표라서 단위는 m/s가 아님
  tx     화면 가로 이동 (px). 오른쪽으로 꺾으면 장면이 왼쪽으로 흘러 음수. 회전(yaw)의 대리 지표
  ty     화면 세로 이동 (px). 급제동·충격 때 크게 튐
  scale  확대 비율 - 1. 앞으로 갈 때 양수
  ok     점이 충분해 믿을 만한 프레임인지

요약(summary): 달리는지·멈췄는지 구간, 충격 후보 프레임, 좌우로 꺾은 정도.
임계값은 영상 몇 개로 정한 값이라 검증이 더 필요하다.
"""
import json
import os
import sys

import cv2
import numpy as np

WIDTH = 480               # 분석용 너비
CROP_BOTTOM = 0.18        # 아래쪽(차 보닛·대시보드)은 점을 안 뽑음
CROP_TOP = 0.10           # 위쪽(하늘·시간 표시)도 뺌
MAX_PTS = 300
MIN_PTS = 25              # 이보다 적으면 믿지 않음
MOVE_MAG = 0.6            # 이보다 크면 달리는 중 (px/프레임, 너비 480 기준)
MIN_SEG = 10               # 이보다 짧은 달림/멈춤 구간은 앞 구간에 합침 (신호 대기 중 잠깐 흔들림 같은 잡음)
SMOOTH = 5                # 움직임 판정 평활 창 (프레임)
JOLT_MIN = 6.0            # 충격 후보: ty 또는 tx가 이보다 크게 튐 (px)
JOLT_RATIO = 4.0          # 그리고 평소(중앙값 절대값) 움직임의 이 배수 이상


def boxes_by_frame(out_dir):
    path = os.path.join(out_dir, "tracks.json")
    by = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fp:
            for recs in json.load(fp)["tracks"].values():
                for r in recs:
                    if r["cls"] in ("car", "truck", "bus", "motorcycle", "bicycle", "person"):
                        by.setdefault(r["frame"], []).append(r["bbox"])
    return by


def smooth(a, k):
    a = np.asarray(a, float)
    if len(a) < k:
        return a
    pad = np.pad(a, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def run(video, out_dir):
    boxes = boxes_by_frame(out_dir)
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    rows, prev, prev_pts, f = [], None, None, 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        sc = WIDTH / img.shape[1]
        g = cv2.cvtColor(cv2.resize(img, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        H, W = g.shape
        row = {"frame": f, "mag": None, "tx": None, "ty": None, "scale": None, "n": 0, "ok": False}
        if prev is not None:
            mask = np.zeros_like(g)
            mask[int(H * CROP_TOP): int(H * (1 - CROP_BOTTOM)), :] = 255
            for x, y, w, h in boxes.get(f - 1, []):      # 이전 프레임의 상자 안 점은 뺌 (조금 넓혀서)
                x1, y1 = int(max(0, (x - 0.02) * W)), int(max(0, (y - 0.02) * H))
                x2, y2 = int(min(W, (x + w + 0.02) * W)), int(min(H, (y + h + 0.02) * H))
                mask[y1:y2, x1:x2] = 0
            p0 = cv2.goodFeaturesToTrack(prev, MAX_PTS, 0.01, 6, mask=mask)
            if p0 is not None and len(p0) >= MIN_PTS:
                p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, g, p0, None, winSize=(21, 21), maxLevel=3)
                st = st.reshape(-1).astype(bool)
                a, b = p0.reshape(-1, 2)[st], p1.reshape(-1, 2)[st]
                row["n"] = int(len(a))
                if len(a) >= MIN_PTS:
                    M, inl = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=2.0)
                    if M is not None:
                        s = float(np.hypot(M[0, 0], M[1, 0]))
                        row.update(mag=round(float(np.median(np.hypot(*(b - a).T))), 3),
                                   tx=round(float(M[0, 2] + (M[0, 0] - 1) * W / 2), 3),   # 화면 가운데 기준 가로 이동
                                   ty=round(float(M[1, 2] + (M[1, 1] - 1) * H / 2), 3),
                                   scale=round(s - 1, 5), ok=True)
        rows.append(row)
        prev = g
        f += 1
    cap.release()

    good = [r for r in rows if r["ok"]]
    mag = np.array([r["mag"] if r["ok"] else np.nan for r in rows], float)
    # 믿을 수 없는 프레임은 앞뒤 값으로 메워 평활
    idx = np.arange(len(mag)); m = ~np.isnan(mag)
    filled = np.interp(idx, idx[m], mag[m]) if m.any() else np.zeros(len(mag))
    sm = smooth(filled, SMOOTH)
    moving = sm > MOVE_MAG
    # 요약
    moving = moving.copy()
    for _ in range(3):   # 짧은 구간을 앞 구간 상태로 덮어쓰기 (맨 앞 구간은 뒤 구간 상태로)
        start = 0
        for i in range(1, len(moving) + 1):
            if i == len(moving) or moving[i] != moving[start]:
                if i - start < MIN_SEG and len(moving) > MIN_SEG:
                    moving[start:i] = moving[start - 1] if start > 0 else (moving[i] if i < len(moving) else moving[start])
                start = i
    segs, start = [], 0
    for i in range(1, len(moving) + 1):
        if i == len(moving) or moving[i] != moving[start]:
            segs.append({"state": "moving" if moving[start] else "stopped", "from": start, "to": i - 1})
            start = i
    txs = np.array([r["tx"] if r["ok"] else 0.0 for r in rows]); tys = np.array([r["ty"] if r["ok"] else 0.0 for r in rows])
    base = max(float(np.median(np.abs(np.concatenate([txs, tys])))), 0.3)
    jolt = np.maximum(np.abs(txs), np.abs(tys))
    cand = [int(i) for i in np.argsort(-jolt)[:3] if jolt[i] >= JOLT_MIN and jolt[i] >= JOLT_RATIO * base]
    summary = {"frames": len(rows), "fps": fps, "ok_frames": len(good),
               "moving_ratio": round(float(moving.mean()), 3) if len(moving) else None,
               "segments": segs,
               "jolt_frames": sorted(cand),
               "yaw_total_px": round(float(np.sum(txs)), 1),
               "ends_moving": bool(moving[-1]) if len(moving) else None}
    out = {"params": {"width": WIDTH, "move_mag": MOVE_MAG, "smooth": SMOOTH, "jolt_min": JOLT_MIN, "jolt_ratio": JOLT_RATIO},
           "summary": summary, "frames": rows}
    path = os.path.join(out_dir, "ego_motion.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    return out


if __name__ == "__main__":
    r = run(sys.argv[1], sys.argv[2])
    s = r["summary"]
    print(f"프레임 {s['frames']} (믿을 만한 {s['ok_frames']}), 달린 비율 {s['moving_ratio']}, 구간 "
          + " ".join(f"{g['state'][0]}{g['from']}-{g['to']}" for g in s["segments"]) + f", 충격 후보 {s['jolt_frames']}")
