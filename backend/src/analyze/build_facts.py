import os
import json
import math

from src.analyze import finalize_tracks

WIN = 15            # 진행 방향을 잴 프레임 수 (약 1초)
TURN_DEG = 30        # 진행 방향이 이 각도 이상 바뀌면 회전으로 판단
U_TURN_DEG = 150     # 이 각도 이상이면 유턴
MIN_DISP = 0.02      # 1초 동안 이동 거리가 이보다 작으면 방향을 판단하지 않음
BORDER_DEG = 10      # 회전 기준 각도에서 이만큼 안쪽이면 경계값으로 보고 사용자에게 확인
BORDER_DISP = 1.5    # 이동 거리가 MIN_DISP의 이 배수보다 작아도 경계값
CLS_SURE = 0.85      # 종류 표 중 1등 비율이 이보다 낮으면 사용자에게 확인
PAIR_OPTIONS = 5     # "부딪힌 두 객체" 질문에 보기로 넣을 충돌 수 (detect_collision이 정한 순위대로)
BORN_OPTIONS = 3     # 그 뒤에 덧붙일 "닿은 채 나타난 쌍" 수
LIGHT_NEAR = 3       # 신호 색 참고 정보: 질문 장면에서 이 프레임의 두 배 안에 색 기록이 있는 신호등만 (light_states.STEP)
DIRS = ["north", "east", "south", "west"]  # 지도에서 시계 방향 순서
DIR_NAMES = {"north": "화면 위쪽 길", "east": "화면 오른쪽 길", "south": "화면 아래쪽 길", "west": "화면 왼쪽 길"}
SAME_TIME_SEC = 1.0  # 규칙(차 12): 진입 시각 차이가 이보다 작으면 동시 진입
PLACES = ["intersection", "roundabout", "parking_lot", "straight"]   # 장소 종류 (B의 scene.location)
# 종류 질문 보기. 농기계(경운기·트랙터)는 탐지로 못 잡지만 인정기준에서 자전거와 같은 장이라 고를 수 있게 둠
CLS_OPTIONS = ["car", "truck", "bus", "two_wheeler", "bicycle", "farm_machine", "pedestrian"]
CLS_CHOICES = ["승용차", "트럭", "버스", "이륜차", "자전거", "농기계(경운기·트랙터 등)", "보행자"]
RAY_STEP = 0.01      # 충돌 직전 진행 방향을 늘려 볼 때 한 걸음 (화면 비율)
RAY_MIN_DISP = 0.005 # 충돌 직전 1초 이동이 이보다 작으면 방향을 늘려 보지 않음 (거의 멈춤)
CUSP_DEG = 120       # 주차장 후진 출차: 충돌 뒤 멈췄다가 충돌 전 방향과 이만큼 이상 반대로 다시 가면 충돌 전은 후진
CUSP_MIN_DISP = 0.01 # 그때 충돌 전·후 1초 이동이 이보다 커야 방향을 봄 (주차장은 천천히 움직여서 MIN_DISP의 절반)
ENTRY_BEFORE = 5     # 들어온 길 질문의 근거 장면: 교차로에 들어가기 이만큼 전 프레임

def pos_at(tracks, tid, f):
    by_tf = {tid: {r["frame"]: r for r in tr["frames"]} for tid, tr in tracks.items()}
    recs = by_tf[tid]
    f = max(min(recs), min(max(recs), f))
    return recs[f]["pos"]

def heading(tracks, tid, f1, f2):
    p, q = pos_at(tracks, tid, f1), pos_at(tracks, tid, f2)
    return (q[0] - p[0], q[1] - p[1])

def turn_angle(h1, h2): 
    cross = h1[0] * h2[1] - h1[1] * h2[0]
    dot = h1[0] * h2[0] + h1[1] * h2[1]
    return math.degrees(math.atan2(cross, dot))

def movement(deg):
    if abs(deg) >= U_TURN_DEG:
        return "u_turn"
    if deg >= TURN_DEG:
        return "right_turn"
    if deg <= -TURN_DEG:
        return "left_turn"
    return "straight"

def reverse_cusp(tracks, tid, f0):
    """충돌 전에 후진하고 있었는지 (주차장 후진 출차): 충돌 뒤 멈췄다가, 충돌 직전 방향과 반대로 다시 움직이면
    충돌 전 움직임은 후진이다 (뒤로 빠져나온 뒤 앞으로 출발). 화면 궤적만으로는 앞뒤를 모르지만 이 꺾임은 보임.
    평가에서 후진 출차(AI Hub 유형 127)가 유턴·좌회전으로 잡혀 원문의 "B 후진 +10"이 안 붙었음 (cc_181103, 190730).
    주차장 평가 8개: 후진 출차 5대 중 4대, 직진 출차 3대는 0대가 걸림. 통로 차 8대 중 2대도 걸림(부딪힌 뒤 뒤로 뺌)"""
    frames = sorted(r["frame"] for r in tracks[tid]["frames"])
    h_before = heading(tracks, tid, f0 - WIN, f0)
    if math.hypot(*h_before) < CUSP_MIN_DISP:
        return False
    stopped = False
    for f in range(f0, frames[-1] - WIN + 1, 3):
        h = heading(tracks, tid, f, f + WIN)
        if math.hypot(*h) < CUSP_MIN_DISP / 2:
            stopped = True
        elif stopped and math.hypot(*h) >= CUSP_MIN_DISP and abs(turn_angle(h_before, h)) >= CUSP_DEG:
            return True
    return False


