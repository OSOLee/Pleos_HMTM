"""MTM 블랙박스 분석기 (docs/design-blackbox.md 1.4 교체 방법 2단계)

  HMTM_BB_ANALYZER=mtm  →  analyzer.MtmAnalyzer가 이 모듈의 check_ready()·analyze()를 부른다

영상 하나(앞 카메라) → 탐지·추적(블랙박스 모델) → 촬영 차 움직임 → 사고 순간·상대 → (사고 직전 보행자·자전거 신호)
→ bb-0.2 출력. 판정 엔진은 부르지 않는다 (HMTM이 부름). 분석 코드는 MTM 블랙박스 코드(video_lib/)의 복사본이고
출처·고친 점은 docs/origin.md. src/analyze(MTM 영역)는 고치지 않는다.

필요한 파일 (git 제외라 로컬에 둠)
  HMTM_BB_DETECTOR  탐지 모델 (기본 models/bb_v3.pt = v8l_bb_v3: 차·이륜차·자전거·사람 4종)
  HMTM_BB_KIND_MODEL 사고 직전 보행자·자전거 신호용 모델 (기본 models/bb_v3.pt, 없으면 그 신호만 건너뜀)
  HMTM_BB_KIND_IMGSZ / HMTM_BB_KIND_CONF  상대 종류 신호 탐지 설정 (기본 960 / 0.15. 사고 직전 2~3초만 보므로 전체 추적이 640이어도 960으로 둠)
  HMTM_BB_IMGSZ / HMTM_BB_CONF  탐지·추적 추론 설정 (기본 960 / 0.15 = 모델을 학습한 크기. PC에서 빨리 볼 때만 HMTM_BB_IMGSZ=640, 정확도 측정은 960)
  HMTM_BB_SCENE_MODEL / HMTM_BB_CROSSWALK_MODEL  장면 분류(M6)·횡단보도 탐지(M5) (기본 models/scene_cls.pt, models/crosswalk.pt, 없으면 건너뜀)
  HMTM_BB_CROSSWALK_CONF  횡단보도 탐지 conf (기본 0.15)
탐지 모델이 없으면 AnalyzerNotReady (그때는 fake를 쓰거나 모델을 둔다). 서버 작업자는 한 번에 영상 하나를 처리하므로
track_video의 모듈 전역(MODEL)을 이 호출 동안만 바꾼다.
"""
import json
import os
import shutil
import tempfile

from src.blackbox.analyzer import AnalyzerNotReady

VERSION = "0.1.0"
BB_MODEL = os.environ.get("HMTM_BB_DETECTOR", "models/bb_v3.pt")
KIND_MODEL = os.environ.get("HMTM_BB_KIND_MODEL", "models/bb_v3.pt")
BB_IMGSZ = int(os.environ.get("HMTM_BB_IMGSZ", "960"))     # backend/models.json의 imgsz·conf와 같음
BB_CONF = float(os.environ.get("HMTM_BB_CONF", "0.15"))
KIND_IMGSZ = int(os.environ.get("HMTM_BB_KIND_IMGSZ", "960"))   # 상대 종류 신호는 사고 직전 2~3초만 학습 크기(960)로 탐지 (전체 추적이 640이어도)
KIND_CONF = float(os.environ.get("HMTM_BB_KIND_CONF", "0.15"))
SCENE_MODEL = os.environ.get("HMTM_BB_SCENE_MODEL", "models/scene_cls.pt")         # M6 장면 분류 (YOLOv8s-cls 384px)
CROSSWALK_MODEL = os.environ.get("HMTM_BB_CROSSWALK_MODEL", "models/crosswalk.pt")  # M5 횡단보도 탐지 (YOLOv8m)
CROSSWALK_CONF = float(os.environ.get("HMTM_BB_CROSSWALK_CONF", "0.15"))             # 횡단보도 모델에 넘기는 conf (안 넘기면 ultralytics 기본 0.25로 돎)
TRACK_SHARE = 90    # 진행률 중 탐지·추적이 차지하는 몫 (나머지는 뒤 단계)


def check_ready():
    if not os.path.exists(BB_MODEL):
        raise AnalyzerNotReady("mtm", f"MTM 블랙박스 분석기가 아직 준비되지 않았어요: 블랙박스 탐지 모델({BB_MODEL})이 없어요. "
                                      "모델을 두거나 HMTM_BB_DETECTOR로 위치를 알려 주세요 (HMTM_BB_ANALYZER=fake로 쓸 수도 있어요)")


def _failed(reason, message):
    return {"schema_version": "bb-0.2", "analyzer": {"name": "mtm", "version": VERSION}, "status": "failed",
            "reason": reason, "message": message, "video": None, "clock": {"osd_start_ms": None}, "facts": None,
            "ego_motion": None, "hints": {}}


GUESSED_PARTY_KEYS = ("entry_from", "movement", "lead_order")   # 사고 순간을 모를 때 상대 쪽은 확정하지 않고 추정으로 낸다


