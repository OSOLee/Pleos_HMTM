"""앱 분석 흐름을 세 단계 함수로 나눈 것 (서버와 run_app.py가 같이 씀, docs/backend.md 5절)

  prepare(case_dir, video, source)          영상을 받자마자: 카메라 확인 → (흔들림 보정) → 배경 그림 → 탐지·추적
  set_scene(case_dir, video, corners, ...)  교차로 네 모서리 → scene.json, scene.jpg
  solve(case_dir, video, answers)           나머지 단계(충돌~사실) → B 판정 → app.json

탐지(prepare)에는 모서리가 필요 없어서, 서버는 영상을 받자마자 prepare를 돌리고 사용자가 모서리를 찍는 동안
기다린다. 결과 폴더(case_dir)의 파일 구조는 예전 run_app.py 결과 폴더와 같다.

사용자 입력이 잘못되면 InputError(code, message)를 던진다. message는 사용자에게 그대로 보여 줄 한국어다
(서버는 422, run_app.py는 안내 한 줄로 바꿈). 그 밖의 예외는 서버 오류다.
"""
import json
import os
import time

import cv2
import numpy as np

from src.analyze import (camera_check, track_video, stitch_tracks, finalize_tracks, detect_collision,
                         zone_events, build_facts, light_states, stabilize)
from src.app import answers as ans, chapters, frames, judge_bridge, signals, situation, slowdown, tap_track
from src.make_scene import build_scene
from tools import draw_scene

JUDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "judge")   # 판정 모듈 폴더 (backend/judge)
MIN_CORNER_AREA = 0.001        # 네 모서리가 감싸는 넓이 (화면 넓이 비율) 하한
CORNER_MIN_MOVE = 0.05         # 모서리 검사에서 움직인 차로 보는 궤적 처음~끝 거리 (화면 비율)
CORNER_MIN_THRU = 0.1          # 움직인 차 중 교차로를 지나간 비율이 이보다 작으면 모서리 경고
CORNER_MAX_OUT = 0.4           # 궤적 점 중 어느 영역에도 안 든 비율이 이보다 크면 모서리 경고
BG_FRAMES = 15                 # 배경 그림을 만들 때 고르게 뽑는 프레임 수