PUSH_WIN = 5         # 밀려남: 이 프레임 수 앞뒤 방향을 비교
PUSH_MIN_DISP = 0.008  # 그때 앞뒤 이동이 둘 다 이보다 커야 봄 (거의 멈춘 차의 흔들림 제외)

def pushed_back(tracks, tid, f_from, f0):
    """충돌로 뒤로 밀렸으면 밀리기 직전 프레임, 아니면 None. 충돌 프레임이 늦게 잡히면(접촉 보간) 밀려난 움직임이
    충돌 전 진행에 섞여서 들어온 진입로로 다시 나간 것처럼 유턴으로 잡혔음 (cc_200227 트럭: 74프레임까지 올라가다
    부딪혀 77~95에 뒤로 밀림, 충돌은 82로 잡힘). 진짜 유턴은 조금씩 돌아서 짧은 구간 앞뒤 방향이 갑자기 뒤집히지 않음"""
    for f in range(f0, max(f_from, f0 - 2 * WIN), -1):
        h1, h2 = heading(tracks, tid, f - PUSH_WIN, f), heading(tracks, tid, f, f + PUSH_WIN)
        if min(math.hypot(*h1), math.hypot(*h2)) >= PUSH_MIN_DISP and abs(turn_angle(h1, h2)) >= CUSP_DEG:
            return f
    return None


def screen_dir(h):
    if abs(h[1]) >= abs(h[0]):
        return "away_from_camera" if h[1] < 0 else "toward_camera"
    return "rightward" if h[0] > 0 else "leftward"

def in_poly(pt, poly):
    """점이 다각형 안에 있는지 (반직선 교차 횟수로 판단)"""
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit

def ray_exit(scene, pos, head, came_from):
    """충돌 지점에서 충돌 직전 진행 방향으로 선을 늘려 처음 닿는 진입로의 방위 (나갈 쪽 추정).
    교차로 안에서 부딪혀 나간 쪽을 못 본 경우에 쓴다. 각도만 보는 것보다 원근의 영향을 덜 받는다
    (화면 위쪽 먼 차는 직진해도 화면에서 꺾여 보임). 들어온 진입로는 건너뜀"""
    n = math.hypot(*head)
    if n < RAY_MIN_DISP:
        return None
    dx, dy = head[0] / n, head[1] / n
    apprs = [(z["direction"], z["polygon"]) for z in scene["zones"]
             if z.get("type") == "approach" and z.get("direction") in DIRS and z["direction"] != came_from]
    for k in range(1, int(2 / RAY_STEP)):
        p = (pos[0] + dx * k * RAY_STEP, pos[1] + dy * k * RAY_STEP)
        if not (0 <= p[0] <= 1 and 0 <= p[1] <= 1):
            return None
        for d, poly in apprs:
            if in_poly(p, poly):
                return d
    return None

def zone_movement(from_dir, exit_dir):
    if from_dir not in DIRS or exit_dir not in DIRS:
        return None
    going = DIRS[(DIRS.index(from_dir) + 2) % 4]    # 진행하는 쪽 = 들어온 방위의 반대

    turn = (DIRS.index(exit_dir) - DIRS.index(going)) % 4
    return {0: "straight", 1: "right_turn", 2: "u_turn", 3: "left_turn"}[turn]

# 같은 방향으로 가던 두 차의 관계 (B 도표 차19~21, 41~48의 lead_order, side_in_pair, stop_state, started_after_stop)
# 거리·속도는 박스 높이로 나눠서 카메라와의 거리 영향을 줄임 (zone_events.STOP_NEAR와 같은 생각)
SAME_DIR_DEG = 45   # 충돌 직전 두 진행 방향의 차이가 이보다 작으면 같은 방향
LOOK_BACK = 5       # 위치를 비교할 프레임: 충돌 이만큼 전 (부딪혀 밀리기 전)
LEAD_MIN_H = 0.5    # 진행 방향 축에서 두 차 위치 차이가 박스 높이의 이 배보다 작으면 앞뒤를 못 가림 (나란히)
SIDE_MIN_H = 0.3    # 옆 방향 차이가 이보다 작으면 좌우를 못 가림 (한 줄로)
REAR_LAT_H = 1.0    # 서 있는 차를 들이받은 경우: 옆으로 이만큼 안이어야 같은 차로 앞뒤로 봄
STOPPED_HS = 0.15   # 1초에 자기 박스 높이의 이 배보다 덜 움직이면 멈춘 것
RESTART_SEC = 3     # 충돌 전 이 시간 안에 멈췄다 출발했으면 started_after_stop
STOP_RUN = 5        # 멈춤으로 볼 연속 프레임 (zone_events.STOP_HOLD와 같음)
EARLY_WIN = 3       # 꺾기 전 방향: 충돌 EARLY_WIN·WIN 전부터 WIN 전까지


def speed_hs(tracks, tid, f1, f2, fps):
    """f1~f2 동안 1초에 자기 박스 높이의 몇 배를 움직였나. 그 구간에 안 보였으면 None"""
    by = {r["frame"]: r for r in tracks[tid]["frames"]}
    fs = [f for f in range(f1, f2 + 1) if f in by]
    if len(fs) < 2 or fs[-1] == fs[0]:
        return None
    p, q = by[fs[0]], by[fs[-1]]
    h = (p["bbox"][3] + q["bbox"][3]) / 2
    d = math.hypot(q["pos"][0] - p["pos"][0], q["pos"][1] - p["pos"][1])
    return d / ((fs[-1] - fs[0]) / fps) / max(h, 1e-6)