def _no_collision_if_unfound(out, case_dir):
    """bb_partner가 사고 순간을 못 찾았으면(never_moving, no_stop_found) 출력을 no_collision으로 바꾼다.

    MTM의 bb_facts는 못 찾으면 영상 끝을 사고 순간으로 두고 계속 가지만(MTM 안에서는 그게 맞다), HMTM은 t_confidence를
    읽지 않아 그 시각을 믿고 차량 기록까지 맞춰 버린다. 그래서 설계대로 status "no_collision", collision.t null로 내고
    (HMTM에 사용자가 충돌 시점을 고르는 흐름이 있다), 영상 끝 시각은 hints.collision_candidates에 후보로만 남긴다.
    복사본(video_lib/bb_facts.py)은 MTM과 갈라지지 않게 고치지 않고 여기서 거른다."""
    if out.get("status") != "ok":
        return
    with open(os.path.join(case_dir, "bb_partner.json"), encoding="utf-8") as fp:
        part = json.load(fp)
    if part.get("impact_frame") is not None:
        return
    col = out["facts"]["collision"]
    out["hints"]["collision_candidates"] = [{"t": col["t"], "frame": col["frame"], "source": "video_end",
                                             "reason": part.get("impact_source")}]
    col["t"], col["frame"], col["t_confidence"] = None, None, None
    other = out["facts"]["parties"]["other"]
    for key in GUESSED_PARTY_KEYS:
        v = other.get(key)
        if isinstance(v, dict) and v.get("value") is not None:
            other[key] = {"value": None, "source": v.get("source", "model"), "guess": v["value"],
                          "confidence": v.get("confidence")}
    out["status"] = "no_collision"
    out["message"] = "영상에서 사고 순간을 찾지 못했어요. 충돌 시점을 골라 주세요"


def _track_progress(report):
    """track_video.run이 (처리한 프레임 수, 전체 프레임 수) 두 인자로 부르는 진행률 함수. 앞 TRACK_SHARE(%)만큼을 추적이 차지한다"""
    return lambda n, total: report(n * TRACK_SHARE / max(total, 1))


CAR_ONLY_PARTY_KEYS = ("entry_from", "movement", "lead_order")   # 상대 차의 움직임. 보행자·자전거는 이 분석기가 움직임을 따로 분석하지 않는다
PED_BIKE_CLS = ("person", "pedestrian", "bicycle")


def _drop_car_facts_for_ped_bike(out):
    """상대가 보행자·자전거로 정해졌으면 entry_from·movement·lead_order를 내지 않는다(비움).

    MTM의 bb_facts는 상대 종류만 바꾸고 나머지는 차대차(끼어든 앞차) 모양으로 채운다. 그 값이 근거 카드에 "상대가 앞차였어요"로
    나오고 판정 도표 고르기도 흐트러뜨려서, 틀린 값을 내느니 질문으로 받는다. 복사본(video_lib/bb_facts.py)은 고치지 않고 여기서 거른다."""
    if out.get("status") not in ("ok", "no_collision") or not out.get("facts"):
        return
    other = out["facts"]["parties"].get("other") or {}
    cls = other.get("cls")
    if (cls.get("value") if isinstance(cls, dict) else cls) not in PED_BIKE_CLS:
        return
    for key in CAR_ONLY_PARTY_KEYS:
        other.pop(key, None)


def analyze(video_path, start_time=None, *, work_dir=None, progress=None, collision_t=None, **opts):
    """영상 → bb-0.2 출력(dict). 예외 대신 status로 실패를 알린다 (영상을 못 열면 failed / video_unreadable)

    collision_t: 사용자가 고른 사고 순간(초). 주면 자동으로 찾지 않고 그 순간으로 분석한다(상대 고르기·종류 신호·장면·facts가 모두 그 순간 기준).
    없으면(None) 자동으로 찾는다."""
    import cv2
    cap = cv2.VideoCapture(video_path)
    opened = cap.isOpened() and cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0
    cap.release()
    if not opened:
        return _failed("video_unreadable", "영상을 열 수 없어요")
    from src.analyze import ego_motion, track_video
    from src.blackbox.video_lib import bb_crosswalk, bb_kind, bb_output, bb_partner, bb_scene

    own = work_dir is None
    case_dir = tempfile.mkdtemp(prefix="hmtm_mtm_") if own else work_dir
    os.makedirs(case_dir, exist_ok=True)

    def report(n):
        if progress:
            progress(int(n))

    try:
        saved = track_video.MODEL, track_video.HELPER_MODEL, track_video.IMGSZ, track_video.CONF
        track_video.MODEL, track_video.HELPER_MODEL, track_video.IMGSZ, track_video.CONF = BB_MODEL, "", BB_IMGSZ, BB_CONF
        try:
            track_video.run(video_path, case_dir, scene_cut=False, progress=_track_progress(report) if progress else None)
        finally:
            track_video.MODEL, track_video.HELPER_MODEL, track_video.IMGSZ, track_video.CONF = saved
        report(TRACK_SHARE)
        ego_motion.run(video_path, case_dir)
        bb_partner.run(case_dir, collision_t=collision_t)
        report(TRACK_SHARE + 4)
        bb_kind.run(case_dir, video_path, model_path=KIND_MODEL, imgsz=KIND_IMGSZ, conf=KIND_CONF)
        report(TRACK_SHARE + 6)
        # 장면(교차로 모양, M6)·횡단보도(M5) 모델은 학습이 끝나 파일을 두면 켜진다. 없으면 건너뛰고 HMTM이 사용자에게 묻는다
        bb_scene.run(case_dir, video_path, model_path=SCENE_MODEL)
        bb_crosswalk.run(case_dir, video_path, model_path=CROSSWALK_MODEL, conf=CROSSWALK_CONF)
        report(TRACK_SHARE + 9)
        out = bb_output.to_bb02(case_dir, video_path, answers=opts.get("answers"))
        _no_collision_if_unfound(out, case_dir)
        _drop_car_facts_for_ped_bike(out)
        report(100)
        return out
    finally:
        if own:
            shutil.rmtree(case_dir, ignore_errors=True)