class InputError(Exception):
    """사용자 입력 문제. code는 앱이 구분할 이름, message는 사용자에게 보여 줄 한국어"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)


def stage(name, fn, log):
    t0 = time.perf_counter()
    fn()
    log[name] = round(time.perf_counter() - t0, 2)


def analysis_video(case_dir, video):
    """분석에 쓰는 영상. 흔들리는 CCTV는 첫 프레임에 맞춘 보정 영상(stabilized.mp4)"""
    stab = os.path.join(case_dir, "stabilized.mp4")
    return stab if os.path.exists(stab) else video


def check_video(video):
    """영상을 열어 첫 프레임을 읽을 수 있는지. 없는 파일, 영상이 아닌 파일, 깨진 파일을 먼저 걸러냄"""
    cap = cv2.VideoCapture(video)
    ok, _ = cap.read()
    cap.release()
    if not ok:
        raise InputError("video_unreadable", "영상을 읽지 못했어요. 다른 파일로 다시 올려 주세요.")


# ---------------------------------------------------------------- 1. 준비 (영상을 받자마자)

def unsupported(case_dir, name, reason, message):
    save({"video": name, "status": "unsupported", "reason": reason, "message": message},
         os.path.join(case_dir, "app.json"))


def background(video, out_path):
    """프레임 BG_FRAMES장의 픽셀별 중앙값. 지나가는 차가 지워져 교차로가 가려지지 않는 그림 (모서리 찍기용)"""
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    imgs = []
    for k in range(BG_FRAMES):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(k * max(n - 1, 0) / (BG_FRAMES - 1)))
        ok, img = cap.read()
        if ok:
            imgs.append(img)
    cap.release()
    if imgs:
        cv2.imwrite(out_path, np.median(np.stack(imgs), axis=0).astype(np.uint8))


def prepare(case_dir, video, source="cctv", name=None, log=None, progress=None):
    """카메라 확인 → 흔들리면 보정 → 배경 그림 → 탐지·추적. 이미 탐지했으면(tracks.json) 다시 안 함.
    progress: 탐지 진행률을 받는 함수 (track_video.run). 반환: "ready" 또는 "unsupported" (이때 app.json에 이유가 남음)"""
    os.makedirs(case_dir, exist_ok=True)
    name = name or os.path.splitext(os.path.basename(video))[0]
    log = {} if log is None else log
    # 영상 종류는 사용자가 고른 것을 믿는다. 블랙박스 분석은 아직 없어서 바로 안내
    if source == "blackbox":
        unsupported(case_dir, name, "blackbox_selected",
                    "블랙박스 영상은 아직 분석할 수 없어요. 지금은 CCTV 영상만 분석할 수 있어요.")
        return "unsupported"
    if os.path.exists(os.path.join(case_dir, "tracks.json")):
        return "ready"
    check_video(video)
    stage("camera", lambda: camera_check.run(video, case_dir), log)
    if load(os.path.join(case_dir, "camera.json"))["camera_type"] == "blackbox":
        # 카메라가 움직임: 같은 장면이 흔들리는 CCTV(휴대폰으로 모니터를 찍음 등)면 첫 프레임에 맞춰 보정.
        # 첫 프레임과 특징점이 거의 안 맞으면 CCTV를 골랐어도 앞으로 달리는 블랙박스로 보고 다시 확인하게 함
        # (안전장치. 서 있는 블랙박스는 여기서 못 막음)
        fixable, med = stabilize.check(video)
        if not fixable:
            unsupported(case_dir, name, "looks_like_blackbox",
                        "카메라가 차와 함께 움직이는 영상(블랙박스)으로 보여요. CCTV 영상이 맞는지 확인해 주세요. "
                        "지금은 CCTV처럼 한 곳을 찍은 영상만 분석할 수 있어요.")
            print(f"블랙박스로 보여 중단 (첫 프레임과 맞는 점 {med})")
            return "unsupported"
        stage("stabilize", lambda: stabilize.run(video, case_dir), log)
    v = analysis_video(case_dir, video)
    stage("background", lambda: background(v, os.path.join(case_dir, "background.jpg")), log)
    stage("tracks", lambda: track_video.run(v, case_dir, stabilized=(v != video), progress=progress), log)
    return "ready"


# ---------------------------------------------------------------- 2. 장면 (교차로 모서리)

def hull_area(pts):
    """점들을 감싸는 볼록 다각형의 넓이. 찍는 순서와 상관없이 네 점이 얼마나 퍼져 있는지 봄"""
    hull = cv2.convexHull(np.array(pts, np.float32)).reshape(-1, 2)
    return 0.5 * abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(hull, np.roll(hull, -1, axis=0))))


def parse_corners(text):
    """명령줄 모서리 "x,y x,y x,y x,y" → [(x, y), ...]"""
    try:
        return [tuple(float(v) for v in c.split(",")) for c in text.split()]
    except ValueError:
        raise InputError("corners_invalid", '모서리 좌표는 숫자로 "x,y x,y x,y x,y" 모양이어야 해요')


def set_scene(case_dir, video, corners, closed=None, frame_ref=0, place="intersection"):
    """네 모서리로 교차로·진입로 영역(scene.json)과 확인 그림(scene.jpg)을 만든다. 탐지 전에 해도 됨
    closed: 삼거리면 길 없는 쪽 (north/east/south/west, 화면 기준)
    place: 장소 종류. intersection(교차로) / roundabout(회전교차로) / parking_lot(주차장) / straight(교차로 아닌 길).
    영상으로 알아볼 수 없어서 사용자가 고름. 교차로가 아니면 네 모서리는 사고가 난 곳 둘레를 찍음"""
    if place not in build_facts.PLACES:
        raise InputError("place_invalid", f"장소 종류는 {build_facts.PLACES} 중 하나여야 해요")
    if place != "intersection" and closed:
        raise InputError("closed_invalid", "길 없는 쪽(삼거리)은 교차로에서만 고를 수 있어요")
    os.makedirs(case_dir, exist_ok=True)
    try:
        corners = [tuple(float(v) for v in c) for c in corners]
    except (TypeError, ValueError):
        raise InputError("corners_invalid", "모서리 좌표는 숫자 [x, y] 네 개여야 해요")
    if len(corners) != 4 or any(len(c) != 2 for c in corners):
        raise InputError("corners_count", "모서리는 정확히 4개여야 해요")
    if not all(0 <= v <= 1 for c in corners for v in c):
        raise InputError("corners_range", "모서리 좌표는 화면 비율 0~1이어야 해요 (화면 밖이면 0 또는 1)")
    if hull_area(corners) < MIN_CORNER_AREA:   # 네 점이 한곳에 몰리면 장면을 만들다 멈췄음
        raise InputError("corners_too_close", "네 모서리가 너무 붙어 있어요. 교차로 네 모서리를 떨어뜨려 찍어 주세요")
    if closed not in (None, "north", "east", "south", "west"):
        raise InputError("closed_invalid", "길 없는 쪽은 north, east, south, west 중 하나여야 해요")
    check_video(video)
    scene_path = os.path.join(case_dir, "scene.json")
    save(build_scene(corners, video, frame_ref, road_type=place, closed=closed), scene_path)
    # 교차로·진입로 영역을 기준 프레임에 겹친 그림. 모서리를 잘 찍었는지 바로 확인
    draw_scene.run(video, scene_path, os.path.join(case_dir, "scene.jpg"))
    return scene_path


# ---------------------------------------------------------------- 3. 판정 (나머지 단계 + 답 반영)

def check_answers(user):
    """답 모양 검사 (값이 보기에 있는지는 solve 안에서 facts로 봄)"""
    if not isinstance(user, dict):
        raise InputError("answers_shape", '답 파일은 {"질문 field": 답} 모양이어야 해요')
    taps = user.get("user_tracks") or {}
    if not isinstance(taps, dict) or not all(isinstance(t, dict) for t in taps.values()):
        raise InputError("user_tracks_shape",
                         'user_tracks는 {"9001": {"frame": 프레임, "bbox": [x, y, w, h], "cls": 종류}} 모양이어야 해요')
    return user


def load_answers(path):
    """사용자 답 파일 (run_app.py --answers)"""
    try:
        user = load(path)
    except FileNotFoundError:
        raise InputError("answers_missing", f"답 파일을 찾지 못했어요: {path}")
    except json.JSONDecodeError as e:
        raise InputError("answers_json", f"답 파일이 JSON 형식이 아니에요 ({e.lineno}줄 {e.colno}칸: {e.msg})")
    return check_answers(user)


def pair_problem(tracks, pair):
    """사용자가 고른 두 궤적으로 충돌을 만들 수 없는 이유. 문제없으면 None
    반환: (reason, 안내 문구, 보여 줄 프레임 또는 None)"""
    if len(set(pair)) != 2:
        return "pair_invalid", "서로 다른 두 객체를 골라 주세요.", None
    missing = [t for t in pair if t not in tracks]
    if missing:
        return "pair_invalid", f"고른 객체 {', '.join(missing)}번을 찾지 못했어요. 목록에서 다시 골라 주세요.", None
    seen = {t: {r["frame"] for r in tracks[t]["frames"]} for t in pair}
    if seen[pair[0]] & seen[pair[1]]:
        return None
    # 같은 화면에 나온 적이 없음 (예: cc_150101 트럭이 흙먼지 속에서 사라진 뒤에 상대가 처음 잡힘).
    # 앞 객체가 사라진 때와 뒤 객체가 나타난 때의 가운데 장면을 보여 주고, 안 보이는 쪽을 직접 표시하게 함
    a, b = sorted(pair, key=lambda t: min(seen[t]))
    gap = (max(seen[a]) + min(seen[b])) // 2
    return ("pair_not_together",
            f"고른 {a}번({min(seen[a])}~{max(seen[a])}프레임)과 {b}번({min(seen[b])}~{max(seen[b])}프레임)은 "
            "같은 화면에 나온 적이 없어요. 부딪힌 순간에 안 보이는 당사자를 화면에 직접 표시해 주세요.", gap)


def ask_parties(case_dir, video, name, user, log, reason, message, frame=None):
    """부딪힌 두 당사자를 다시 묻는 응답(no_collision). 움직이는 객체를 한 장면에 번호와 함께 그려서
    사용자가 고르거나, 화면에 없는(YOLO가 놓친) 당사자는 박스로 직접 표시하게 함.
    frame을 주면 객체 그림 대신 그 장면을 보여 줌 (직접 표시할 장면)"""
    tracks = load(os.path.join(case_dir, "tracks_final.json"))["tracks"]
    img, f, objs = frames.objects_frame(video, tracks, case_dir)
    if frame is not None:
        f = frame
        img = frames.save(video, [f], case_dir).get(f)
    elif img is None:
        f = load(os.path.join(case_dir, "tracks.json"))["frames_analyzed"] // 2
        img = frames.save(video, [f], case_dir).get(f)
    app = {"video": name, "status": "no_collision", "reason": reason, "message": message,
           "questions": [{"field": "collision.parties", "question": "서로 부딪힌 두 당사자를 골라 주세요",
                          "answer_type": "pair", "options": None, "objects": objs,
                          "evidence_frame": f, "image": img},
                         {"field": "user_tracks", "question": "목록에 없는 당사자를 화면에 박스로 표시하고 종류를 골라 주세요",
                          "answer_type": "boxes", "options": tap_track.CLASSES, "max": 2,
                          "id_from": tap_track.USER_ID_MIN, "evidence_frame": f, "image": img}],
           "answers": user, "timing_sec": log}
    save(app, os.path.join(case_dir, "app.json"))
    return app


def camera_moved(case_dir, f0, fps):
    """흔들림 보정에서 정렬을 확인 못 한 구간이 있으면 안내 (회전·줌하는 CCTV, stabilize.unverified_ranges).
    그 구간은 차 위치가 첫 화면과 어긋났을 수 있다. 충돌 장면이 그 안이면 진행 방향·진입로를 그림으로 확인하게 함"""
    path = os.path.join(case_dir, "stabilize.json")
    ranges = load(path).get("unverified") if os.path.exists(path) else None
    if not ranges:
        return None
    at = any(a <= f0 <= b for a, b in ranges)
    span = ", ".join(f"{a / fps:.1f}~{b / fps:.1f}초" for a, b in ranges)
    msg = ("부딪힌 장면에서 카메라가 크게 줌하거나 돌아가서, 차의 위치와 진행 방향이 정확하지 않을 수 있어요. "
           "질문의 그림을 보고 직접 확인해 주세요." if at else
           f"영상의 {span}는 카메라가 크게 줌하거나 돌아가서 분석이 정확하지 않을 수 있어요.")
    return {"frames": ranges, "at_collision": at, "message": msg}


def corner_check(scene, tracks):
    """찍은 모서리가 차들이 다닌 곳과 안 맞으면 다시 찍어 보라고 안내 (막지는 않음).
    교차로 사고 영상이면 움직인 차 대부분이 교차로를 지나는데, 모서리를 엉뚱한 곳에 찍으면 거의 아무 차도 안 지나거나
    궤적이 어느 영역(교차로·진입로)에도 안 들어간다. 기준값은 모서리 민감도 실험(tools/experiments/sens_corners.py, 360번):
    원래 모서리는 지나간 비율 0.25 이상·영역 밖 점 0.27 이하, 아무 데나 찍으면 0인 경우가 1/4, 영역 밖 0.65~0.91"""
    zones = [np.float32(z["polygon"]) for z in scene.get("zones", [])]
    inter = [np.float32(z["polygon"]) for z in scene.get("zones", []) if z["type"] == "intersection"]
    if not inter:
        return None
    inside = lambda poly, p: cv2.pointPolygonTest(poly, (float(p[0]), float(p[1])), False) >= 0
    moving = thru = pts = out = 0
    for t in tracks.values():
        ps = [r["pos"] for r in t["frames"]]
        if len(ps) < 5 or np.hypot(ps[0][0] - ps[-1][0], ps[0][1] - ps[-1][1]) < CORNER_MIN_MOVE:
            continue
        moving += 1
        thru += any(inside(inter[0], p) for p in ps)
        pts += len(ps)
        out += sum(not any(inside(z, p) for z in zones) for p in ps)
    if moving < 3:
        return None
    thru_ratio, out_ratio = thru / moving, out / pts
    if thru_ratio >= CORNER_MIN_THRU and out_ratio <= CORNER_MAX_OUT:
        return None
    return {"thru_ratio": round(thru_ratio, 2), "out_ratio": round(out_ratio, 2),
            "message": "찍은 교차로 모서리가 차들이 다닌 곳과 잘 맞지 않아요. 모서리를 다시 찍으면 결과가 더 정확해질 수 있어요."}


def signal_guesses(facts, user):
    """연결된 신호등 색을 신호 색 질문의 추정값으로 넣음. 확신이 AUTO_MIN 이상이면(B 모델로 켤 때) 질문을 빼고
    사실로 바로 씀 (facts["auto_facts"]에 남겨 결과 화면에 "영상에서 판단"으로 보여 줌)"""
    a, b = facts["collision"]["a"], facts["collision"]["b"]
    came = {t: situation.effective(facts, user, t, "entry_from") for t in (a, b)}
    guess = signals.guesses(facts, user, came)
    late = signals.late_red(facts, user, came)
    keep = []
    for u in facts["unknowns"]:
        g = guess.get(u["field"])
        if g and u["field"] not in user:
            color, share = g
            if signals.AUTO_MIN is not None and share >= signals.AUTO_MIN:
                _, tid, key = u["field"].split(".", 2)
                facts["parties"][tid][key] = color
                facts.setdefault("auto_facts", []).append(u["field"])
                continue
            u["model_guess"] = color
        if u["field"] == "situation.special" and "situation.special" not in user:   # 적신호 직전 진입 미리 고르기
            u["model_guess"] = list(u.get("model_guess") or []) + [f"late_red:{t}" for t in late
                                                                   if f"late_red:{t}" in u["options"]]
        keep.append(u)
    facts["unknowns"] = keep


def modifier_details(result, asm):
    """적용된 수정요소마다 누구에게, 얼마나, 근거가 영상인지 사용자 입력인지.
    근거 사실(observed) 중 하나라도 사용자 답에서 온 값(asm: to_assumptions)이면 "user". 운전자 요인·감산 보기처럼
    당사자가 자기에게 유리하게 고를 수 있는 것을 결과·투표글에서 "사용자 입력"으로 따로 보여 주려고"""
    roles = result.get("roles") or {}
    out = []
    for m in result.get("applied_modifiers", []):
        party = m.get("party")
        track = (roles.get(party) or {}).get("track_id") if party in roles else None
        given = set((asm.get("parties") or {}).get(str(track), {})) | {"scene." + k for k in asm.get("scene") or {}}
        facts = list((m.get("observed") or {}).keys())
        user = any(f in given for f in facts)
        out.append({"label": m.get("label"), "party": party, "track": track, "delta": m.get("delta"),
                    "source": "user" if user else "video", "facts": facts})
    return out


def parking_guesses(facts, user):
    """주차장: "주차 칸에서 나오던 중"이라고 답한 당사자가 충돌 뒤 반대로 다시 출발했으면(build_facts.reverse_cusp)
    진행 방향 질문에 "후진"을 미리 골라 둠. 원문 차51-1 "B 후진 +10" (후진 출차)"""
    for u in facts["unknowns"]:
        part = u["field"].split(".")
        if len(part) == 3 and part[2] == "movement" and u["field"] not in user:
            t = part[1]
            if (user.get(f"parties.{t}.parking_action") == "leaving"
                    and (facts["parties"].get(t) or {}).get("reverse_cusp")):
                u["model_guess"] = "reverse"


def slow_guesses(facts, user, scene, tracks):
    """서행 질문: 진입 전에 멈춘 게 확실하면(경계 검사 통과) 질문을 빼고(판정 모듈이 멈춤을 서행으로 봄),
    진입 직전에 오히려 빨라졌으면 "안 줄였음"을 미리 골라 둠. 나머지는 빈 질문 (src/app/slowdown.py)"""
    keep = []
    for u in facts["unknowns"]:
        part = u["field"].split(".")
        if len(part) == 3 and part[2] == "slowed_before_entry" and u["field"] not in user:
            t = part[1]
            p = facts["parties"].get(t) or {}
            entry = user.get(f"parties.{t}.intersection_entry")
            if not isinstance(entry, (int, float)) or isinstance(entry, bool):
                # 답이 숫자가 아니면 영상 값으로 (잘못된 답은 이 뒤 ans.check가 안내 문구로 막음.
                # 여기서 먼저 계산하다 TypeError로 죽던 것, tests/test_inputs "프레임 글자")
                entry = (p.get("intersection_entry") or {}).get("frame")
            path = {r["frame"]: r["pos"] for r in tracks[t]["frames"]} if t in tracks else {}
            g = slowdown.guess(p, path, scene.get("corners"), facts["fps"], entry)
            if g is True and p.get("stopped_before_entry"):
                continue
            u["model_guess"] = g
        keep.append(u)
    facts["unknowns"] = keep


def solve(case_dir, video, user=None, judge_dir=JUDGE_DIR, name=None, log=None):
    """준비(prepare)와 장면(set_scene)이 끝난 결과 폴더에서 나머지 단계를 돌리고 B 판정까지 → app.json
    user: 지금까지의 답 전부 (app_io.md 2.2). 반환: app.json 내용"""
    name = name or os.path.splitext(os.path.basename(video))[0]
    log = {} if log is None else log
    user = check_answers(user or {})
    out = case_dir
    scene_path = os.path.join(out, "scene.json")
    if not os.path.exists(scene_path):
        raise InputError("scene_missing", "교차로 모서리를 먼저 찍어 주세요")
    if not os.path.exists(os.path.join(out, "tracks.json")):
        raise InputError("not_prepared", "영상 분석이 아직 끝나지 않았어요")
    video = analysis_video(out, video)

    taps = user.get("user_tracks") or {}
    n_frames = load(os.path.join(out, "tracks.json"))["frames_analyzed"]   # 화면 전환이 있으면 그 앞까지
    try:
        tap_track.check(taps, n_frames)
    except (ValueError, TypeError, KeyError) as e:
        raise InputError("user_tracks_invalid", f"직접 표시한 박스를 확인해 주세요: {e}")
    pair = ans.collision_pair(user)
    if not pair and len(taps) == 2:   # 당사자 둘을 다 직접 표시했으면 그 둘이 충돌 쌍
        pair = list(taps)
    # 당사자를 직접 표시한 프레임 = 사용자가 본 충돌 장면 → 충돌 프레임으로 씀
    tap_frame = min((t["frame"] for tid, t in taps.items() if pair and tid in pair), default=None)
    stage("stitch", lambda: stitch_tracks.run(out), log)
    stage("finalize", lambda: finalize_tracks.run(out), log)
    if taps:
        stage("user_tracks", lambda: tap_track.add(out, video, taps, n_frames), log)

    if pair:   # 고른 쌍으로 충돌을 만들 수 없으면 detect_collision이 멈추므로 먼저 확인
        problem = pair_problem(load(os.path.join(out, "tracks_final.json"))["tracks"], pair)
        if problem:
            return ask_parties(out, video, name, user, log, *problem)
    stage("collision", lambda: detect_collision.run(out, pair=pair, frame=tap_frame), log)
    if not load(os.path.join(out, "collision.json"))["events"]:
        return ask_parties(out, video, name, user, log, "not_found",
                           "충돌 장면을 찾지 못했어요. 부딪힌 두 당사자를 골라 주세요. 목록에 없으면 화면에 직접 표시해 주세요.")
    stage("lights", lambda: light_states.run(video, out), log)   # 신호등 궤적별 프레임 색 (신호 색 질문의 참고)
    stage("zones", lambda: zone_events.run(scene_path, out), log)
    stage("facts", lambda: build_facts.run(out), log)

    # 답 반영: 충돌 쌍을 고른 답은 위에서 facts에 반영됨. 나머지는 B의 가정으로 넘김
    facts_path = os.path.join(out, "facts.json")
    facts = load(facts_path)
    if pair:   # 고른 쌍으로 facts를 다시 만들었으니, 같은 질문이 남아 있으면 지움
        facts["unknowns"] = [u for u in facts["unknowns"] if u["field"] != "collision.parties"]
        save(facts, facts_path)
    # 인정기준의 장: 종류는 사용자 답이 있으면 답으로. 보행자·자전거 장 도표가 판정 모듈에 생기면 그 장에 필요한
    # 사실을 묻고, 아직 없으면 판정이 자동차끼리 도표로 나온 참고값이라고 알린다 (src/app/chapters.py)
    pa, pb = facts["collision"]["a"], facts["collision"]["b"]
    cls_of = {t: user.get(f"parties.{t}.cls", facts["parties"][t]["cls"]) for t in (pa, pb)}
    ch = chapters.chapter(cls_of.values())
    ch_ready = chapters.ready(judge_dir, ch)
    if ch != "vehicle" and ch_ready:
        for t, c in cls_of.items():
            if chapters.CHAPTER_OF.get(c):
                facts["unknowns"] += chapters.questions(t, facts["collision"]["frame"])
    # 차대차 도표에 필요한 상황 질문 (일시정지 표지, 비보호 좌회전, 유턴 종류, 앞뒤, 서 있던 이유 등)
    facts["unknowns"] += situation.questions(facts, user)
    # 신호등 ↔ 진입로 연결 질문, 연결됐으면 그 신호등 색으로 당사자 신호 색 추정 (src/app/signals.py)
    facts["unknowns"] += signals.questions(facts, load(scene_path).get("closed_side"))
    signal_guesses(facts, user)
    parking_guesses(facts, user)
    slow_guesses(facts, user, load(scene_path), load(os.path.join(out, "tracks_final.json"))["tracks"])
    facts["judge_thresholds"] = judge_bridge.thresholds(judge_dir)   # 명확한 선진입 기준 등 (B 값을 따름)
    try:
        ans.check(facts, {k: v for k, v in user.items() if k != "collision.parties"}, n_frames)
    except ValueError as e:
        raise InputError("answer_invalid", f"답을 확인해 주세요: {e}")
    asm = ans.to_assumptions(facts, user)

    # 답이 없는 질문은 모델 추정값(또는 기본값)으로 채워서 판정 → 사용자 입력 없이도 결과가 나옴
    left = ans.remaining(facts, user)
    judge_facts, filled = ans.fill_guesses(facts, left, user)
    judge_path = os.path.join(out, "facts_judge.json")
    save(judge_facts, judge_path)

    t0 = time.perf_counter()
    verdict = judge_bridge.judge(judge_path, asm, judge_dir)
    log["judge"] = round(time.perf_counter() - t0, 3)
    save(verdict, os.path.join(out, "result.json"))

    def same(results):
        return len({json.dumps([r.get("rule_id"), r.get("fault_by_track")], sort_keys=True) for r in results}) == 1

    # 중앙선·상황 질문(situation.DROP_IF_SAME): 보기마다 판정해 봐서 모두 지금 판정과 같으면 이 사고에서는
    # 상관없으니 묻지 않는다 (평가 24개 모두 중앙선 질문이 남았었음). 중앙선은 결과가 갈리면 도로 폭처럼 경우별
    # 결과를 나란히 보여 준다
    issues = []
    for q in [u for u in left if situation.droppable(u["field"])]:
        cases = []
        for opt, label in zip(q["options"], q["choices"]):
            rr = judge_bridge.judge(judge_path, ans.to_assumptions(facts, dict(user, **{q["field"]: opt})),
                                    judge_dir)["result"]
            cases.append({"answer": opt, "choice": label, "rule_id": rr.get("rule_id"),
                          "fault_by_track": rr.get("fault_by_track")})
        if same(cases + [verdict["result"]]):
            left = [u for u in left if u is not q]
            filled = [f for f in filled if f != q["field"]]
        elif q["field"] == "road.center_line" and not same(cases):
            issues.append({"field": q["field"], "question": q["question"], "cases": cases})

    # 쟁점: 답이 없는 도로 폭 질문은 세 경우로 각각 판정해 본다 (화면으로 추정할 방법을 못 찾음).
    # 결과가 모두 같으면 이 사고에서는 상관없으니 질문을 지우고, 다르면 경우별 결과를 나란히 보여 준다
    q = next((u for u in left if u["field"] == "road.wider_road"), None)
    if q:
        cases = []
        for opt, label in zip(q["options"], q["choices"]):
            alt_facts, _ = ans.fill_guesses(facts, [dict(u, model_guess=opt) if u is q else u for u in left], user)
            alt_path = os.path.join(out, "facts_judge_alt.json")
            save(alt_facts, alt_path)
            rr = judge_bridge.judge(alt_path, asm, judge_dir)["result"]
            cases.append({"answer": opt, "choice": label, "rule_id": rr.get("rule_id"),
                          "fault_by_track": rr.get("fault_by_track")})
        os.remove(alt_path)
        if same(cases):
            left = [u for u in left if u is not q]
            filled = [f for f in filled if f != q["field"]]
        else:
            issues.append({"field": q["field"], "question": q["question"], "cases": cases})

    # 부딪힌 두 대 질문을 맨 앞으로: 이 답이 바뀌면 당사자별 질문(진행 방향 등)이 다른 궤적 것으로 바뀌어서
    # 앞에서 답한 게 버려짐 (앱은 받은 순서대로 한 개씩 물음, 11-03 에뮬레이터 시험에서 맨 뒤에 나왔음)
    left.sort(key=lambda u: u["field"] != "collision.parties")

    # 앱 응답: 남은 질문(근거 프레임 이미지 포함) + 판정 결과
    # 그림마다 충돌 당사자 둘(빨강·파랑)을, 부딪힌 쌍 질문이면 보기에 나온 객체(초록)까지 번호와 함께 그림
    parties = (facts["collision"]["a"], facts["collision"]["b"])
    show = {facts["collision"]["frame"]: list(parties)}
    names = {}   # 이름표: {궤적: 종류} 또는 {(프레임, 궤적): 글자}
    for u in left:
        ids = show.setdefault(u["evidence_frame"], list(parties))
        if u["answer_type"] == "pair":
            for t in (t for o in u["options"] for t in o):
                if t not in ids:
                    ids.append(t)
        for h in u.get("light_hints", []):   # 신호 색 질문: 신호등에 모델이 본 색을 적어 참고로 보여 줌
            if h["track"] not in ids:
                ids.append(h["track"])
            names[(u["evidence_frame"], h["track"])] = f"light {h['color']} {h['p']:.2f}"
    tracks = load(os.path.join(out, "tracks_final.json"))["tracks"]
    answered_cls = {t: user[f"parties.{t}.cls"] for t in parties if f"parties.{t}.cls" in user}
    answered_cls.update(names)
    imgs = frames.save(video, list(show), out, tracks, show, parties, answered_cls)
    for u in left:
        u["image"] = imgs.get(u["evidence_frame"])
    # 진입로·진행 방향 질문은 진입로마다 보기 이름을 칠하고 그 당사자가 지나간 길을 그린 그림으로 바꿈.
    # 보기가 "화면 위쪽 길" 같은 화면 기준이라 길이 대각선이면 그림 없이는 어느 길인지 모름
    scene = load(scene_path)
    path_imgs = {}
    for u in left:
        part = u["field"].split(".")
        if len(part) == 3 and part[0] == "parties" and part[2] in ("entry_from", "movement") and part[1] in tracks:
            tid = part[1]
            if tid not in path_imgs:
                color = frames.PARTY_COLORS[parties.index(tid)] if tid in parties else frames.OTHER_COLOR
                path_imgs[tid] = frames.path_image(video, u["evidence_frame"], scene, tracks[tid], tid, color,
                                                   build_facts.DIR_NAMES, out)
            u["image"] = path_imgs[tid] or u["image"]
        if u.get("light_track") in tracks:   # 신호등 연결 질문: 진입로 이름 + 신호등 확대 그림
            t = u["light_track"]
            u["image"] = frames.light_image(video, u["evidence_frame"], scene, tracks[t], t,
                                            build_facts.DIR_NAMES, out) or u["image"]
    r = verdict["result"]
    # 화면 전환(줌인 등)이 있으면 그 앞까지만 분석했다는 사실 (기획서: 결과에 그 사실을 표시)
    cut = load(os.path.join(out, "tracks.json")).get("scene_cut_frame")
    scene_cut = {"frame": cut, "t": round(cut / facts["fps"], 3)} if cut is not None else None
    camera_notice = camera_moved(out, facts["collision"]["frame"], facts["fps"])
    app = {
        "video": name,
        # 선택 질문(optional, 특수 상황)만 남았으면 완료. 앱은 결과 화면에 "해당하면 알려 주세요"로 보여 줌
        "status": "needs_answers" if any(not u.get("optional") for u in left) else "done",
        "questions": left,
        "optional_questions": ans.optional_all(facts, user),   # 답한 것 포함 (앱이 다시 열어 고치거나 취소)
        "answers": user,
        "answer_conflicts": ans.conflicts(facts, user),   # 사용자 답이 모델 추정과 다른 질문 (기획서 6.3)
        "scene_cut": scene_cut,
        "camera_notice": camera_notice,   # 카메라가 크게 줌·회전해서 위치를 믿기 어려운 구간
        "corner_notice": corner_check(scene, tracks),   # 모서리가 궤적과 안 맞음 (다시 찍기 안내)
        "collision": {**facts["collision"], "image": imgs.get(facts["collision"]["frame"])},
        "verdict": {
            "status": verdict["status"],
            "rule_id": r.get("rule_id"),
            "title": r.get("title"),     # 도표 이름 (예: "직진 대 직진 (동시진입)"). 결과·기록 화면용
            "fault_by_track": r.get("fault_by_track"),
            "fault_if_pending_by_track": r.get("fault_if_pending_by_track"),
            "applied_modifiers": [m.get("label") for m in r.get("applied_modifiers", [])],
            # 수정요소별 근거: source "user"면 사용자가 답·보기로 넣은 것 (결과 화면에서 "사용자 입력"으로 구분)
            "modifier_details": modifier_details(r, asm),
            "unverifiable_factors": r.get("unverifiable_factors", []),
            "assumptions": verdict["assumptions"],
            "provisional": any(not u.get("optional") for u in left),   # 남은 질문이 있으면 추정값으로 낸 결과
            "auto_filled": filled,       # 추정값·기본값으로 채운 질문
            "auto_facts": facts.get("auto_facts", []),   # 확신이 높아 질문 없이 영상에서 정한 사실 (신호 색 등)
            "chapter": ch,               # 당사자 종류로 본 인정기준의 장 (vehicle / bicycle / pedestrian)
            "chapter_ready": ch_ready,   # 그 장의 도표가 판정 모듈에 있는지
            "notice": None if ch_ready else
                      f"'{chapters.NAMES[ch]}' 사고 기준은 아직 판정 모듈에 없어서, 이 결과는 자동차끼리의 기준으로 "
                      "낸 참고값이에요.",
        },
        "issues": issues,                # 답에 따라 결과가 달라지는 쟁점과 경우별 결과
        "judge_version": verdict["judge_version"],
        "timing_sec": log,
    }
    save(app, os.path.join(out, "app.json"))
    return app
