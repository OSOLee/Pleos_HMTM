"""블랙박스 분석기 빈자리 (docs/design-blackbox.md 1절)

  analyzer = get_analyzer()            # 환경변수 HMTM_BB_ANALYZER: fake(기본) / mtm
  out = analyzer.analyze(video_path, start_time, work_dir=..., progress=..., scenario=...)
  out = validate_output(out)           # 틀리면 status=failed, reason=analyzer_output_invalid

출력은 bb_facts (schema_version "bb-0.2", 1.2·8절): FACTS 0.3 모양의 facts + 블랙박스 블록(video, clock, ego_motion, hints).
bb-0.1 출력도 받는다 (bb-0.2는 facts에 보행자·자전거 항목(8.3.1~8.3.3)이 늘었을 뿐 모양이 같음).
analyze는 예외 대신 status로 실패를 알린다. 예외가 나면 run()이 failed / server_error로 바꾼다.
"""
import copy
import os
import threading
from typing import Callable, Protocol

SCHEMA_VERSION = "bb-0.2"
ACCEPTED_VERSIONS = ("bb-0.1", SCHEMA_VERSION)
FACTS_VERSION = "0.3"
STATUSES = ("ok", "no_collision", "unsupported", "failed")
PARTIES = ("ego", "other")
COMPASS = ("west", "east", "north", "south")
MOVEMENTS = ("straight", "left_turn", "right_turn", "u_turn", "lane_change", "reverse")
CLASSES = ("car", "truck", "bus", "two_wheeler", "bicycle", "person")
PLACES = ("intersection", "straight", "parking_lot", "roundabout", "off_road")
JUNCTIONS = ("cross", "t")
ZONES = ("intersection", "road")
CONTACTS = ("front", "left", "right", "rear", "unknown")
# 차량 신호 값은 판정 엔진 이름 그대로 (FACTS 3-5, src/analyze/build_facts.SIGNALS와 같음)
SIGNALS = ("green", "green_arrow", "yellow", "red", "flashing_yellow", "flashing_red", "none")
BOOL = (True, False)

# 보행자·자전거 항목 (8.3.2 도표 선택용, 8.3.3 수정요소 전용). 값은 판정 엔진 이름 그대로 (FACTS 3-15·3-16)
PED_PLACES = ("crosswalk", "near_crosswalk", "near_overpass", "intersection", "road", "sidewalk", "roadway",
              "ped_only_road", "ped_priority_road")
PED_SIGNALS = ("green", "flashing_green", "red")
DIST_BINS = ("within_10m", "10_30m", "over_30m")     # 횡단보도 거리 구간 (8.3.2). 횡단보도 위는 거리를 내지 않음
PED_PARTY_VALUES = {
    "ped_place": PED_PLACES, "ped_signal_at_start": PED_SIGNALS, "ped_signal_at_impact": PED_SIGNALS,
    "ped_activity": ("crossing", "walking", "lying_or_playing"),
    "roadway_walk_position": ("edge_1m", "beyond_1m", "edge", "center"),
    "impact_after_intersection": BOOL, "passed_crosswalk": BOOL, "right_turn_signal": ("green", "red", "none"),
    "riding_on_crosswalk": BOOL,
    "walk_manner": ("normal", "stop", "back", "zigzag"), "diagonal_crossing": BOOL, "opposite_side_start": BOOL,
    "inside_stop_line": BOOL, "passed_stopped_vehicles": BOOL, "ped_posture": ("sitting", "lying", "standing"),
    "on_shoulder": BOOL, "behind_before_reverse": BOOL,
}
BIKE_PARTY_VALUES = {
    "crossing_road": BOOL, "on_bike_crossing": BOOL,
    "bike_lane_type": ("dedicated_road", "dedicated_lane", "priority_road", "none"), "approached_right_edge": BOOL,
    "bike_lane_nearby": BOOL, "in_bike_lane": BOOL, "left_side_riding": BOOL, "path_blocked": BOOL,
    "obstacle_ahead": BOOL, "off_right_side": BOOL,
}
# 배열 값 (허용 값 중 여러 개, 없으면 []). user_factors는 장마다 목록이 달라 문자열 배열인지만 봄
LIST_VALUES = {"ped_factors": ("group", "sudden_entry", "intentional_block", "inline_skate"), "user_factors": None}
# 0 이상 숫자
NUMBER_VALUES = ("dist_from_crosswalk_m", "intersection_entry_speed_kmh")