def started_after_stop(tracks, tid, f0, fps):
    """충돌 전 RESTART_SEC 안에 STOP_RUN 프레임 넘게 멈췄다가, 충돌 직전에는 움직이고 있었는지.
    그 구간을 못 봤으면 None"""
    f1 = f0 - int(RESTART_SEC * fps)
    frames = {r["frame"] for r in tracks[tid]["frames"]}
    if f1 not in frames or f0 not in frames:
        return None
    moving_now = (speed_hs(tracks, tid, f0 - LOOK_BACK, f0, fps) or 0) >= STOPPED_HS
    run = 0
    for f in range(f1, f0 - LOOK_BACK):
        s = speed_hs(tracks, tid, f, f + LOOK_BACK, fps)
        run = run + 1 if s is not None and s < STOPPED_HS else 0
        if run >= STOP_RUN:
            return moving_now
    return False


def pair_motion(tracks, a, b, f0, fps):
    """두 당사자의 같은 방향 관계와 멈춤 상태. 반환: {궤적: {사실: 값}} (모르면 None)
    - stop_state: 충돌 직전 움직였으면 driving. 멈춰 있었으면 None (앞선 사고인지 주정차인지는 질문)
    - stationary_at_collision: 충돌 직전 1초(WIN) 동안 멈춰 있었는지 (B 수정요소 "정지" -10, 차32-1)
    - 같은 방향(SAME_DIR_DEG 안)이면 진행 방향 축으로 앞선 쪽이 leading, 오른쪽에 있던 쪽이 right
    - 한쪽이 서 있으면 움직인 차의 방향을 축으로 쓰고, 서 있는 차가 그 앞 같은 줄(REAR_LAT_H 안)이면 앞차로 봄 (추돌)"""
    out = {t: {"stop_state": None, "started_after_stop": None, "stopped_before_collision": None,
               "stationary_at_collision": None, "same_direction": None, "opposite_direction": None, "lead_order": None, "side_in_pair": None}
           for t in (a, b)}
    # 사용자가 직접 표시한 당사자는 추적기로 따라간 궤적이라 충돌 전 구간이 자주 틀림(맞게 따라간 비율 33~40%).
    # 방향·멈춤을 재지 않고 질문에 맡김 (cc_190506, 200303 자전거가 "같은 방향"으로 잘못 잡혔음)
    if any(tracks[t].get("source") == "user" for t in (a, b)):
        return out
    for t in (a, b):
        out[t]["started_after_stop"] = started_after_stop(tracks, t, f0, fps)
    sp = {t: speed_hs(tracks, t, f0 - WIN, f0, fps) for t in (a, b)}
    stopped = {t: sp[t] is not None and sp[t] < STOPPED_HS for t in (a, b)}
    for t in (a, b):
        out[t]["stopped_before_collision"] = stopped[t] if sp[t] is not None else None
        out[t]["stationary_at_collision"] = out[t]["stopped_before_collision"]
        if sp[t] is not None and not stopped[t]:
            out[t]["stop_state"] = "driving"
    h = {t: heading(tracks, t, f0 - WIN, f0) for t in (a, b)}
    movers = [t for t in (a, b) if sp[t] is not None and not stopped[t] and math.hypot(*h[t]) >= MIN_DISP]
    # 충돌 직전 서 있던 차는 멈추기 전에 움직이던 방향으로 본다. 서 있는 차 앞으로 다른 차가 왔다고 추돌로 단정하면
    # 마주 오다 회전한 사고(cc_160316)를 추돌로 잘못 봄. 한 번도 안 움직였으면(주차 차) 방향을 모름
    # 서 있다고 본 차의 아주 느린 밀림(cc_200511 트럭)은 방향으로 쓰지 않음
    for t in (a, b):
        if t not in movers:
            h[t] = moved_heading(tracks, t, f0, fps) or (0.0, 0.0)
    known = [t for t in (a, b) if t in movers or math.hypot(*h[t]) >= MIN_DISP]
    if len(known) == 2:
        ang = abs(turn_angle(h[a], h[b]))
        same = ang < SAME_DIR_DEG
        for t in (a, b):   # 마주 오는 방향 (중앙선 침범·교행 질문을 고를 때 씀, situation.contexts)
            out[t]["opposite_direction"] = ang > 180 - SAME_DIR_DEG
        axis = (h[a][0] + h[b][0], h[a][1] + h[b][1])
        # 한 차가 회전하는 중에 부딪히면 직전 1초 방향은 벌어짐. 꺾기 전(그 앞 2초) 방향이 같았으면 같은 방향으로 가다가
        # 한 차가 꺾은 사고 (cc_180420: 우회전 차 직전 80°, 그 전 32° / 직진 차 9°, 3°. 차19 "직진 대 앞차 회전")
        if not same and ang < 180 - SAME_DIR_DEG:
            early = {t: heading(tracks, t, f0 - EARLY_WIN * WIN, f0 - WIN) for t in (a, b)}
            if all(math.hypot(*early[t]) >= MIN_DISP for t in (a, b)) \
                    and abs(turn_angle(early[a], early[b])) < SAME_DIR_DEG:
                same = True
                axis = (early[a][0] + early[b][0], early[a][1] + early[b][1])
    elif len(movers) == 1:
        same, axis = None, h[movers[0]]
    else:
        return out
    n = math.hypot(*axis)
    if same is False or n == 0:
        for t in (a, b):
            out[t]["same_direction"] = same
        return out
    ux, uy = axis[0] / n, axis[1] / n
    fr = f0 - LOOK_BACK
    pa, pb = pos_at(tracks, a, fr), pos_at(tracks, b, fr)
    hbox = (box_h(tracks, a, fr) + box_h(tracks, b, fr)) / 2 or 1e-6
    dx, dy = pb[0] - pa[0], pb[1] - pa[1]
    along = (dx * ux + dy * uy) / hbox            # +면 b가 앞
    lateral = (dx * -uy + dy * ux) / hbox         # +면 b가 오른쪽 (화면 y가 아래로 커서 오른쪽 법선이 (-uy, ux))
    if same is None:   # 한쪽이 서 있음: 같은 줄 앞에 있으면 추돌로 보고 같은 방향
        mover = movers[0]
        other = b if mover == a else a
        ahead = along if mover == a else -along
        if ahead < LEAD_MIN_H or abs(lateral) > REAR_LAT_H:
            return out
        same = True
        out[other]["lead_order"], out[mover]["lead_order"] = "leading", "following"
    else:
        if along >= LEAD_MIN_H:
            out[b]["lead_order"], out[a]["lead_order"] = "leading", "following"
        elif along <= -LEAD_MIN_H:
            out[a]["lead_order"], out[b]["lead_order"] = "leading", "following"
        if lateral >= SIDE_MIN_H:
            out[b]["side_in_pair"], out[a]["side_in_pair"] = "right", "left"
        elif lateral <= -SIDE_MIN_H:
            out[a]["side_in_pair"], out[b]["side_in_pair"] = "right", "left"
    for t in (a, b):
        out[t]["same_direction"] = same
    return out


