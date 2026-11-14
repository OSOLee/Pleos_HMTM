"""가짜 블랙박스 분석기 (docs/design-blackbox.md 2절)

영상 내용은 보지 않고 시나리오 JSON(scenarios/<이름>.json) 하나를 골라 돌려준다.
단 영상 길이·fps·크기(video)는 파일에서 실제로 읽어 시나리오 값을 덮는다 (OpenCV, 못 읽으면 시나리오 값).

시나리오 고르기 (위에서부터 처음 맞는 것, 확정 Q16)
  1. analyze(..., scenario=이름)  (API 요청의 scenario 칸)
  2. 원래 파일 이름의 "__scn-<이름>"  (analyze(..., filename=원래 이름). 없으면 video_path의 이름)
  3. 환경변수 HMTM_BB_FAKE_DEFAULT, 없으면 right_turn_left_straight

사용자가 고른 사고 순간으로 다시 분석 (analyze(..., collision_t=초), 3.6 PUT collision): 시나리오에 "fake.on_pick"(다른 시나리오 이름)이
있으면 그 시나리오를 돌려준다 (사고 순간을 못 찾은 영상이 고른 순간으로는 판정되는 흐름). 없으면 같은 시나리오 그대로
(no_collision이면 다시 no_collision). collision.t를 고른 시각으로 바꾸는 일은 HMTM(analyzer.apply_pick)이 한다.

시각 맞추기: 시나리오의 시각(collision.t, intersection_entry.t, 값 객체의 t, ego_motion.jolt_t·t, hints.collision_candidates의 t)은
시나리오 영상 길이 기준이라, 실제 영상 길이에 비례해 옮긴다 (k = 실제 길이 ÷ 시나리오 길이). 프레임은 실제 fps로 다시 계산.
"""
import copy
import glob
import json
import os
import re
import time

from src.blackbox.analyzer import SCHEMA_VERSION

NAME, VERSION = "fake", "0.1.0"
SCENARIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios")
DEFAULT_SCENARIO = "right_turn_left_straight"
ENV_DEFAULT = "HMTM_BB_FAKE_DEFAULT"
SCN_IN_NAME = re.compile(r"__scn-([A-Za-z0-9_]+)")


def scenario_names():
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(SCENARIO_DIR, "*.json")))


def load_scenario(name, _seen=()):
    """시나리오 JSON. "extends": 다른 시나리오 이름이면 그 내용에 이 파일의 칸을 덮어씀 ("fake"는 칸별로 합침).
    분석 결과는 같고 데모 차량 기록(fake.vehicle_demo)만 다른 시나리오에 씀"""
    path = os.path.join(SCENARIO_DIR, f"{name}.json")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name or "") or not os.path.isfile(path) or name in _seen:
        return None
    with open(path, encoding="utf-8") as f:
        scn = json.load(f)
    parent = scn.pop("extends", None)
    if not parent:
        return scn
    base = load_scenario(parent, _seen + (name,))
    if base is None:
        return None
    fake = {**base.get("fake", {}), **scn.pop("fake", {})}
    base.update(scn)
    base["fake"] = fake
    return base


def choose(scenario=None, filename=None):
    """(시나리오 이름, 고른 방법) — 방법: request / filename / default"""
    if scenario:
        return scenario, "request"
    m = SCN_IN_NAME.search(os.path.basename(filename or ""))
    if m:
        return m.group(1), "filename"
    return os.environ.get(ENV_DEFAULT) or DEFAULT_SCENARIO, "default"


def read_video(path):
    """{"duration_s", "fps", "frames", "width", "height"} 또는 None (못 읽음)"""
    import cv2
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or frames <= 0:
            return None
        return {"duration_s": round(frames / fps, 3), "fps": round(fps, 3), "frames": frames,
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    finally:
        cap.release()


def _rescale(node, k, fps):
    """dict 안의 t(초)를 k배, 같은 dict의 frame은 새 t × fps"""
    if isinstance(node, dict):
        if isinstance(node.get("t"), (int, float)) and not isinstance(node.get("t"), bool):
            node["t"] = round(node["t"] * k, 3)
            if "frame" in node or "evidence_frame" in node:
                key = "frame" if "frame" in node else "evidence_frame"
                node[key] = int(round(node["t"] * fps))
        for v in node.values():
            _rescale(v, k, fps)
    elif isinstance(node, list):
        for v in node:
            _rescale(v, k, fps)


class FakeAnalyzer:
    name, version = NAME, VERSION

    def analyze(self, video_path, start_time=None, *, work_dir=None, progress=None, scenario=None, filename=None,
                collision_t=None, **opts):
        name, how = choose(scenario, filename or video_path)
        scn = load_scenario(name)
        picked_from = None
        if scn is not None and collision_t is not None and (scn.get("fake") or {}).get("on_pick"):
            picked_from, name = name, scn["fake"]["on_pick"]
            scn = load_scenario(name)
        if scn is None:
            return {"schema_version": SCHEMA_VERSION, "analyzer": {"name": NAME, "version": VERSION},
                    "status": "failed", "reason": "scenario_unknown",
                    "message": f"가짜 분석기에 없는 시나리오예요: {name}", "video": read_video(video_path),
                    "clock": {"osd_start_ms": None}, "facts": None, "ego_motion": None, "hints": {}}
        out = copy.deepcopy(scn)
        fake = out.pop("fake", {})
        delay = float(fake.get("delay_sec") or 0)
        steps = 10 if delay > 0 else 0
        for i in range(steps):
            time.sleep(delay / steps)
            if progress:
                progress(int((i + 1) * 100 / steps))

        out["analyzer"] = {"name": NAME, "version": VERSION}
        real = read_video(video_path)
        scn_video = out.get("video") or {}
        if real:
            k = real["duration_s"] / scn_video["duration_s"] if scn_video.get("duration_s") else 1.0
            if out.get("facts"):
                _rescale(out["facts"], k, real["fps"])
            if (out.get("hints") or {}).get("collision_candidates"):
                _rescale(out["hints"]["collision_candidates"], k, real["fps"])
            em = out.get("ego_motion") or {}
            for key in ("jolt_t", "t"):   # 움직임 시각도 같은 비율로 (값 배열은 그대로)
                if em.get(key):
                    em[key] = [round(t * k, 3) for t in em[key]]
            out["video"] = real
        out.setdefault("clock", {"osd_start_ms": None})
        out.setdefault("hints", {})
        out["hints"] = dict(out["hints"], fake={"scenario": name, "chosen_by": how, "video_read": real is not None,
                                                 "description": fake.get("description"),
                                                 **({"picked_from": picked_from} if picked_from else {})})
        if progress:
            progress(100)
        return out
