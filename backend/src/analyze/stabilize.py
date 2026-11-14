"""흔들리거나 움직이는 CCTV(휴대폰으로 모니터를 다시 찍음, 흔들리는 화면)를 첫 프레임에 맞춰 고정 화면으로 만든다

  python src/analyze/stabilize.py <영상> [결과 폴더]   # → stabilized.mp4, stabilize.json

사용자가 CCTV를 골랐고 camera_check가 "움직이는 카메라"로 본 영상에만 쓴다. 블랙박스는 앞으로 달려서 금방
다른 장면이 되지만, 움직이는 CCTV는 같은 장면이 흔들리기만 해서 첫 프레임과 특징점이 계속 맞는다.
check()는 사용자가 블랙박스를 CCTV로 잘못 골랐을 때 막는 안전장치다 (10-26 전체 확인, tools/data/camera_survey.py:
움직이는 카메라로 본 CCTV 41개 영상 전체 중앙값 45~974, 블랙박스 66개 10~968).

방법: 프레임마다 ORB 특징점을 첫 프레임과 맞춰 RANSAC으로 호모그래피를 구하고, 첫 프레임 좌표로 되돌려 그린다.
첫 프레임과 직접 맞는 점이 MIN_INLIERS보다 적으면 앞 프레임과 맞춘 변환을 이어 붙인다.
이렇게 해도 맞는 점의 중앙값이 STABLE_MEDIAN보다 적으면 "보정할 수 없음"(블랙박스로 봄)이다.
"""
import json
import os
import sys

import cv2
import numpy as np

WORK_W = 640          # 특징점을 찾을 때 줄이는 폭
MIN_INLIERS = 40      # 첫 프레임과 직접 맞는 점이 이보다 적으면 앞 프레임 변환을 이어 붙임
# 맞는 점 중앙값이 이보다 적으면 보정할 수 없음(블랙박스로 봄). 진짜 CCTV를 막지 않는 게 먼저라 가장 낮은 CCTV(45)보다
# 여유 있게 낮춤. 이 기준으로 블랙박스 66개 중 34개를 막는다. 서 있다 출발하는 블랙박스 일부와 정차한 블랙박스는 못 막음
STABLE_MEDIAN = 35
CHECK_STEP = 5        # check()가 영상 전체에서 몇 프레임마다 볼지
ORB_N = 2000
# 앞 프레임 변환과 비교해 화면 네 귀퉁이가 이 비율(작업 폭 기준)보다 많이 움직이면 틀린 변환으로 보고 버림.
# 충돌 뒤 큰 차가 카메라 앞을 가리면 맞는 점이 차에 몰려 변환이 크게 틀어진다(cc_160726의 120~124프레임).
# 휴대폰 흔들림은 프레임 사이에 이보다 훨씬 작게 움직임
JUMP_MAX = 0.1
# 앞 프레임에 이어 붙인 변환은 오차가 쌓인다. 회전·줌하는 CCTV(cc_220103: 사고 뒤 1.7배 줌인)는 끝부분이 어긋났다.
# 이어 붙인 프레임은 첫 그림의 특징점을 그 변환으로 지금 프레임에 옮겨, 지금 프레임의 같은 특징점과 ALIGN_PX 안에
# 겹치는 수를 다시 센다. 이 수가 ALIGN_MIN보다 적은 프레임이 UNVERIFIED_RUN번 이어지면 "확인 못 한 구간"으로 남긴다.
# 그 구간을 잘라 버리지는 않는다: 크게 줌한 화면은 정렬이 맞아도 첫 그림과 특징점이 거의 안 맞아서(cc_171218은 맞았는데
# 0, cc_220103은 어긋났는데 0) 맞았는지 틀렸는지 가를 수 없고, 자르면 171218의 충돌(120프레임쯤)까지 잘린다.
# 대신 결과에 "그 구간 위치는 정확하지 않을 수 있음"을 알린다 (pipeline.solve의 camera_notice)
ALIGN_PX = 4
ALIGN_MIN = 10        # 흔들리기만 한 휴대폰 촬영(cc_220119)은 이어 붙여도 12 이상
UNVERIFIED_RUN = 3


def _aligned(bf, k0, d0, kb, db, H):
    """첫 그림 특징점(k0)을 H(첫 그림 → 이 프레임)로 옮긴 자리와 이 프레임의 짝 특징점(kb)이 ALIGN_PX 안인 수"""
    if db is None or d0 is None:
        return 0
    ms = [m for m, n in (p for p in bf.knnMatch(d0, db, k=2) if len(p) == 2) if m.distance < 0.75 * n.distance]
    if not ms:
        return 0
    src = cv2.perspectiveTransform(np.float32([k0[m.queryIdx].pt for m in ms]).reshape(-1, 1, 2), H).reshape(-1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in ms])
    return int((np.linalg.norm(src - dst, axis=1) <= ALIGN_PX).sum())


def _jump(H, H_prev):
    """두 변환으로 옮긴 작업 그림 네 귀퉁이의 최대 거리 / 작업 폭"""
    h = WORK_W * 9 / 16
    c = np.float32([[0, 0], [WORK_W, 0], [WORK_W, h], [0, h]]).reshape(-1, 1, 2)
    a, b = cv2.perspectiveTransform(c, H), cv2.perspectiveTransform(c, H_prev)
    return float(np.linalg.norm(a - b, axis=2).max()) / WORK_W