# 값 객체로 받는 항목과 허용 값 (1.3). 여기에 없는 키는 모양만 보고 그대로 둔다 (분석기가 더 내는 값)
PARTY_VALUES = {"cls": CLASSES, "movement": MOVEMENTS, "entry_from": COMPASS, "lead_order": ("leading", "following"),
                "lane_change_dir": ("left", "right"), "stationary_at_collision": BOOL, "stopped_before_entry": BOOL,
                "turn_signal_used": BOOL, "signal_at_entry": SIGNALS, **PED_PARTY_VALUES, **BIKE_PARTY_VALUES}
ROAD_VALUES = {"location": PLACES, "junction_type": JUNCTIONS, "signal_present": BOOL, "center_line": BOOL,
               "night": BOOL, "low_visibility": BOOL,
               "crosswalk_signal": BOOL, "sidewalk_separated": BOOL, "crossing_prohibition": ("none", "sign", "barrier"),
               "protection_zone": ("child", "elderly", "disabled", "none"), "bad_weather": BOOL,
               "lanes_two_plus": BOOL, "dashed_bike_lane_border": BOOL}
ENV = "HMTM_BB_ANALYZER"


class AnalyzerNotReady(Exception):
    """고른 분석기를 아직 쓸 수 없음 (mtm: MTM 블랙박스 분석기가 완성되기 전)"""

    def __init__(self, name, message):
        super().__init__(message)
        self.name, self.message = name, message


class BlackboxAnalyzer(Protocol):
    name: str
    version: str

    def analyze(self, video_path: str, start_time: dict | None = None, *, work_dir: str | None = None,
                progress: Callable[[int], None] | None = None, **opts) -> dict: ...


_MTM_RUN = threading.Lock()   # 한 프로세스에서 MTM 분석은 한 번에 하나 (track_video 모듈 전역을 바꿔치기하므로, 3.4)


class MtmAnalyzer:
    """MTM 블랙박스 분석기 (1.4 교체 방법). 실제 일은 src/blackbox/video_analyzer.py (A 영역, 고치지 않음).

    만들 때 가중치 목록(backend/models.json)과 실제 파일을 대조한다 (models.py, 1.6). 탐지 모델이 없거나 다르거나,
    등록된 다른 모델이 없거나 다르면 AnalyzerNotReady. 등록 안 된 모델(version·sha256 null)은 analyze 동안 그 경로를
    없는 파일로 바꿔 그 단계만 건너뛴다 (video_analyzer의 각 단계는 모델 파일이 없으면 건너뜀)."""
    name, version = "mtm", None

    def __init__(self):
        from src.blackbox import models, video_analyzer
        self.skip = ()
        self.report = None
        if models.enabled():
            paths = {role: getattr(video_analyzer, attr) for role, attr in models.ATTRS.items()}
            try:
                self.report = models.check(paths)
            except models.ListInvalid as e:
                raise AnalyzerNotReady("mtm", f"MTM 블랙박스 분석기가 아직 준비되지 않았어요: {e}")
            bad = models.problems(self.report)
            if bad:
                raise AnalyzerNotReady("mtm", "MTM 블랙박스 분석기가 아직 준비되지 않았어요: " + " / ".join(bad))
            self.skip = tuple(r for r, v in self.report.items() if v["status"] == "unregistered")
        video_analyzer.check_ready()
        self.version = video_analyzer.VERSION

    def analyze(self, video_path, start_time=None, *, work_dir=None, progress=None, collision_t=None, **opts):
        """collision_t: 사용자가 고른 사고 순간(영상 안 초, 3.6 PUT collision). video_analyzer.analyze에 그대로 넘긴다(그 순간으로 상대·종류·장면·facts를 정함)"""
        from src.blackbox import models, video_analyzer
        with _MTM_RUN:
            saved = {r: getattr(video_analyzer, models.ATTRS[r]) for r in self.skip}
            for r in self.skip:
                setattr(video_analyzer, models.ATTRS[r], models.SKIPPED_PATH)
            try:
                return video_analyzer.analyze(video_path, start_time, work_dir=work_dir, progress=progress,
                                              collision_t=collision_t, **opts)
            finally:
                for r, p in saved.items():
                    setattr(video_analyzer, models.ATTRS[r], p)