def moved_heading(tracks, tid, f0, fps):
    """충돌 전 마지막으로 움직이던 1초(WIN)의 진행 방향. 충돌 전에 한 번도 안 움직였으면 None"""
    first = tracks[tid]["frames"][0]["frame"]
    for f in range(f0 - WIN, first - 1, -LOOK_BACK):
        s = speed_hs(tracks, tid, f, f + WIN, fps)
        if s is not None and s >= STOPPED_HS:
            hd = heading(tracks, tid, f, f + WIN)
            if math.hypot(*hd) >= MIN_DISP:
                return hd
    return None


def box_h(tracks, tid, f):
    recs = {r["frame"]: r for r in tracks[tid]["frames"]}
    f = max(min(recs), min(max(recs), f))
    return recs[f]["bbox"][3]


def entry_order(entries, a, b, fps):
    ea, eb = entries.get(a), entries.get(b)
    if not (isinstance(ea, dict) and isinstance(eb, dict)):
        return None

    def judge(diff):
        if abs(diff) < SAME_TIME_SEC:
            return "same_time"
        return a if diff > 0 else b

    nominal = (eb["frame"] - ea["frame"]) / fps
    first = judge(nominal)
    alts = (ea["frame_outer"], ea["frame_inner"], eb["frame_outer"], eb["frame_inner"])
    if None in alts:
        return {"first": first, "diff_sec": round(nominal, 3), "diff_range_sec": None, "robust": False}
    lo = (eb["frame_outer"] - ea["frame_inner"]) / fps
    hi = (eb["frame_inner"] - ea["frame_outer"]) / fps
    return {"first": first, "diff_sec": round(nominal, 3),
            "diff_range_sec": [round(lo, 3), round(hi, 3)],
            "robust": judge(lo) == judge(hi) == first}

