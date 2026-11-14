"""같은 사고를 담은 영상(색·크기·검은 테두리만 바뀐 복사본, 앞뒤를 자른 복사본)을 찾는다

두 가지로 본다. 하나라도 걸리면 후보다.
- 장면 지문: 0.5초 간격 프레임의 작은 흑백 지문(dHash)이 얼마나 겹치는지. 그대로 복사한 영상에 강하다
- 움직임 곡선: 프레임 사이 밝기 변화량을 시간 순으로 늘어놓은 곡선의 상관. 색을 바꾸거나(분홍 톤),
  줄이고 검은 테두리를 붙인 복사본도 움직임의 시간 변화는 같아서 잡힌다 (cc_3_190506 묶음 4개)
라벨 값은 쓰지 않는다. 같은 영상에 라벨이 다르게 붙거나(cc_3_200822 / cc_3_211029), 라벨이 같은데
다른 사고인 경우(cc_3_150101 / cc_3_220723)가 있어서다.

  python tools/data/find_duplicates.py data/videos/cc     # → outputs/dedup/pairs.json, 후보 쌍 그림

결과는 후보다. outputs/dedup/<A>__<B>.jpg를 눈으로 보고 확정한다.
"""
import glob
import itertools
import json
import os
import sys

import cv2
import numpy as np

STEP_SEC = 0.5     # 지문을 뽑는 간격
HASH = 16          # 지문 크기 (16x16 = 256비트)
NEAR = 40          # 두 지문의 다른 비트 수가 이 이하이면 같은 장면으로 봄 (256비트 중)
DUP_SHARE = 0.5    # 짧은 쪽 영상의 프레임 중 이 비율 이상이 상대에 같은 장면이 있으면 중복 후보
DARK = 20          # 테두리를 잘라 낼 때 이보다 어두운 줄은 검은 테두리로 봄
MOTION_HZ = 10     # 움직임 곡선을 이 간격(초당 횟수)으로 맞춰 비교 (fps가 다른 복사본 때문)
MOTION_CORR = 0.8  # 움직임 곡선 상관이 이 이상이면 중복 후보
MIN_OVERLAP = 0.6  # 곡선을 밀어 맞출 때 짧은 쪽의 이 비율 이상이 겹쳐야 함 (앞뒤 자른 복사본 허용)


def trim_border(gray):
    """위아래·좌우의 검은 테두리를 잘라 낸다 (테두리만 다른 복사본 때문)"""
    rows = np.where(gray.mean(axis=1) > DARK)[0]
    cols = np.where(gray.mean(axis=0) > DARK)[0]
    if len(rows) < 10 or len(cols) < 10:
        return gray
    return gray[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def dhash(gray):
    small = cv2.resize(gray, (HASH + 1, HASH), interpolation=cv2.INTER_AREA)
    return (small[:, 1:] > small[:, :-1]).flatten()


def fingerprints(path):
    """장면 지문과 움직임 곡선. 프레임을 처음부터 끝까지 한 번 읽는다"""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, round(fps * STEP_SEC))
    hashes, diffs, prev, f = [], [], None, 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if f % step == 0:
            hashes.append(dhash(trim_border(gray)))
        small = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)
        if prev is not None:
            diffs.append(float(np.abs(small - prev).mean()))
        prev, f = small, f + 1
    cap.release()
    # 움직임 곡선을 MOTION_HZ 간격으로 다시 뽑고 평균 0, 표준편차 1로 맞춤 (밝기·크기 차이를 없앰)
    t = np.arange(1, len(diffs) + 1) / fps
    grid = np.arange(t[0], t[-1], 1 / MOTION_HZ) if len(t) > 1 else np.array([])
    curve = np.interp(grid, t, diffs) if len(grid) else np.array([])
    if len(curve) and curve.std() > 0:
        curve = (curve - curve.mean()) / curve.std()
    return {"fps": fps, "frames": f, "hashes": np.array(hashes, bool), "motion": curve}


