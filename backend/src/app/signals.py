"""신호등 ↔ 진입로 연결과, 연결된 신호등 색으로 당사자 신호 색 채우기

신호 색 판정에 필요한 건 "1번 차가 들어갈 때 1번 차 쪽 신호"인데, 탐지 모델은 화면의 신호등이 어느 길의 신호인지
모른다 (CCTV는 신호등 옆·뒤를 찍는 경우도 많음). 그래서 사용자에게 신호등마다 "어느 길 신호인가요?"를 한 번 묻고
(선택 질문), 연결되면 그 신호등의 프레임별 색(light_states.py)에서 당사자의 진입 때·충돌 때 색을 읽는다.

모델 값의 확신도에 따라 세 갈래 (docs/facts_plan.md 7절):
  확신 높음 (AUTO_MIN 이상)  질문 없이 사실로 씀. 지금 색 분류기(light_cnn, 시험 0.70)로는 끔 (AUTO_MIN = None)
  애매함                     신호 색 질문에 모델 값을 미리 골라 둠 (model_guess)
  모름                       지금처럼 빈 질문
B 탐지 모델로 바꾸고 정확도를 확인하면 MTM_SIGNAL_AUTO_MIN으로 첫 갈래를 켠다.

색 분류기는 red / green / etc(노랑·꺼짐·뒷면 등)만 내서, 노랑과 꺼짐을 가르지 못한다. 그래서 점멸은 빨강 점멸만
(빨강과 etc가 짧게 번갈아 나옴) 보고, 노랑 점멸은 질문으로 둔다.
"""
import os
from collections import Counter

from src.analyze.build_facts import DIRS, DIR_NAMES

MIN_STATES = 5        # 색 기록이 이보다 적은 신호등은 묻지 않음 (잠깐 잡힌 잡음)
MAX_LIGHTS = 4        # 연결 질문을 하는 신호등 수 (기록이 많은 것부터)
NEAR = 6              # 이 프레임 안의 색 기록으로 그 순간 색을 봄 (light_states.STEP의 두 배)
P_MIN = 0.6           # 이보다 확신이 낮은 색 기록은 안 씀
AGREE_MIN = 0.75      # 근처 기록 중 이 비율 이상이 같은 색이어야 그 색으로 봄
FLASH_WIN = 30        # 점멸을 볼 구간 (프레임, 앞뒤로)
FLASH_SWITCHES = 4    # 이 구간에서 빨강↔etc가 이만큼 바뀌면 빨강 점멸로 봄
_auto = os.environ.get("MTM_SIGNAL_AUTO_MIN")
AUTO_MIN = float(_auto) if _auto else None   # 확신 높음 기준 (근처 기록 중 같은 색 비율). None이면 자동 확정 안 함

OTHER = ["pedestrian", "unknown"]
OTHER_NAMES = ["보행자 신호", "모르겠음"]


def candidates(facts):
    """연결 질문을 할 신호등: 색 기록이 MIN_STATES 이상인 것 중 기록이 많은 순으로 MAX_LIGHTS개"""
    states = facts.get("traffic_light_states") or {}
    ok = [t for t, s in states.items() if len(s) >= MIN_STATES]
    return sorted(ok, key=lambda t: -len(states[t]))[:MAX_LIGHTS]


def questions(facts, closed=None):
    """신호등마다 "어느 길 신호인가요?" (신호등이 있다고 답했을 때만, 선택 질문).
    closed: 삼거리면 길이 없는 쪽 (scene.json의 closed_side, 보기에서 뺌).
    그림에는 그 신호등 박스를 그림 (pipeline이 light_track을 보고 이름표를 붙임)"""
    states = facts.get("traffic_light_states") or {}
    f0 = facts["collision"]["frame"]
    dirs = [d for d in DIRS if d != closed]
    out = []
    for t in candidates(facts):
        frame = min(states[t], key=lambda s: abs(s["frame"] - f0))["frame"]   # 충돌에 가장 가까운 기록 장면
        out.append({"field": f"lights.{t}.approach", "question": f"{t}번 신호등은 어느 길의 신호인가요?",
                    "answer_type": "choice", "options": dirs + OTHER,
                    "choices": [DIR_NAMES[d] + " 차량 신호" for d in dirs] + OTHER_NAMES,
                    "model_guess": None, "evidence_frame": frame, "light_track": t, "optional": True, "group": "신호등",
                    "depends_on": {"road.signal_present": True}})
    return out