def chosen_name(name=None):
    """고른 분석기 이름 (환경변수 HMTM_BB_ANALYZER, 기본 fake)"""
    return (name or os.environ.get(ENV) or "fake").strip().lower()


def uses_worker(name=None):
    """분석을 작업자 프로세스(src.blackbox.worker)가 하는지 (3.4). mtm = 작업자, fake = API 프로세스 안 스레드"""
    return chosen_name(name) == "mtm"


def get_analyzer(name=None):
    """환경변수 HMTM_BB_ANALYZER(기본 fake)로 분석기를 고른다. mtm은 가중치가 없거나 목록과 다르면 AnalyzerNotReady"""
    name = chosen_name(name)
    if name == "fake":
        from src.blackbox.fake import FakeAnalyzer
        return FakeAnalyzer()
    if name == "mtm":
        return MtmAnalyzer()
    raise AnalyzerNotReady(name, f"모르는 분석기예요: {name} (fake 또는 mtm)")


# ---------- 출력 검사 (1.4 validate_output) ----------

class OutputInvalid(Exception):
    pass


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_value(path, v, allowed, name=None):
    """값 객체 {"value", "source", "guess"?, "confidence"?}. value·guess는 허용 값 또는 null.
    배열 항목(LIST_VALUES)은 허용 값의 배열, 숫자 항목(NUMBER_VALUES)은 0 이상 숫자"""
    if not isinstance(v, dict) or "value" not in v:
        raise OutputInvalid(f"{path}: 값 객체({{value, source}})여야 해요")
    for k in ("value", "guess"):
        x = v.get(k)
        if x is None:
            continue
        if name in LIST_VALUES:
            ok_list = LIST_VALUES[name]
            if not isinstance(x, list) or not all(isinstance(i, str) and (ok_list is None or i in ok_list) for i in x):
                raise OutputInvalid(f"{path}.{k}: {x!r}는 배열이어야 해요" + (f" ({list(ok_list)} 중)" if ok_list else ""))
        elif name in NUMBER_VALUES:
            if not (_num(x) and x >= 0):
                raise OutputInvalid(f"{path}.{k}: 0 이상 숫자여야 해요")
        elif allowed is not None and (isinstance(x, (list, dict)) or x not in allowed):
            raise OutputInvalid(f"{path}.{k}: {x!r}는 {list(allowed)} 중 하나여야 해요")
    if name == "dist_from_crosswalk_m":
        if v.get("bin") is not None and v["bin"] not in DIST_BINS:
            raise OutputInvalid(f"{path}.bin: {list(DIST_BINS)} 중 하나여야 해요")
        if v.get("measured") is not None and not isinstance(v["measured"], bool):
            raise OutputInvalid(f"{path}.measured: true / false여야 해요")
    c = v.get("confidence")
    if c is not None and not (_num(c) and 0 <= c <= 1):
        raise OutputInvalid(f"{path}.confidence: 0~1이어야 해요")