def unknown_items(parties, zones, f0, lights, c, pairs, several, closed=None, at_intersection=False):
    items = []
    for tid, p in parties.items():
        # 사용자가 표시한 당사자는 추적기로 따라간 궤적이라 충돌 전 구간이 짧거나 틀릴 수 있음
        # → 궤적에서 나온 사실(진행 방향, 온 길, 진입 순서)은 추정값으로만 보여 주고 항상 물음
        user = p.get("source") == "user"
        if p["movement"] == "unknown" or user:
            items.append({
                "field": f"parties.{tid}.movement",
                "model_guess": p["movement_guess"] if p["movement"] == "unknown" else p["movement"],
                # 문장에 당사자 번호를 넣음. 그림 없이 문장만 보는 화면에서 누구 얘기인지 몰랐음 (앱 에뮬레이터 시험 11-03)
                "question": f"{tid}번 차는 어느 방향으로 가고 있나요?",
                "answer_type": "choice",
                # 진로 변경·후진은 B 도표가 진행 방향 값으로 씀 (차43, 47, 31-4)
                "options": ["straight", "left_turn", "right_turn", "u_turn", "lane_change", "reverse", "unknown"],
                "choices": ["직진", "좌회전", "우회전", "유턴", "진로 변경 (차로 바꾸기)", "후진", "모름"],
                "evidence_frame": max(f0 - WIN, p["first_frame"]),
            })
        # 들어온 길·교차로 진입 순간은 교차로에서만 (주차장·회전교차로·교차로 아닌 길에는 진입로가 없어서 묻지 않음.
        # 평가를 주차장 등으로 넓혔을 때 cc_120407 등에서 쓰이지도 않는 이 질문이 남았음)
        if at_intersection and (user or p["entry_from"] is None):
            dirs = [d for d in DIRS if d != closed]   # 삼거리면 길이 없는 쪽은 보기에서 뺌
            # 근거 장면: 교차로에 들어가기 직전 (모르면 충돌 1초 전). 예전엔 처음 보인 프레임이라 차가 화면 끝에
            # 작게만 보였음 (앱 에뮬레이터 시험, cc_211208 0.0초)
            ent = zones["intersection_entries"].get(tid)
            near = ent["frame"] - ENTRY_BEFORE if isinstance(ent, dict) else f0 - WIN
            items.append({
                "field": f"parties.{tid}.entry_from",
                "model_guess": p["entry_from"],
                "question": f"{tid}번은 어느 쪽 길에서 왔나요?",
                "answer_type": "choice",
                "options": dirs,
                "choices": [DIR_NAMES[d] for d in dirs],
                "evidence_frame": max(near, p["first_frame"]),
            })
        if at_intersection and zones["intersection_entries"].get(tid) == "unknown" and not user:   # 사용자 당사자는 진입 순서 질문으로 받음
            seg = next((s for s in zones["timelines"][tid]["segments"]
                        if zones["zone_types"].get(s["zone"]) == "intersection"), None)
            items.append({
                "field": f"parties.{tid}.intersection_entry",
                "question": f"{tid}번 차가 교차로에 들어간 순간을 골라 주세요",
                "answer_type": "frame",
                "options": None,
                "choices": None,
                "evidence_frame": seg["start"] if seg else p["first_frame"],
            })
        votes = p["cls_votes"]
        # 표가 갈렸거나, 이륜차 보정 규칙이 다수결을 뒤집었거나(cc_200303: car 85표인 SUV가 이륜차가 됨),
        # 사람인데 탈것을 탄 듯 빠르면(cc_200702: 오토바이 탄 사람이 person으로만 잡힘) 확인
        if (max(votes.values()) / sum(votes.values()) < CLS_SURE
                or p["cls_from"] in ("two_wheeler_rule", "fast_person")):
            items.append({
                "field": f"parties.{tid}.cls",
                "model_guess": p["cls"],
                "question": f"{tid}번의 종류는 무엇인가요?",
                "answer_type": "choice",
                "options": CLS_OPTIONS,
                "choices": CLS_CHOICES,
                "evidence_frame": max(f0 - 5, p["first_frame"]),
            })
    if at_intersection:
        # 교차로에서만 (주차장 등에서 먼 신호등이 잡혀 "신호등 있나요?"가 나왔음, cc_190730).
        # 신호등이 보여도 이 교차로를 통제하는 신호가 아닐 수 있음 (먼 교차로, 야간 점멸).
        # 반대로 신호등이 안 잡혀도 화면 밖에 있을 수 있음 (CCTV는 신호등이 작거나 화면 밖인 경우가 많고,
        # cc_210819는 신호 교차로인데 진짜 신호등을 못 잡음). 그래서 교차로면 늘 묻고, 추정값은 "없음"
        items.append({
            "field": "road.signal_present",
            "model_guess": False,
            "question": ("화면에 신호등이 보여요. 이 교차로에 신호등이 있나요?" if lights
                         else "이 교차로에 신호등이 있나요? (화면에는 신호등이 잡히지 않았어요)"),
            "answer_type": "choice",
            "options": [True, False],
            "choices": ["있음", "없음"],
            "evidence_frame": lights[0]["first_frame"] if lights else f0,   # 신호등이 없으면 충돌 장면 (교차로가 보이게)
        })
    if not c.get("confirmed", True) or several:
        items.append({
            "field": "collision.parties",
            "model_guess": [c["a"], c["b"]],
            "question": "서로 부딪힌 두 객체를 골라 주세요",
            "answer_type": "pair",
            "options": [[k["a"], k["b"]] for k in pairs],
            "choices": [f"{k['a']}번 ↔ {k['b']}번 ({k['frame']}프레임{', 충돌 뒤 탐지' if k.get('born') else ''})"
                        for k in pairs],
            "evidence_frame": f0,
        })
    return items

def state_at(states, f):
    """f에 가장 가까운 신호등 색 기록 (light_states.state_at과 같음. torch를 불러오지 않으려고 따로 둠)"""
    return min(states, key=lambda s: abs(s["frame"] - f)) if states else None


SIGNALS = ["green", "green_arrow", "yellow", "red", "flashing_yellow", "flashing_red", "none"]
SIGNAL_NAMES = ["초록", "초록 좌회전 화살표", "노랑", "빨강", "노랑 점멸", "빨강 점멸", "이 차량 쪽 신호등 없음"]


def signal_items(parties, light_states, f0):
    """신호 색 질문 (B의 당사자별 signal_at_entry, signal_at_collision).
    화면의 신호등이 어느 당사자 쪽 신호인지 영상만으로 정할 수 없어서 여기서는 추정값을 넣지 않고, 그 장면에서 본
    신호등 색을 참고(light_hints)로 붙인다. 사용자가 신호등을 진입로에 연결하면(lights.<id>.approach) 그 신호등 색이
    추정값이 된다 (src/app/signals.py, pipeline.signal_guesses).
    "신호등이 있다"고 답했을 때만 보인다 (depends_on, src/app/answers.remaining)"""
    def hints(f):
        out = []
        for t, states in light_states.items():
            s = state_at(states, f)
            if s and abs(s["frame"] - f) <= 2 * LIGHT_NEAR:
                out.append({"track": t, "frame": s["frame"], "color": s["color"], "p": s["p"]})
        return out

    items = []
    for tid, p in parties.items():
        fe = p["intersection_entry"]["frame"] if p["intersection_entry"] else max(f0 - WIN, p["first_frame"])
        changed = any(len({s["color"] for s in states if fe <= s["frame"] <= f0}) > 1
                      for states in light_states.values())
        for key, f, q in (("signal_at_entry", fe, f"{tid}번 차가 교차로에 들어갈 때, {tid}번 차 쪽 신호등은 무슨 색이었나요?"),
                          ("signal_at_collision", f0, f"부딪힐 때, {tid}번 차 쪽 신호등은 무슨 색이었나요?")):
            # 충돌 순간 색은 진입 뒤 화면 신호등 색이 바뀌었을 때만 따로 물음 (안 바뀌었으면 진입 때 답을 같이 씀)
            if key == "signal_at_collision" and not changed:
                continue
            items.append({"field": f"parties.{tid}.{key}", "model_guess": None, "question": q,
                          "answer_type": "choice", "options": SIGNALS, "choices": SIGNAL_NAMES,
                          "evidence_frame": f, "light_hints": hints(f),
                          "depends_on": {"road.signal_present": True}})
    return items