def color_at(states, f):
    """프레임 f 근처(NEAR) 색 기록의 다수결. (색, 같은 색 비율) 또는 None.
    빨강 점멸이면 ("flashing_red", 비율). etc만 나오면 노랑인지 꺼짐인지 몰라서 None"""
    near = [s for s in states if abs(s["frame"] - f) <= NEAR and s["p"] >= P_MIN]
    if not near:
        return None
    if flashing_red(states, f):
        return "flashing_red", 1.0
    color, n = Counter(s["color"] for s in near).most_common(1)[0]
    share = n / len(near)
    if color == "etc" or share < AGREE_MIN:
        return None
    return color, share


def flashing_red(states, f):
    """f 앞뒤 FLASH_WIN 안에서 빨강과 etc가 FLASH_SWITCHES번 이상 번갈아 나오면 빨강 점멸"""
    seq = [s["color"] for s in sorted(states, key=lambda s: s["frame"])
           if abs(s["frame"] - f) <= FLASH_WIN and s["p"] >= P_MIN and s["color"] in ("red", "etc")]
    switches = sum(a != b for a, b in zip(seq, seq[1:]))
    return switches >= FLASH_SWITCHES and seq.count("red") >= 2 and seq.count("etc") >= 2


LATE_SEC = 2.0      # 진입 때 빨강이 아니었는데 이 안에 빨강이 되면 "적신호 직전 진입"으로 미리 골라 둠


def late_red(facts, user, came_from):
    """연결된 신호등이 당사자 진입 때 빨강이 아니었고(초록·노랑·꺼짐) 진입 뒤 LATE_SEC 안에 빨강이 됐으면 그 당사자.
    색 분류기가 노랑을 따로 못 가려서(etc) 노란불 진입을 직접 못 보고, 곧 빨강이 된 것으로 대신 봄"""
    states = facts.get("traffic_light_states") or {}
    by_dir = lights_of(user)
    fps = facts.get("fps") or 30
    out = []
    for t, came in came_from.items():
        p = facts["parties"].get(t) or {}
        entry = user.get(f"parties.{t}.intersection_entry") or (p.get("intersection_entry") or {}).get("frame")
        lights = by_dir.get(came)
        if entry is None or not lights:
            continue
        for l in lights:
            st = states.get(l, [])
            at = color_at(st, entry)
            later = [color_at(st, entry + k) for k in range(NEAR, int(LATE_SEC * fps) + 1, NEAR)]
            if at and at[0] != "red" and any(c and c[0] == "red" for c in later):
                out.append(t)
                break
    return out


def lights_of(user):
    """답에서 {진입로 방위: [신호등]}"""
    out = {}
    for k, v in user.items():
        if k.startswith("lights.") and k.endswith(".approach") and v in DIRS:
            out.setdefault(v, []).append(k.split(".")[1])
    return out


def guesses(facts, user, came_from):
    """연결된 신호등으로 당사자 신호 색 추정. came_from: {당사자: 들어온 길(답 우선)}.
    반환: {field: (색, 비율)}. 한 길에 신호등이 여럿이면 색이 같을 때만 (다르면 화살표 신호 등이라 모름)"""
    states = facts.get("traffic_light_states") or {}
    by_dir = lights_of(user)
    f0 = facts["collision"]["frame"]
    out = {}
    for t, came in came_from.items():
        lights = by_dir.get(came)
        if not lights:
            continue
        p = facts["parties"].get(t) or {}
        entry = user.get(f"parties.{t}.intersection_entry") or (p.get("intersection_entry") or {}).get("frame")
        for key, f in (("signal_at_entry", entry), ("signal_at_collision", f0)):
            if f is None:
                continue
            seen = [color_at(states.get(l, []), f) for l in lights]
            seen = [s for s in seen if s]
            if seen and len({c for c, _ in seen}) == 1:
                out[f"parties.{t}.{key}"] = (seen[0][0], min(r for _, r in seen))
    return out