def _check(out):
    if not isinstance(out, dict):
        raise OutputInvalid("출력은 객체여야 해요")
    if out.get("schema_version") not in ACCEPTED_VERSIONS:
        raise OutputInvalid(f"schema_version은 {' / '.join(ACCEPTED_VERSIONS)} 중 하나여야 해요")
    st = out.get("status")
    if st not in STATUSES:
        raise OutputInvalid(f"status는 {list(STATUSES)} 중 하나여야 해요")
    an = out.get("analyzer")
    if not (isinstance(an, dict) and an.get("name") and an.get("version")):
        raise OutputInvalid("analyzer.name, analyzer.version이 있어야 해요")
    video = out.get("video")
    if not isinstance(video, dict) or not all(_num(video.get(k)) and video[k] >= 0 for k in ("duration_s", "fps")):
        raise OutputInvalid("video.duration_s, video.fps가 있어야 해요")
    if st in ("unsupported", "failed"):
        if not out.get("reason"):
            raise OutputInvalid(f"status {st}에는 reason이 있어야 해요")
        return
    facts = out.get("facts")
    if not isinstance(facts, dict) or facts.get("schema_version") != FACTS_VERSION:
        raise OutputInvalid(f"facts(schema_version {FACTS_VERSION})가 있어야 해요")
    col = facts.get("collision")
    if not isinstance(col, dict) or col.get("a") != "ego" or col.get("b") != "other":
        raise OutputInvalid("facts.collision.a, b는 ego, other여야 해요")
    t = col.get("t")
    if st == "ok":
        if not (_num(t) and 0 <= t <= video["duration_s"] + 1e-6):
            raise OutputInvalid("facts.collision.t는 영상 안의 초여야 해요 (status ok)")
    elif t is not None:
        raise OutputInvalid("status no_collision이면 facts.collision.t는 null이어야 해요")
    if col.get("zone") not in (None, *ZONES):
        raise OutputInvalid(f"facts.collision.zone은 {list(ZONES)} 중 하나여야 해요")
    if col.get("contact") not in (None, *CONTACTS):
        raise OutputInvalid(f"facts.collision.contact는 {list(CONTACTS)} 중 하나여야 해요")
    tc = col.get("t_confidence")
    if tc is not None and not (_num(tc) and 0 <= tc <= 1):
        raise OutputInvalid("facts.collision.t_confidence는 0~1이어야 해요")
    if col.get("t_source") not in (None, "model", "guess"):
        raise OutputInvalid("facts.collision.t_source는 model / guess 중 하나여야 해요")
    _check_candidates(out.get("hints"), video["duration_s"])
    parties = facts.get("parties")
    if not isinstance(parties, dict) or set(parties) != set(PARTIES):
        raise OutputInvalid("facts.parties는 ego, other 두 당사자여야 해요")
    for pid, p in parties.items():
        if not isinstance(p, dict):
            raise OutputInvalid(f"facts.parties.{pid}는 객체여야 해요")
        for k, v in p.items():
            if k == "intersection_entry":
                if not (isinstance(v, dict) and _num(v.get("t"))):
                    raise OutputInvalid(f"facts.parties.{pid}.intersection_entry는 {{frame, t}}여야 해요")
                continue
            _check_value(f"facts.parties.{pid}.{k}", v, PARTY_VALUES.get(k), k)
        if "entry_from" in (p if pid == "ego" else {}):
            raise OutputInvalid("facts.parties.ego.entry_from은 내지 않아요 (HMTM이 south로 넣음)")
    for k, v in (facts.get("road") or {}).items():
        _check_value(f"facts.road.{k}", v, ROAD_VALUES.get(k), k)
    if col.get("frame") is not None and not (isinstance(col["frame"], int) and not isinstance(col["frame"], bool)
                                             and col["frame"] >= 0):
        raise OutputInvalid("facts.collision.frame은 0 이상 정수여야 해요")
    _check_motion(out.get("ego_motion"), video["duration_s"])


