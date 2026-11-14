"""교차로에 들어가기 전에 속도를 줄였는지 (서행) — 화면에서 확실할 때만 추정 (docs/facts_plan.md 8절)

판정 모듈의 "서행(일시정지 포함)" -10과 "서행·감속 불이행" +10(비신호 교차로 도표 42개)에 쓰인다.
화면 속도로는 km/h를 몰라서(교차로 크기를 모름) 서행 여부를 바로 정할 수 없다. 평가 24개로 재 본 결과
(tools/experiments/slowdown_try.py) 감속 비율은 대부분 0.4~1.1에 몰려 있고, 회전하는 차는 원래 속도를 줄여서
비율만으로는 못 가른다. 그래서 확실한 두 경우만 추정값으로 쓰고 나머지는 질문으로 둔다.
  - 진입 전에 멈춤(stopped_before_entry, 경계 검사 통과) → 줄였음 (일시정지는 서행에 포함)
  - 진입 직전 1초가 그 전보다 오히려 빨라짐 (비율 SPEEDUP 이상) → 안 줄였음
"""
import math

import cv2
import numpy as np

SMOOTH = 5        # 속도를 볼 때 이만큼 떨어진 프레임 사이로 잼 (잡음 줄이기)
SPEEDUP = 1.1     # 진입 직전 가장 느린 속도 ÷ 그 전 속도가 이 이상이면 "안 줄였음"
MIN_FAR = 0.02    # 그 전 속도가 이보다 느리면(거의 서 있음) 비율을 안 봄 (한 변/초)


def square_of(corners):
    """모서리를 중심 기준 각도 순으로 정렬해 한 변 1인 정사각형에 맞추는 변환 (make_scene.build_scene과 같은 정렬)"""
    cx, cy = sum(p[0] for p in corners) / 4, sum(p[1] for p in corners) / 4
    pts = sorted(corners, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    return cv2.getPerspectiveTransform(np.float32(pts), np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]))


def warp(H, p):
    q = H @ np.array([p[0], p[1], 1.0])
    return q[:2] / q[2]


def speeds(path, H, fps):
    """{프레임: 편 좌표 속도(교차로 한 변/초)}. 원근 때문에 먼 차가 느려 보이는 걸 줄이려고 편 좌표에서 잼"""
    fs = sorted(path)
    sq = {f: warp(H, path[f]) for f in fs}
    out = {}
    for i, f in enumerate(fs):
        j = next((k for k in range(i + 1, len(fs)) if fs[k] - f >= SMOOTH), None)
        if j is not None:
            out[f] = float(np.linalg.norm(sq[fs[j]] - sq[f])) * fps / (fs[j] - f)
    return out


def measure(path, H, fps, entry):
    """진입 직전 1초 가장 느린 속도 ÷ 진입 2~1초 전 속도 (중앙값). 궤적이 짧으면 None"""
    v = speeds(path, H, fps)
    far = [s for f, s in v.items() if entry - 2 * fps <= f < entry - fps]
    near = [s for f, s in v.items() if entry - fps <= f <= entry]
    if len(far) < 3 or len(near) < 3:
        return None
    v_far = float(np.median(far))
    return {"ratio": round(min(near) / v_far, 2) if v_far > MIN_FAR else None, "v_far": round(v_far, 3),
            "v_min": round(min(near), 3)}


def guess(party, path, corners, fps, entry):
    """서행 추정: True(줄였음) / False(안 줄였음) / None(모름 → 질문)"""
    if party.get("stopped_before_entry"):
        return True
    if entry is None or not corners or not path:
        return None
    m = measure(path, square_of([tuple(c) for c in corners]), fps, entry)
    if m and m["ratio"] is not None and m["ratio"] >= SPEEDUP:
        return False
    return None
