# MTM(OSOLee/MTM) feature/server의 src/analyze/bb_output.py 복사본. import만 video_lib로 바꿈 (docs/origin.md). MTM 쪽을 고친 뒤 다시 복사한다.
"""블랙박스 분석 결과를 HMTM 분석기 출력(bb-0.2)으로 바꾼다 (docs: HMTM docs/design-blackbox.md 8절)

  out = to_bb02(case_dir, video)        # case_dir에 ego_motion.json, tracks.json, bb_partner.json (+ bb_kind.json)이 있어야 함

HMTM의 `HMTM_BB_ANALYZER=mtm` 자리(backend/src/blackbox/video_analyzer.py)에서 이 함수를 부르면 된다. 판정 엔진은 부르지 않는다.
HMTM 규약에 맞춘 점
  - 당사자 id는 "ego"(촬영 차)와 "other"(상대). 우리 내부 id("0", 트랙 id, "9999")는 쓰지 않는다.
  - 값은 {"value", "source": "model", "confidence"} 또는 추정만 {"value": null, "guess", "confidence"}.
    확실하지 않은 값은 guess로 내서 HMTM이 사용자에게 묻고 미리 골라 둔다 (틀린 확실한 값이 질문 없이 판정에 들어가기 때문)
  - 방위: 상대 entry_from은 내 차 기준. 같은 방향(앞차·뒤차)은 south. 내 차 cls·entry_from은 내지 않는다.
  - 상대 종류(cls)는 사고 장을 정한다: 탐지 신호(bb_kind)가 있으면 person·bicycle, 확신도 0.7 미만이면 추정으로 낸다.
  - 장면(M6)은 영상 단위 정확도 66%라 늘 추정으로, T자형은 신호 유무를 내지 않는다 (B 평가 기록). 횡단보도는 위=확정, 부근=추정.
이 파일은 src/analyze와 표준 라이브러리만 쓰고 HMTM에 그대로 복사해 쓸 수 있게 둔다 (판정에 쓰는 사실 만들기는 bb_facts.run을 그대로 부름).
"""
import json
import os

from src.blackbox.video_lib import bb_facts, bb_kind

SCHEMA_VERSION = "bb-0.2"
ANALYZER = {"name": "mtm-blackbox", "version": "0.1.0"}
KIND_SURE = 0.7     # 상대 종류 확신도가 이 이상이면 확실한 값 (HMTM CLS_MIN_CONF와 같음)