def run(out_dir="outputs"):
    tracks_path = os.path.join(out_dir, "tracks_final.json")
    coll_path = os.path.join(out_dir, "collision.json")
    zones_path = os.path.join(out_dir, "zones.json")
    out_path = os.path.join(out_dir, "facts.json")

    with open(tracks_path, encoding="utf-8") as f:
        data = json.load(f)
    with open(coll_path, encoding="utf-8") as f:
        coll = json.load(f)
    with open(zones_path, encoding="utf-8") as f:
        zones = json.load(f)
    with open(zones["scene"], encoding="utf-8") as f:   # 진입로 영역 (나갈 쪽 추정에 씀)
        scene = json.load(f)

    fps = data["fps"]
    tracks = data["tracks"]

    camera_type = None
    cam_path = os.path.join(out_dir, "camera.json")
    if os.path.exists(cam_path):
        with open(cam_path, encoding="utf-8") as f:
            camera_type = json.load(f)["camera_type"]
    lights = [{"track": tid, "pos": tr["frames"][0]["pos"],
               "first_frame": tr["frames"][0]["frame"], "frames": len(tr["frames"])}
              for tid, tr in tracks.items() if tr["cls"] == "traffic_light"]

    if not coll["events"]:
        raise SystemExit("충돌 이벤트가 없어서 facts를 만들 수 없어요")

    c = coll["events"][0]    # 첫 번째 충돌
    f0 = c["frame"]
    zc = next(z for z in zones["collisions"] if z["frame"] == f0)

    parties = {}
    for tid in (c["a"], c["b"]):
        tr = tracks[tid]
        first = tr["frames"][0]["frame"]
        segs = zones["timelines"][tid]["segments"]
        origin = next((s["zone"] for s in segs if s["zone"] != "out_of_roi"), "unknown")
        enter = next((e for e in zones["events"]
                      if e["track"] == tid and e["zone_type"] == "carriageway"), None)
        entry = zones["intersection_entries"].get(tid)

        if isinstance(entry, dict):
            fe = entry["frame"]
            h_start, start_from = heading(tracks, tid, fe - WIN, fe), "intersection_entry"
        else:
            h_start, start_from = heading(tracks, tid, first, first + WIN), "track_start"
        # 진행 방향은 충돌로 밀리기 전까지만 봄 (밀린 프레임 fm, 안 밀렸으면 충돌 프레임)
        push = pushed_back(tracks, tid, entry["frame"] if isinstance(entry, dict) else first, f0)
        fm = push if push is not None else f0
        h_end = heading(tracks, tid, fm - WIN, fm)
        deg = turn_angle(h_start, h_end)

        d_start, d_end = math.hypot(*h_start), math.hypot(*h_end)
        guess = None
        if d_start < MIN_DISP or d_end < MIN_DISP:
            mv, turn = "unknown", None
        else:
            mv, turn = movement(deg), round(deg, 1)
            near_turn = min(abs(abs(deg) - TURN_DEG), abs(abs(deg) - U_TURN_DEG)) < BORDER_DEG
            short = min(d_start, d_end) < MIN_DISP * BORDER_DISP
            if near_turn or short:
                mv, guess = "unknown", mv
        
        mv_from = "angle"
        zone_mv= None
        if isinstance(entry, dict) and entry["exit_frame"] is not None and entry["exit_frame"] <= fm:
            zone_mv = zone_movement(entry["from_direction"], entry["exit_direction"])
        guess_from = "angle" if guess else None
        if zone_mv:
            mv, guess, mv_from, guess_from = zone_mv, None, "zones", None
        elif isinstance(entry, dict):
            # 교차로 안에서 부딪혀 나간 쪽을 못 봄: 충돌 직전 방향을 늘려 나갈 진입로를 추정 (추정으로만 씀)
            exit_dir = ray_exit(scene, pos_at(tracks, tid, fm), h_end, entry["from_direction"])
            ray_mv = zone_movement(entry["from_direction"], exit_dir)
            if ray_mv:
                mv, guess, guess_from = "unknown", ray_mv, "ray"
            elif mv != "unknown":
                mv, guess, guess_from = "unknown", mv, "angle"

        # 주차장에서 충돌 뒤 반대로 다시 출발했으면(후진 출차 단서) 각도로 잰 방향은 그 꺾임 때문에 유턴·좌회전으로
        # 잘못 나와서 확정하지 않고 질문으로 (cc_160413·181103·190730)
        cusp = zones["road_type"] == "parking_lot" and reverse_cusp(tracks, tid, f0)
        if cusp and mv != "unknown":
            mv, guess, guess_from = "unknown", mv, mv_from

        cls_from = tr.get("cls_from", "majority")
        # 사람으로 잡혔는데 충돌 전에 빨랐으면 탈것을 탄 사람일 수 있음 (finalize_tracks의 fast_person과 같은 기준).
        # 궤적 전체 중앙값은 부딪힌 뒤 넘어져 멈춘 구간이 길면 낮아져서 놓침 (cc_210313 자전거: 충돌 전 2.21, 전체 0.18)
        if tr["cls"] == "pedestrian" and cls_from == "majority":
            pre = [r for r in tr["frames"] if not r.get("interp") and r["frame"] <= f0]
            if len(pre) > 5 and finalize_tracks.heights_per_sec(pre, fps) >= finalize_tracks.RIDER_HS:
                cls_from = "fast_person"

        parties[tid] = {
            "cls": tr["cls"],
            "cls_votes": tr["cls_votes"],
            "cls_from": cls_from,   # majority / two_wheeler_rule / fast_person / user
            "source": tr.get("source", "model"),   # user: 사용자가 박스로 표시한 당사자
            "first_frame": first,
            "origin_zone": origin,
            "origin_approach": entry["from"] if isinstance(entry, dict) else None,
            "entry_from": entry["from_direction"] if isinstance(entry, dict) else None,
            "enter_road": {"frame": enter["frame"], "t": enter["t"]} if enter else None,
            "zone_at_collision": zc["party_zones"][tid],
            "movement": mv,
            "movement_guess": guess,
            "movement_guess_from": guess_from,   # angle: 각도, ray: 충돌 직전 방향을 늘려 본 나갈 진입로
            # 주차장: 충돌 뒤 반대로 다시 출발함 (후진 출차 단서). 통로 차도 부딪힌 뒤 뒤로 빼면 같은 모양이라,
            # "주차 칸에서 나오던 중"이라고 답한 당사자에게만 후진을 추정값으로 씀 (pipeline.parking_guesses)
            "reverse_cusp": cusp if zones["road_type"] == "parking_lot" else None,
            "movement_from": mv_from,
            "turn_deg": turn,
            "disp_start": round(d_start, 4),
            "disp_before_collision": round(d_end, 4),
            "heading_start": [round(v, 4) for v in h_start],
            "heading_start_from": start_from,
            "heading_before_collision": [round(v, 4) for v in h_end],
            "direction_before_collision": screen_dir(h_end) if d_end >= MIN_DISP else "unknown",
            "approach_speed": c["approach_speed"][tid],
            "stop_frame": c["stop_frame"][tid],
            "intersection_entry": ({"frame": entry["frame"], "t": entry["t"]}
                                   if isinstance(entry, dict) else None),
            "intersection_entry_speed":  (entry["speed"] if isinstance(entry, dict)
                                          else None),
            "stopped_before_entry": entry["stopped_before"] if isinstance(entry, dict) else None,
        }

    # 같은 방향 관계·멈춤 (B: lead_order, side_in_pair, stop_state, started_after_stop)
    for tid, extra in pair_motion(tracks, c["a"], c["b"], f0, fps).items():
        parties[tid].update(extra)

    events = []
    for tid, p in parties.items():
        events.append({"frame": p["first_frame"], "t": round(p["first_frame"] / fps, 3),
                       "type": "appear", "track": tid, "zone": p["origin_zone"]})
    for e in zones["events"]:
        if e["track"] in parties:
            events.append({"frame": e["frame"], "t": e["t"], "type": "enter_zone",
                           "track": e["track"], "from": e["from"], "zone": e["zone"],
                           "zone_type": e["zone_type"]})
    events.append({"frame": f0, "t": c["t"], "type": "collision",
                "a": c["a"], "b": c["b"], "zone": zc["zone"]})
    for tid, sf in c["stop_frame"].items():
        if sf is not None:
            events.append({"frame": sf, "t": round(sf / fps, 3), "type": "stop", "track": tid})
    events.sort(key=lambda e: e["frame"])

    # 보기: 순위가 높은 충돌 PAIR_OPTIONS개 + 닿은 채 나타난 쌍. 확정 충돌이 수십 개인 영상이 있어서 다 넣지 않음
    pairs = (coll["events"] if c.get("confirmed", True) else coll.get("candidates", []))[:PAIR_OPTIONS]
    pairs = pairs + coll.get("born_candidates", [])[:BORN_OPTIONS]
    at_intersection = str(zones["road_type"]).startswith("intersection")
    unknowns = unknown_items(parties, zones, f0, lights, c, pairs, len(coll["events"]) > 1,
                             scene.get("closed_side"), at_intersection)
    light_states = {}
    lights_path = os.path.join(out_dir, "lights.json")
    if os.path.exists(lights_path):   # light_states.py가 남긴 신호등별 프레임 색
        with open(lights_path, encoding="utf-8") as f:
            light_states = json.load(f)["lights"]
    if at_intersection:   # 신호등이 있다고 답하면 보이는 신호 색 질문 (신호등이 안 잡혀도 물음)
        unknowns += signal_items(parties, light_states, f0)

    entries = zones["intersection_entries"]
    order = entry_order(entries, c["a"], c["b"], fps)
    user_pair = any(parties[t]["source"] == "user" for t in (c["a"], c["b"]))
    if (order and not order["robust"]) or user_pair:
        seen = [e["frame"] for e in (entries.get(c["a"]), entries.get(c["b"])) if isinstance(e, dict)]
        unknowns.append(({
            "field": "intersection_entry_order",
            "model_guess": order["first"] if order else None,
            "question": "두 차 중 어느 쪽이 먼저 교차로에 들어갔나요?",
            "answer_type": "choice",
            "options": [c["a"], c["b"], "same_time"],
            "choices": [f"{c['a']}번", f"{c['b']}번", "거의 동시에"],
            "evidence_frame": min(seen) if seen else max(f0 - WIN, 0),
        }))
    # 도로 정보: B가 facts.road에서 읽음. 모르면 넣지 않음(None)
    # - 교차로 형태: 장면(scene.json)의 junction_type. 사용자가 삼거리로 정하고 길 없는 쪽을 고르면 "t",
    #   아니면 "cross" (예전 장면에는 이 값이 없어서 사거리로 봄)
    # - 신호등: 교차로면 늘 질문(unknown_items). 답이 없으면 추정값 "없음"으로 판정(fill_guesses).
    #   교차로가 아닌 장면에서 신호등이 하나도 안 잡히면 없음으로 확정
    # - 도로 폭: 네 모서리로는 추정 못 함 (원근 때문에 화면 깊이 방향 변이 늘 짧게 찍혀
    #   11개 장면 모두 남북 폭이 동서 폭의 1.8~3.9배로 나옴). 항상 질문, 답이 없으면 "비슷함"을 기본값으로 판정
    # 장소: 모서리를 찍을 때 사용자가 고른 장소 종류(scene.json의 road_type, pipeline.set_scene의 place).
    # 회전교차로·주차장·교차로 아닌 길은 영상으로 알아볼 수 없어서 사용자에게 받음 (B의 scene.location 값과 같음)
    place = zones["road_type"] if zones["road_type"] in PLACES else None
    road = {"location": place,
            "junction_type": scene.get("junction_type", "cross") if at_intersection else None,
            "signal_present": False if not at_intersection else None,
            "road_width": None}
    if at_intersection:
        # 규칙(차12~): 두 도로 폭이 같은지, 다르면 누가 넓은 도로에 있었는지
        unknowns.append({
            "field": "road.wider_road",
            "model_guess": "equal",   # 추정이 아니라 기본값. 앱은 "기본값"으로 표시
            "question": "교차하는 두 도로 중 어느 쪽이 더 넓은가요?",
            "answer_type": "choice",
            "options": ["equal", "north_south", "east_west"],
            "choices": ["폭이 비슷함", "화면 위아래로 지나는 도로", "화면 좌우로 지나는 도로"],
            "evidence_frame": c["frame"],   # 도로 질문은 충돌 장면 (0프레임은 당사자가 안 보일 때가 많음)
            "default": True,
        })
        # 규칙(차14 등)이 골목길(road_class: side_street)인지, 정면 충돌 규칙(차31~)이 중앙선 유무를 요구.
        # B 변환기는 중앙선 없는 도로를 골목길로 봄. 사용자가 답하기 쉬운 "중앙선이 있나요?"로 묻고, 추정값은 없음
        unknowns.append({
            "field": "road.center_line",
            "model_guess": None,
            "question": "사고 난 길에 중앙선(가운데 노란 선)이 있나요?",
            "answer_type": "choice",
            "options": [True, False],
            "choices": ["있음", "없음 (골목길)"],
            "evidence_frame": c["frame"],
        })

    facts = {
        "schema_version": "0.2",
        "source": data["source"],
        "video": data["video"],
        "scene": zones["scene"],
        "road_type": zones["road_type"],
        "camera_type": camera_type,
        "traffic_lights_detected": lights,
        "traffic_light_states": light_states,   # 신호등 궤적별 프레임 색 (참고용, 정확도 0.70)
        "road": road,
        "fps": fps,
        "collision": {"frame": f0, "t": c["t"], "a": c["a"], "b": c["b"],
                      "zone": zc["zone"], "pos": c["pos"], "contact": c["contact"],
                      "interp": c["interp"],"confirmed": c.get("confirmed", True)},
        "parties": parties,
        "intersection_entry_order": order,
        "events": events,
        "unknowns": unknowns,
        "params": {"win": WIN, "turn_deg": TURN_DEG, "u_turn_deg": U_TURN_DEG, "min_disp": MIN_DISP,
                   "border_deg": BORDER_DEG, "border_disp": BORDER_DISP, "cls_sure": CLS_SURE,
                   "same_time_sec": SAME_TIME_SEC,
                   "tracks": data["params"], "collision": coll["params"], "zones": zones["params"]},
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=1)

    print(f"도로 종류: {facts['road_type']}")
    print(f"충돌: 프레임 {f0} ({c['t']}초), 위치 {zc['zone']}\n")
    for tid, p in parties.items():
        print(f"ID {tid} ({p['cls']})")
        print(f"  출발 영역: {p['origin_zone']}  | 도로 진입: {p['enter_road']}")
        print(f"  진행: {p['movement']} (회전 {p['turn_deg']}도) | 충돌 직전 방향: {p['direction_before_collision']}")
        print(f"  처음 이동 {p['heading_start']} → 충돌 직전 이동 {p['heading_before_collision']}")
        print(f"  접근 속도 {p['approach_speed']} | 정지 프레임 {p['stop_frame']}\n")
    print("=== 사건 순서 ===")
    for e in events:
        print(f"  {e['t']:>6}초 (프레임 {e['frame']:>3}) | {e['type']} | "
            + ", ".join(f"{k}={v}" for k, v in e.items() if k not in ('frame', 't', 'type')))
    print("\n=== 확인 필요 (unknowns) ===")
    for u in unknowns:
        print(f"  {u['field']} | {u['question']} | 근거 프레임 {u['evidence_frame']}")
    if not unknowns:
        print("  없음")
    print(f"\n저장: {out_path}")
    return out_path

if __name__ == "__main__":
    run()