def _check_motion(em, duration):
    """ego_motion (1.3 F): 시각 맞추기(sync.fine_match)가 읽는 모양. 없어도 됨 (그러면 fine 등급이 안 나옴)"""
    if em is None:
        return
    if not isinstance(em, dict):
        raise OutputInvalid("ego_motion은 객체여야 해요")
    t = em.get("t") or []
    if not isinstance(t, list) or not all(_num(x) for x in t) or any(b < a for a, b in zip(t, t[1:])):
        raise OutputInvalid("ego_motion.t는 오름차순 초 배열이어야 해요")
    if t and not (t[0] >= 0 and t[-1] <= duration + 1):
        raise OutputInvalid("ego_motion.t는 영상 안의 초여야 해요")
    for k in ("speed_proxy", "yaw_proxy", "moving"):
        arr = em.get(k)
        if arr in (None, []):
            continue
        if not isinstance(arr, list) or len(arr) != len(t):
            raise OutputInvalid(f"ego_motion.{k}는 ego_motion.t와 길이가 같아야 해요")
        ok = (lambda x: isinstance(x, bool)) if k == "moving" else _num
        if not all(ok(x) for x in arr):
            raise OutputInvalid(f"ego_motion.{k}의 값 모양이 틀렸어요")
    jolt = em.get("jolt_t") or []
    if not isinstance(jolt, list) or not all(_num(x) and 0 <= x <= duration + 1e-6 for x in jolt):
        raise OutputInvalid("ego_motion.jolt_t는 영상 안의 초 배열이어야 해요")


def _check_candidates(hints, duration):
    """hints.collision_candidates (선택): 사고 순간 후보 [{t, frame?, source?, reason?}]. 앱에 그대로 전달하므로 모양만 봄"""
    cands = (hints or {}).get("collision_candidates") if isinstance(hints, dict) else None
    if cands is None:
        return
    if not isinstance(cands, list):
        raise OutputInvalid("hints.collision_candidates는 배열이어야 해요")
    for i, c in enumerate(cands):
        if not (isinstance(c, dict) and _num(c.get("t")) and 0 <= c["t"] <= duration + 1e-6):
            raise OutputInvalid(f"hints.collision_candidates[{i}].t는 영상 안의 초여야 해요")


# ---------- 사고 순간 확인 필요 (3.6 collision_review) ----------

LOW_T_CONFIDENCE = 0.5     # collision.t_confidence가 이보다 낮으면 사고 순간이 불확실 (임시값. A 분석기는 0.8 / 0.5 / 0.2를 냄)
REVIEW_TEXT = {
    "no_collision": "영상에서 사고 순간을 찾지 못했어요. 영상에서 부딪힌 순간을 골라 주세요",
    "guess": "사고 순간을 추정만 했어요. 영상에서 부딪힌 순간이 맞는지 확인해 주세요",
    "low_confidence": "사고 순간이 확실하지 않아요. 영상에서 부딪힌 순간이 맞는지 확인해 주세요",
}


def collision_review(bb):
    """분석기 출력 → 사고 순간 확인 필요 표시. 사고 순간이 없거나(no_collision) 추정(collision.t_source == "guess")이거나
    확신도(collision.t_confidence)가 LOW_T_CONFIDENCE 미만이면 needed. 그때 HMTM은 시각 맞추기를 none으로 두고
    차량 기록 값을 쓰지 않는다 (sync reason collision_uncertain / no_collision_time).
    candidates: 분석기 hints.collision_candidates 그대로, 없고 collision.t가 있으면 그 시각 하나"""
    st = bb.get("status")
    col = ((bb.get("facts") or {}).get("collision")) or {}
    t, conf = col.get("t"), col.get("t_confidence")
    reason = None
    if st == "ok" and col.get("t_source") == "user":   # 사용자가 고른 순간으로 다시 분석함 (apply_pick)
        reason = None
    elif st == "no_collision" or (st == "ok" and t is None):
        reason = "no_collision"
    elif st == "ok" and col.get("t_source") == "guess":
        reason = "guess"
    elif st == "ok" and _num(conf) and conf < LOW_T_CONFIDENCE:
        reason = "low_confidence"
    cands = copy.deepcopy(((bb.get("hints") or {}).get("collision_candidates")) or [])
    if not cands and reason and t is not None:
        cands = [{"t": t, "frame": col.get("frame"), "source": "analyzer"}]
    return {"needed": reason is not None, "reason": reason, "message": REVIEW_TEXT.get(reason),
            "t": t, "t_confidence": conf if _num(conf) else None,
            "candidates": cands if reason else [], "threshold": LOW_T_CONFIDENCE}