def _load(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def _val(v, conf=None, **extra):
    o = {"value": v, "source": "model", **extra}
    if conf is not None:
        o["confidence"] = round(conf, 3)
    return o


def _guess(g, conf):
    return {"value": None, "source": "model", "guess": g, "confidence": round(conf, 3)}


def _video_info(video, fps_fallback):
    import cv2
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or fps_fallback or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    info = {"duration_s": round(n / fps, 3), "fps": round(fps, 3), "frames": n,
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    cap.release()
    return info


def _ego_motion(ego, fps):
    """시각 맞추기용 (8.4). speed_proxy=mag, yaw_proxy=tx. 못 잰 프레임(None)은 건너뜀"""
    fr = [f for f in ego["frames"] if f.get("ok")]
    segs = ego["summary"]["segments"]

    def moving(f):
        return any(g["state"] == "moving" and g["from"] <= f <= g["to"] for g in segs)
    return {"fps": fps, "step": 1, "t": [round(f["frame"] / fps, 3) for f in fr],
            "speed_proxy": [f["mag"] for f in fr], "moving": [moving(f["frame"]) for f in fr],
            "yaw_proxy": [f["tx"] for f in fr], "jolt_t": [round(j / fps, 3) for j in ego["summary"]["jolt_frames"]]}


def _other_cls(case, partner, hint, kind_cls):
    """상대 종류 값 객체. 탐지 신호가 있으면 그것, 없으면 보이는 상대의 탐지 종류, 안 보이면 자동차류 추정"""
    if kind_cls in ("pedestrian", "bicycle"):
        name = "person" if kind_cls == "pedestrian" else "bicycle"
        score = hint["score"] if hint and hint.get("fired") and hint.get("score") else 0.5   # 탐지 신호 없이 사용자 답이면 0.5
        return _val(name, score) if score >= KIND_SURE else _guess(name, score)
    if partner is not None and case != "ego_hit_from_behind":
        if partner["cls"] == "motorcycle":
            return _val("two_wheeler", 0.7)
        return _val("car", 0.8)
    return _guess("car", 0.5)   # 화면에 안 보이는 상대 (뒤에서 받힘): 차일 것으로 보되 HMTM이 "상대는 무엇이었나요?"를 묻게 함


# ---------- 장면·횡단보도 모델 출력 (M6·M5) → HMTM 항목. B의 참고 구현(scene_crosswalk.py)과 같은 규칙 ----------
# 입력은 case_dir의 선택 파일 (없으면 아무것도 안 채우고 HMTM이 사용자에게 묻는다)
#   bb_scene.json      {"label", "confidence", "guess"}                         (bb_scene.py, M6)
#   bb_crosswalk.json  {"ped_place": {value, confidence, guess}, "dist_from_crosswalk_m": {...}}   (bb_crosswalk.py, M5)
SCENE_TABLE = {   # label → (road.location, junction_type, signal_present). T자형은 신호 유무를 장면만으로 몰라서 내지 않음 (질문)
    "cross_signal": ("intersection", "cross", True),
    "cross_nosignal": ("intersection", "cross", False),
    "t_junction": ("intersection", "t", None),
    "straight": ("straight", None, None),
}
# M6 영상 단위 정확도 66.2%, 확신도 0.9 이상만 써도 84.2%(자동 47.9%) (B 평가 기록 v0.26.0) → 자동 결정에 쓰지 않고 늘 추정으로 낸다.
# 재학습으로 확신도 기준을 넘는 값이 90% 이상 맞으면 SCENE_AUTO를 True로 (B 코드의 SCENE_AUTO·SCENE_CONF_MIN과 같은 뜻)
SCENE_AUTO = False
SCENE_CONF_MIN = 0.90


def _load_opt(case_dir, name):
    p = os.path.join(case_dir, name)
    return _load(p) if os.path.exists(p) else None


def _scene_obj(value, conf):
    sure = SCENE_AUTO and conf is not None and conf >= SCENE_CONF_MIN
    return _val(value, conf) if sure else _guess(value, conf if conf is not None else 0.5)


def _apply_scene(road, scene):
    sc = SCENE_TABLE.get((scene or {}).get("label"))
    if not sc:
        return
    conf = scene.get("confidence")
    loc, junction, signal = sc
    road["location"] = _scene_obj(loc, conf)
    if junction:
        road["junction_type"] = _scene_obj(junction, conf)
    if signal is not None:
        road["signal_present"] = _scene_obj(signal, conf)


def _cw_obj(f):
    """bb_crosswalk.json의 {value, confidence, guess} → 값 객체 (guess면 추정만)"""
    return _guess(f["value"], f["confidence"]) if f.get("guess") else _val(f["value"], f["confidence"])


def _apply_crosswalk(other, cw):
    if not cw:
        return
    is_person = "person" in (other["cls"].get("value"), other["cls"].get("guess"))   # 보행자 도표에서만 쓰는 항목
    if not is_person:
        return
    for key in ("ped_place", "dist_from_crosswalk_m"):
        if cw.get(key):
            other[key] = _cw_obj(cw[key])


def to_bb02(case_dir, video, answers=None):
    """case_dir의 분석 결과를 bb-0.2 dict로. 반환값은 HMTM의 validate_output을 통과하는 모양"""
    ego = _load(os.path.join(case_dir, "ego_motion.json"))
    tracks = _load(os.path.join(case_dir, "tracks.json"))
    part = _load(os.path.join(case_dir, "bb_partner.json"))
    fps = ego["summary"].get("fps") or tracks.get("fps") or 30.0
    info = _video_info(video, fps)
    out = {"schema_version": SCHEMA_VERSION, "analyzer": dict(ANALYZER), "status": "ok", "video": info,
           "ego_motion": _ego_motion(ego, fps)}
    f = bb_facts.run(case_dir, video=video, place="직선도로", answers=answers)
    if not f["supported"]:
        # 상대가 옆에서 온 사고 등 1차 범위 밖: 판정하지 않고 알림 (HMTM이 사용자에게 알림)
        out.update(status="unsupported", reason="out_of_scope", message=f["reason"] or "이 사고 유형은 아직 분석하지 못해요")
        return out
    case, conf = f["case"], f["confidence"]
    facts = f["facts"]
    imp = facts["collision"]["frame"]
    p = part["partner"]
    hint = bb_kind.load(case_dir)
    kind_cls = next((c for c in ("pedestrian", "bicycle") if facts["parties"][facts["collision"]["b"]]["cls"] == c), None)
    other_cls = _other_cls(case, p, hint, kind_cls)
    contact = {"ego_hit_from_behind": "rear", "ego_rear_ends_front": "front", "partner_cuts_in": "unknown"}.get(case, "unknown")
    t_conf = 0.8 if part["impact_source"] in ("jolt_near_stop",) else 0.5 if part["impact_frame"] is not None else 0.2
    moving_at = any(g["state"] == "moving" and g["from"] <= max(imp - 8, 0) <= g["to"] for g in ego["summary"]["segments"])
    conf_num = {"high": 0.85, "medium": 0.6, "low": 0.4}.get(conf, 0.4)
    b = facts["parties"][facts["collision"]["b"]]
    other = {"cls": other_cls, "entry_from": _val("south", conf_num)}
    if case == "partner_cuts_in":
        other["movement"] = _guess("lane_change", conf_num)       # 옆에서 들어온 것 = 끼어든 것으로 보되 틀릴 수 있어 묻게 함
        other["lead_order"] = _val("leading", conf_num)
    else:
        other["movement"] = _val("straight", conf_num)
        other["lead_order"] = _val(b.get("lead_order", "following"), conf_num)
    if case == "ego_hit_from_behind":
        other["stationary_at_collision"] = _val(False, 0.5)
    out["facts"] = {
        "schema_version": "0.3",
        "collision": {"a": "ego", "b": "other", "t": round(imp / fps, 3), "frame": imp, "zone": "road",
                      "contact": contact, "t_confidence": t_conf},
        "parties": {
            "ego": {"movement": _val("straight", 0.6), "stationary_at_collision": _val(not moving_at, 0.6)},
            "other": other,
        },
        "road": {"location": _guess("straight", 0.5)},   # 장소(직선도로/교차로)는 이 분석기가 가리지 못해 HMTM이 사용자에게 묻도록 추정으로 냄
    }
    _apply_scene(out["facts"]["road"], _load_opt(case_dir, "bb_scene.json"))
    _apply_crosswalk(other, _load_opt(case_dir, "bb_crosswalk.json"))
    out["hints"] = {"bb_case": case, "bb_confidence": conf, "kind_signal": hint,
                    "partner_visible": p is not None and case != "ego_hit_from_behind"}
    return out