def motion_corr(a, b):
    """두 움직임 곡선을 앞뒤로 밀어 보며 가장 높은 상관"""
    if len(a) > len(b):
        a, b = b, a
    need = max(int(len(a) * MIN_OVERLAP), MOTION_HZ * 3)
    best = 0.0
    for lag in range(-len(a) + need, len(b) - need + 1):
        lo, hi = max(0, lag), min(len(b), lag + len(a))
        x, y = a[lo - lag:hi - lag], b[lo:hi]
        if len(x) < need or x.std() == 0 or y.std() == 0:
            continue
        best = max(best, float(np.corrcoef(x, y)[0, 1]))
    return best


def share(a, b):
    """a의 지문 중 b에 같은 장면(NEAR 이하)이 있는 비율, 그리고 그 장면들의 평균 차이"""
    if len(a) == 0 or len(b) == 0:
        return 0.0, None
    dist = (a[:, None, :] != b[None, :, :]).sum(axis=2).min(axis=1)
    hit = dist <= NEAR
    return float(hit.mean()), (float(dist[hit].mean()) if hit.any() else None)


def sheet(va, vb, out_path):
    """두 영상의 25%·50%·75% 지점을 위아래로 나란히 놓은 그림"""
    rows = []
    for v in (va, vb):
        cap = cv2.VideoCapture(v)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        tiles = []
        for r in (0.25, 0.5, 0.75):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * r))
            ok, img = cap.read()
            img = img if ok else np.zeros((360, 640, 3), np.uint8)
            img = cv2.resize(img, (480, 270))
            cv2.putText(img, os.path.basename(v)[:24], (8, 24), 0, 0.6, (0, 255, 255), 2)
            tiles.append(img)
        cap.release()
        rows.append(np.hstack(tiles))
    cv2.imwrite(out_path, np.vstack(rows))


def run(video_dir, out_dir="outputs/dedup"):
    os.makedirs(out_dir, exist_ok=True)
    vids = sorted(glob.glob(os.path.join(video_dir, "cc_*.mp4")))
    fp = {}
    for i, v in enumerate(vids, 1):
        fp[v] = fingerprints(v)
        print(f"\r지문 {i}/{len(vids)}", end="", flush=True)
    print()

    pairs = []
    for va, vb in itertools.combinations(vids, 2):
        a, b = fp[va]["hashes"], fp[vb]["hashes"]
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        s, d = share(short, long_)
        c = motion_corr(fp[va]["motion"], fp[vb]["motion"])
        if s >= DUP_SHARE or c >= MOTION_CORR:
            name = lambda v: os.path.basename(v)[:-4]
            img = os.path.join(out_dir, f"{name(va)[5:11]}__{name(vb)[5:11]}.jpg")
            sheet(va, vb, img)
            pairs.append({"a": name(va), "b": name(vb), "share": round(s, 3), "motion_corr": round(c, 3),
                          "mean_diff": round(d, 1) if d is not None else None, "image": img})
    pairs.sort(key=lambda p: -max(p["share"], p["motion_corr"]))
    with open(os.path.join(out_dir, "pairs.json"), "w", encoding="utf-8") as f:
        json.dump({"params": {"step_sec": STEP_SEC, "hash": HASH, "near": NEAR, "dup_share": DUP_SHARE,
                              "motion_hz": MOTION_HZ, "motion_corr": MOTION_CORR, "min_overlap": MIN_OVERLAP},
                   "videos": len(vids), "pairs": pairs}, f, ensure_ascii=False, indent=1)
    for p in pairs:
        print(f"지문 {p['share']:.2f} 움직임 {p['motion_corr']:.2f}  {p['a']} ↔ {p['b']}")
    print(f"영상 {len(vids)}개, 중복 후보 {len(pairs)}쌍 → {out_dir}/pairs.json")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "data/videos/cc")
