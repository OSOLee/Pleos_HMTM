# MTM(OSOLee/MTM) feature/server의 src/analyze/scene_crosswalk.py 복사본. import만 video_lib로 바꿈 (docs/origin.md). MTM 쪽을 고친 뒤 다시 복사한다.
# B 전달 참고 구현(초안, 2026-11-10) scene_crosswalk.py 복사본. 임계값은 B가 임시값이라 했음. 고치지 말고 B 것을 다시 복사한다. 좌표는 픽셀.
# B 전달 참고 구현(초안, 2026-11-10) scene_crosswalk.py 복사본. 임계값은 B가 임시값이라 했음. 고치지 말고 B 것을 다시 복사한다. 좌표는 픽셀.
"""M6(교차로 형태 분류)·M5(횡단보도 탐지) 결과를 bb-0.2 facts 조각으로 바꾸는 참고 구현 (초안)

용도: HMTM 분석기 자리(HMTM_BB_ANALYZER=mtm)를 채우는 A의 코드에서 불러 쓰는 보조 모듈.
     사고 순간(t_impact)과 프레임은 A의 코드가 이미 갖고 있다는 전제.

원칙 (HMTM 설계와 같음)
- 확실하면 값(confident), 애매하면 추정(guess)만, 모르면 키를 내지 않는다 → HMTM이 사용자에게 묻는다.
- 화면 거리로 잰 값은 정확하지 않으므로 거리는 늘 measured=False, guess로 낸다.

TODO(대조 필요): 아래 값 이름(location, junction_type, ped_place, 거리 구간 이름)은
judge의 docs/FACTS_SPEC.md 와 HMTM docs/design-blackbox.md 8.3 의 이름과 대조해서 맞출 것.
임계값(*_MIN, *_RATIO)은 모두 임시값. 평가 영상으로 조정할 것.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

# ---------------------------------------------------------------------------
# 공통 결과 형태: A의 bb-0.2 변환기가 이 값을 읽어 필드에 넣는다
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    value: object
    confidence: float          # 0~1
    guess: bool                # True면 추정값만 (HMTM이 질문으로 확인)
    source: str                # "M6" / "M5"
    hints: dict = field(default_factory=dict)  # 근거 (클래스별 확률, 프레임 수 등)


Frame = tuple[float, np.ndarray]   # (영상 시각 초, BGR 이미지)


def _in_window(frames: Iterable[Frame], t_impact: float, start: float, end: float) -> list[Frame]:
    return [(t, img) for t, img in frames if t_impact + start <= t <= t_impact + end]


# ---------------------------------------------------------------------------
# M6: 교차로 형태 → road.location / junction_type / signal_present
# ---------------------------------------------------------------------------

# TODO(대조 필요): judge 값 이름
SCENE_TO_ROAD = {
    "cross_signal":   {"location": "intersection", "junction_type": "cross", "signal_present": True},
    "cross_nosignal": {"location": "intersection", "junction_type": "cross", "signal_present": False},
    "t_junction":     {"location": "intersection", "junction_type": "t"},   # 신호 유무는 장면만으로 모름 → 질문
    "straight":       {"location": "straight"},
}
# detector v0.26.0 평가 기록: 영상 단위 정확도 66.2%, 확신도 0.9 이상만 자동 처리해도 정확도 84.2%(자동 47.9%).
# → 자동 결정에는 쓰지 않고 "추천값 + 확인 질문"으로만 사용하기로 함. 그래서 M6 값은 항상 guess로 낸다.
# 재학습으로 자동 처리 정확도가 90%를 넘는 기준값이 생기면 그 값을 넣고 SCENE_AUTO를 True로.
SCENE_AUTO = False
SCENE_CONF_MIN = 0.90      # SCENE_AUTO=True일 때만 사용. 이 이상이면 확정
SCENE_WINDOW = (-2.0, 0.0)  # 충돌 2초 전 ~ 충돌 순간 (블랙박스는 한 장면만으론 교차로 모양이 안 보일 수 있음)
SCENE_STEP = 0.5            # 0.5초 간격으로 뽑아 평균 → 충돌 직전 5장면 (-2.0, -1.5, -1.0, -0.5, 0)
SCENE_FRAMES = 5            # 최대 장면 수 (창·간격을 바꿔도 5장을 넘기지 않게 뒤에서부터 자름)


def classify_scene(model, frames: list[Frame], t_impact: float, imgsz: int = 384) -> dict[str, Fact]:
    """충돌 직전 여러 장면의 클래스 확률을 평균내 한 번 판단한다 (eval_cls.py --by-video 와 같은 방식)."""
    picked, last = [], -1e9
    for t, img in _in_window(frames, t_impact, *SCENE_WINDOW):
        if t - last >= SCENE_STEP:
            picked.append(img)
            last = t
    picked = picked[-SCENE_FRAMES:]
    if not picked:
        return {}

    results = model.predict(picked, imgsz=imgsz, verbose=False)
    names = results[0].names                      # {index: class name}
    probs = np.mean([r.probs.data.cpu().numpy() for r in results], axis=0)
    top = int(probs.argmax())
    scene, conf = names[top], float(probs[top])

    road = SCENE_TO_ROAD.get(scene)
    if road is None:                              # 학습에 없는 장소 → 내지 않음 (질문)
        return {}
    guess = (not SCENE_AUTO) or conf < SCENE_CONF_MIN
    hints = {"scene": scene, "frames": len(picked),
             "scores": {names[i]: round(float(p), 3) for i, p in enumerate(probs)}}
    return {f"road.{k}": Fact(v, conf, guess, "M6", hints) for k, v in road.items()}


# ---------------------------------------------------------------------------
# M5: 횡단보도 탐지 + 상대(보행자·자전거) 발 위치 → ped_place / dist_from_crosswalk_m
# ---------------------------------------------------------------------------

CROSSWALK_CLASS = "crosswalk"
CW_DET_CONF = 0.40         # 횡단보도 박스 탐지 확신도 하한
CW_WINDOW = (-3.0, 0.2)    # 충돌 3초 전 ~ 0.2초 뒤. 이 안에서 사람 박스가 잡힌 마지막 CW_LAST_N개 프레임만 쓴다
CW_LAST_N = 6              # 사람이 차 앞까지 와서 사고 직전 박스가 안 잡히는 영상이 있어, 구간을 고정하지 않고 마지막 N개를 쓴다 (3개 미만이면 질문)
CW_PRED_CONF = 0.15        # 횡단보도 탐지 모델에 넘기는 최소 확신도 (넘기지 않으면 ultralytics 기본 0.25로 돌아감). 박스를 쓰는 기준은 CW_DET_CONF
MIN_FRAMES = 3             # 발 위치가 있는 프레임이 이보다 적으면 판단하지 않음
ON_RATIO_MIN = 0.6         # 발이 박스 안에 있던 프레임 비율이 이 이상이면 "횡단보도 위"
SEEN_RATIO_MIN = 0.5       # 횡단보도가 보인 프레임 비율이 이 이상이어야 "부근"을 말함
NEAR_GAP_MAX = 1.0         # (발 ~ 박스 세로 거리) / 박스 높이 가 이 이하면 "10m 이내" 추정
EDGE_MARGIN = 0.05         # 박스 경계 여유 (박스 높이 대비)

# TODO(대조 필요): 구간 이름과 대표 거리 (설계 8.3.2 표: 위 / 10m 이내(5) / 10~30m(20) / 30m 초과(40))
BIN_ON, BIN_10, BIN_30, BIN_OVER = "on", "within_10m", "10_30m", "over_30m"
BIN_DIST = {BIN_10: 5, BIN_30: 20, BIN_OVER: 40}


def _boxes(result) -> np.ndarray:
    names = result.names
    keep = [i for i, (c, s) in enumerate(zip(result.boxes.cls.tolist(), result.boxes.conf.tolist()))
            if names[int(c)] == CROSSWALK_CLASS and s >= CW_DET_CONF]
    return result.boxes.xyxy.cpu().numpy()[keep] if keep else np.zeros((0, 4))


def _relate(foot: tuple[float, float], boxes: np.ndarray) -> tuple[bool, float | None]:
    """(발이 박스 안인지, 가장 가까운 박스까지 세로 거리/박스 높이). 가로로 겹치는 박스만 거리 계산."""
    fx, fy = foot
    inside, gaps = False, []
    for x1, y1, x2, y2 in boxes:
        h = max(y2 - y1, 1.0)
        m = EDGE_MARGIN * h
        if x1 - m <= fx <= x2 + m and y1 - m <= fy <= y2 + m:
            inside = True
        elif x1 <= fx <= x2:
            gaps.append(min(abs(fy - y1), abs(fy - y2)) / h)
    return inside, (min(gaps) if gaps else None)


def relate_crosswalk(model, frames: list[Frame], feet: dict[float, tuple[float, float]],
                     t_impact: float, imgsz: int = 960, conf: float = CW_PRED_CONF) -> dict[str, Fact]:
    """feet: {프레임 시각: 상대의 발 위치(박스 아래 가운데, 픽셀)} — A의 추적 결과에서.

    반환 키: "parties.other.ped_place", "parties.other.dist_from_crosswalk_m" (없으면 질문)
    """
    win = sorted(((t, img) for t, img in _in_window(frames, t_impact, *CW_WINDOW) if t in feet), key=lambda x: x[0])[-CW_LAST_N:]
    if len(win) < MIN_FRAMES:
        return {}

    results = model.predict([img for _, img in win], imgsz=imgsz, conf=conf, verbose=False)
    n, on, seen, gaps = len(win), 0, 0, []
    for (t, _), r in zip(win, results):
        boxes = _boxes(r)
        if len(boxes):
            seen += 1
            inside, gap = _relate(feet[t], boxes)
            on += inside
            if not inside and gap is not None:
                gaps.append(gap)

    hints = {"frames": n, "on_frames": on, "crosswalk_seen_frames": seen}
    out: dict[str, Fact] = {}

    if on / n >= ON_RATIO_MIN:                               # 횡단보도 위
        out["parties.other.ped_place"] = Fact("crosswalk", on / n, False, "M5", {**hints, "bin": BIN_ON})
        return out

    if seen / n >= SEEN_RATIO_MIN:                           # 횡단보도는 보이는데 위는 아님 → 부근
        conf = seen / n
        out["parties.other.ped_place"] = Fact("near_crosswalk", conf, True, "M5", hints)
        if gaps:
            g = float(np.median(gaps))
            hints["gap_ratio"] = round(g, 2)
            if g <= NEAR_GAP_MAX:                            # 화면상 가까움 → 10m 이내로 추정
                out["parties.other.dist_from_crosswalk_m"] = Fact(
                    BIN_DIST[BIN_10], conf, True, "M5", {**hints, "bin": BIN_10, "measured": False})
            # 더 먼 구간(10~30m, 30m 초과)은 화면 거리로 가르기 어려움 → 내지 않고 질문
        return out

    # 횡단보도가 거의 안 보임: "없음"을 확정하지 않는다 (탐지 누락일 수 있음) → 질문
    return {}