def apply_pick(out, t):
    """사용자가 고른 사고 순간(영상 안 초)을 분석기 출력에 씀 (PUT collision 뒤 다시 분석). status ok일 때만.
    분석기가 다른 시각을 냈어도 사용자 시각이 이긴다 (분석기 값은 hints.collision_pick.analyzer_t에 남김)"""
    if out.get("status") != "ok" or not out.get("facts"):
        return out
    col = out["facts"]["collision"]
    fps = (out.get("video") or {}).get("fps") or 30.0
    out.setdefault("hints", {})
    out["hints"]["collision_pick"] = {"t": t, "analyzer_t": col.get("t"), "analyzer_t_confidence": col.get("t_confidence")}
    col.update(t=round(float(t), 3), frame=int(round(t * fps)), t_source="user", t_confidence=None)
    return out


def validate_output(out):
    """분석기 출력 검사. 맞으면 그대로(사본), 틀리면 failed / analyzer_output_invalid 출력으로 바꿔 돌려줌"""
    try:
        _check(out)
        return copy.deepcopy(out)
    except OutputInvalid as e:
        base = out if isinstance(out, dict) else {}
        return failed(base.get("analyzer"), base.get("video"), "analyzer_output_invalid",
                      f"분석기 출력이 약속한 모양과 달라요: {e}")


def failed(analyzer, video, reason, message):
    an = analyzer if isinstance(analyzer, dict) else {}
    return {"schema_version": SCHEMA_VERSION,
            "analyzer": {"name": an.get("name") or "unknown", "version": an.get("version") or "unknown"},
            "status": "failed", "reason": reason, "message": message,
            "video": video if isinstance(video, dict) else None,
            "clock": {"osd_start_ms": None}, "facts": None, "ego_motion": None, "hints": {}}


def run(video_path, start_time=None, work_dir=None, progress=None, name=None, collision_t=None, **opts):
    """분석기를 골라 돌리고 출력을 검사한다. 분석기 예외는 failed / server_error.
    분석기를 고르지 못하면(mtm 준비 안 됨) failed / analyzer_not_ready.
    collision_t: 사용자가 고른 사고 순간(영상 안 초). 분석기에 넘기고, 결과가 ok면 그 시각을 collision.t로 씀 (apply_pick)"""
    if collision_t is not None:
        opts["collision_t"] = collision_t
    try:
        an = get_analyzer(name)
    except AnalyzerNotReady as e:
        return failed({"name": e.name, "version": "unknown"}, None, "analyzer_not_ready", e.message)
    try:
        out = an.analyze(video_path, start_time, work_dir=work_dir, progress=progress, **opts)
    except Exception as e:   # 분석기 버그는 사건 failed로 (서버는 계속 돎)
        return failed({"name": an.name, "version": an.version}, None, "server_error", f"분석 중 오류가 났어요: {e}")
    out = validate_output(out)
    # 결과에 분석기 이름·판을 HMTM이 다시 박는다 (분석기가 다르게 적어도 실제로 돌린 분석기)
    out["analyzer"] = {"name": an.name, "version": an.version}
    if collision_t is not None:
        apply_pick(out, collision_t)
    return out