def _match(orb, bf, ka, da, img):
    kb, db = orb.detectAndCompute(img, None)
    if db is None or da is None:
        return None, 0, kb, db
    ms = [m for m, n in (p for p in bf.knnMatch(da, db, k=2) if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(ms) < 15:
        return None, len(ms), kb, db
    src = np.float32([ka[m.queryIdx].pt for m in ms])
    dst = np.float32([kb[m.trainIdx].pt for m in ms])
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    return H, (int(mask.sum()) if mask is not None else 0), kb, db


def unverified_ranges(log):
    """정렬 점수가 ALIGN_MIN보다 낮은 프레임이 UNVERIFIED_RUN번 이상 이어진 구간 [[시작, 끝], ...]"""
    out, run = [], []
    for x in log + [{"frame": None, "aligned": ALIGN_MIN}]:   # 끝 표시
        if x["frame"] is not None and x.get("aligned", ALIGN_MIN) < ALIGN_MIN:
            run.append(x["frame"])
            continue
        if len(run) >= UNVERIFIED_RUN:
            out.append([run[0], run[-1]])
        run = []
    return out


def check(video):
    """영상 전체를 CHECK_STEP 간격으로 보고 보정할 수 있는지 (맞는 점 중앙값). 반환: (보정 가능, 중앙값)
    앞부분만 보면 서 있다가 출발하는 블랙박스가 통과한다 (앞 60프레임만 볼 때 블랙박스 66개가 통과)"""
    cap = cv2.VideoCapture(video)
    ok, f0 = cap.read()
    if not ok:
        return False, 0
    s = WORK_W / f0.shape[1]
    g0 = cv2.cvtColor(cv2.resize(f0, None, fx=s, fy=s), cv2.COLOR_BGR2GRAY)
    orb, bf = cv2.ORB_create(ORB_N), cv2.BFMatcher(cv2.NORM_HAMMING)
    k0, d0 = orb.detectAndCompute(g0, None)
    inl, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        i += 1
        if i % CHECK_STEP == 0:
            g = cv2.cvtColor(cv2.resize(f, None, fx=s, fy=s), cv2.COLOR_BGR2GRAY)
            inl.append(_match(orb, bf, k0, d0, g)[1])
    cap.release()
    med = int(np.median(inl)) if inl else 0
    return med >= STABLE_MEDIAN, med


def run(video, out_dir="outputs"):
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    ok, f0 = cap.read()
    H0, W0 = f0.shape[:2]
    s = WORK_W / W0
    S = np.diag([s, s, 1.0])
    to_small = lambda f: cv2.cvtColor(cv2.resize(f, None, fx=s, fy=s), cv2.COLOR_BGR2GRAY)
    orb, bf = cv2.ORB_create(ORB_N), cv2.BFMatcher(cv2.NORM_HAMMING)
    k0, d0 = orb.detectAndCompute(to_small(f0), None)

    path = os.path.join(out_dir, "stabilized.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W0, H0))
    writer.write(f0)
    H_prev = np.eye(3)              # 앞 프레임 → 첫 프레임 (작은 그림 좌표에서, 첫→현재 방향)
    kp, dp = k0, d0
    log, f = [], 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        f += 1
        g = to_small(img)
        H, n, kb, db = _match(orb, bf, k0, d0, g)       # 첫 프레임 → 이 프레임
        how = "first"
        if H is None or n < MIN_INLIERS or _jump(H, H_prev) > JUMP_MAX:
            Hs, n2, _, _ = _match(orb, bf, kp, dp, g)    # 앞 프레임 → 이 프레임
            if Hs is not None and _jump(Hs @ H_prev, H_prev) <= JUMP_MAX:
                H, n, how = Hs @ H_prev, n2, "chain"
            else:
                H, n, how = H_prev, 0, "keep"
        H_prev, kp, dp = H, kb, db
        Hfull = np.linalg.inv(S) @ H @ S                # 원래 크기 좌표
        to_ref = np.linalg.inv(Hfull)                   # 이 프레임 좌표 → 첫 프레임 좌표 (픽셀)
        writer.write(cv2.warpPerspective(img, to_ref, (W0, H0)))
        # 첫 그림과 직접 맞춘 프레임은 맞는 점 수(n)가 곧 정렬 점수. 이어 붙인 프레임은 다시 잼
        aligned = n if how == "first" else _aligned(bf, k0, d0, kb, db, H)
        # to_ref는 평가 때 정답 라벨 박스를 보정한 좌표로 옮기는 데 씀 (src/eval/match_parties.align_gt)
        log.append({"frame": f, "inliers": n, "how": how, "aligned": aligned, "to_ref": np.round(to_ref, 6).tolist()})
    cap.release()
    writer.release()
    inl = [x["inliers"] for x in log]
    out = {"video": video, "stabilized": path, "frames": f + 1, "size": [W0, H0],
           "inliers_median": int(np.median(inl)) if inl else 0,
           "chained": sum(x["how"] != "first" for x in log),
           "unverified": unverified_ranges(log),   # 정렬을 확인 못 한 구간 [[시작, 끝], ...]
           "params": {"work_w": WORK_W, "min_inliers": MIN_INLIERS, "stable_median": STABLE_MEDIAN,
                      "jump_max": JUMP_MAX, "align_px": ALIGN_PX, "align_min": ALIGN_MIN,
                      "unverified_run": UNVERIFIED_RUN},
           "log": log}
    with open(os.path.join(out_dir, "stabilize.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)
    print(f"보정: {path} (맞는 점 중앙값 {out['inliers_median']}, 앞 프레임 연결 {out['chained']}번)")
    return path


if __name__ == "__main__":
    out = sys.argv[2] if len(sys.argv) > 2 else "outputs"
    os.makedirs(out, exist_ok=True)
    run(sys.argv[1], out)
