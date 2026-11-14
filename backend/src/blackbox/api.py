"""블랙박스 사건 API (docs/design-blackbox.md 3.2~3.4, 최종 요청·응답 형식은 3.6)

  POST   /api/bb-cases               multipart: video(파일, 필수), meta(JSON 문자열), vehicle(JSON 문자열), scenario → 202 analyzing
  GET    /api/bb-cases                내 사건 목록 (최근 것부터, ?before=<created_at>&limit=20, 최대 50)
  GET    /api/bb-cases/{id}          분석 중이면 {status: analyzing, progress}, 끝나면 블랙박스 사건 객체
  PUT    /api/bb-cases/{id}/answers  {"answers": {...}} 지금까지의 답 전부 → 저장한 bb_facts·차량 기록으로 처음부터 다시 판정
  PUT    /api/bb-cases/{id}/collision {"t": 초} 사용자가 고른 사고 순간(영상 안) → 202 analyzing. 그 순간으로 분석기를 다시 돌림
  DELETE /api/bb-cases/{id}          204. 행(bb_facts·차량 기록·답·결과)과 사건 폴더. 분석 중이면 분석도 멈춤
  DELETE /api/bb-cases               200 {"deleted": n}. 내 사건 전부 (앱 "모든 기록 삭제")

차량 기록은 참고 자료다 (4.4): 응답의 result는 영상·사용자 답 기준, result_with_vehicle·vehicle_effects·vehicle_timeline이 차량 기록 쪽.

분석을 돌리는 곳 (확정 Q6, 3.4): 가짜 분석기(fake)는 API 프로세스 안의 스레드 하나가 차례로 하고, 서버를 켤 때 analyzing으로
남은 사건을 다시 넣는다. 진짜 분석기(HMTM_BB_ANALYZER=mtm)는 작업자 프로세스(src/blackbox/worker.py)가 DB의 analyzing 사건을
하나씩 꺼내 분석한다 (API는 행과 영상만 만들고, 작업자를 다시 켜면 analyzing으로 남은 사건부터 다시 함).
사고 순간이 불확실하면(analyzer.collision_review) 시각 맞추기를 none으로 두고 응답에 collision_review를 넣는다 (3.6).
분석이 끝나면 원본 영상을 지운다. HMTM_KEEP_VIDEO=1(개발 모드)이면 남긴다 (확정 Q13).
예외: 사고 순간이 없거나 불확실하면(collision_review.needed) 사용자가 순간을 고를 때까지 영상을 7일(PICK_DAYS) 둔다.
고르면(PUT collision) 그 순간으로 다시 분석하고, 판정이 되면 영상을 지운다. 7일이 지나면 API 프로세스가 영상을 지운다 (expire_videos).

src/server/app.py 맨 끝의 한 줄로 등록한다 (차량 사건과 같은 방식):
  from src.blackbox.api import install as install_bb; install_bb(app)
오류 모양은 차량 사건과 같다 ({"error", "message"}, VehicleError 처리기를 같이 씀).
"""
import json
import logging
import os
import queue
import threading
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from src.blackbox import adapter, analyzer, fake, store, sync
from src.server import auth
from src.vehicle import clock
from src.vehicle.api import json_body, me
from src.vehicle.samples import (EGO_CLASSES, MAX_SAMPLES, VehicleError, _check_sample, _is_int)

log = logging.getLogger("hmtm.blackbox")
router = APIRouter(prefix="/api/bb-cases")
MAX_UPLOAD_MB = int(os.environ.get("MTM_MAX_UPLOAD_MB", "200"))   # 영상 사건과 같은 제한
KEEP_ENV = "HMTM_KEEP_VIDEO"
VIDEO_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".ts", ".3gp")
PICK_DAYS = 7                                      # 사고 순간 고르기를 기다리며 영상을 두는 기간 (3.2 Q13 예외)
PICK_MS = PICK_DAYS * 24 * 3600 * 1000
EXPIRE_EVERY_SEC = float(os.environ.get("HMTM_BB_EXPIRE_SEC", "3600"))   # 기한 지난 영상을 찾는 간격


def keep_video():
    return os.environ.get(KEEP_ENV) == "1"


# ---------- 요청 검사 ----------

def _json_form(text, name):
    if text is None or text == "":
        return None
    try:
        v = json.loads(text)
    except ValueError:
        raise VehicleError("request_invalid", f"{name}은 JSON 문자열이어야 해요")
    if not isinstance(v, dict):
        raise VehicleError("request_invalid", f"{name}은 JSON 객체여야 해요")
    return v


def validate_vehicle(body):
    """첨부 차량 기록 검사 (차량 명세 2.1에서 t_event를 뺀 것). 구간은 최대 300초 (확정 Q12).
    맞으면 {range, samples, vehicle_cls, client}"""
    rng = body.get("range")
    if not (isinstance(rng, dict) and _is_int(rng.get("from")) and _is_int(rng.get("to"))):
        raise VehicleError("range_invalid", "vehicle.range.from, to는 epoch 밀리초 정수여야 해요")
    lo, hi = rng["from"], rng["to"]
    if lo >= hi:
        raise VehicleError("range_invalid", "vehicle.range.from은 range.to보다 앞이어야 해요")
    if hi - lo > sync.MAX_WINDOW_MS:
        raise VehicleError("range_invalid", f"차량 기록 구간은 {sync.MAX_WINDOW_MS // 1000}초까지 올릴 수 있어요")
    samples = body.get("samples")
    if not isinstance(samples, list):
        raise VehicleError("request_invalid", "vehicle.samples는 배열이어야 해요")
    if not samples:
        raise VehicleError("samples_empty", "차량 기록이 비어 있어요")
    if len(samples) > MAX_SAMPLES:
        raise VehicleError("samples_too_many", f"차량 기록은 {MAX_SAMPLES:,}개까지 올릴 수 있어요")
    out = []
    for i, s in enumerate(samples):
        s = _check_sample(i, s, lo, hi)
        if out and s["t"] < out[-1]["t"]:
            raise VehicleError("samples_unsorted", f"samples[{i}]: t가 앞 기록보다 이른 시각이에요 (오름차순이어야 해요)")
        out.append(s)
    if body.get("location") is not None:
        raise VehicleError("location_unsupported", "위치 데이터는 아직 받지 않아요 (location은 null)")
    vehicle = body.get("vehicle") or {}
    if not isinstance(vehicle, dict):
        raise VehicleError("request_invalid", "vehicle.vehicle은 객체여야 해요")
    cls = vehicle.get("cls") or "car"
    if cls not in EGO_CLASSES:
        raise VehicleError("request_invalid", f"vehicle.vehicle.cls는 {', '.join(EGO_CLASSES)} 중 하나여야 해요")
    client = body.get("client") or {}
    if not isinstance(client, dict):
        raise VehicleError("request_invalid", "vehicle.client는 객체여야 해요")
    return {"range": {"from": lo, "to": hi}, "samples": out, "vehicle_cls": cls, "client": client}


def crop_vehicle(vreq, start_ms, duration_s, margin_ms=sync.MARGIN_MS):
    """차량 기록을 영상 구간 [S0 − 여유, S0 + 길이 + 여유](최대 300초)로 자름 (5.5). 시작 시각을 모르면 그대로"""
    if vreq is None or start_ms is None:
        return vreq
    w = sync.vehicle_window(start_ms, duration_s, margin_ms)
    lo, hi = max(w["from"], vreq["range"]["from"]), min(w["to"], vreq["range"]["to"])
    kept = [s for s in vreq["samples"] if lo <= s["t"] <= hi]
    if lo >= hi or not kept:
        return dict(vreq, range={"from": lo, "to": max(lo, hi)}, samples=[], cropped=True)
    return dict(vreq, range={"from": lo, "to": hi}, samples=kept, cropped=True)


# ---------- 분석 작업 (스레드 하나) ----------

_jobs = queue.Queue()
_worker = None
_lock = threading.Lock()
_busy = set()
_cancelled = set()      # 분석 중에 지운 사건 (DELETE). 분석기 진행률 알림에서 멈추고, 끝나면 사건 폴더를 다시 지움


class Cancelled(Exception):
    """분석 중인 사건이 지워짐"""


def cancel(case_id):
    with _lock:
        if case_id in _busy:
            _cancelled.add(case_id)


def cancelled(case_id):
    with _lock:
        return case_id in _cancelled


def enqueue(case_id):
    """분석 줄에 넣기. 작업자 프로세스 모드(mtm)면 아무것도 안 함: 작업자가 DB의 analyzing 행을 가져감"""
    global _worker
    if analyzer.uses_worker():
        return
    with _lock:
        _busy.add(case_id)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="bb-analyzer", daemon=True)
            _worker.start()
    _jobs.put(case_id)


def idle():
    """분석 줄이 비었는지 (시험용)"""
    with _lock:
        return not _busy


def _loop():
    while True:
        cid = _jobs.get()
        try:
            analyze_case(cid)
        except Exception:   # 한 사건이 실패해도 다음 사건은 돌림
            log.exception("블랙박스 분석 실패: %s", cid)
            try:
                store.finish(cid, "failed", None, None,
                             {"analysis": {"status": "failed", "reason": "server_error", "message": "분석 중 오류가 났어요"}})
            except Exception:
                log.exception("실패 상태 저장 실패: %s", cid)
        finally:
            with _lock:
                _busy.discard(cid)
                was_cancelled = cid in _cancelled
                _cancelled.discard(cid)
            if was_cancelled:   # 분석 중에 지움: 분석기가 쓰던 파일까지 남김없이
                store.delete(cid)


def video_file(case_id):
    d = store.case_dir(case_id)
    if not os.path.isdir(d):
        return None
    for name in sorted(os.listdir(d)):
        if name.startswith("video."):
            return os.path.join(d, name)
    return None


def _delete_video(path):
    if path and not keep_video():
        try:
            os.remove(path)
        except OSError:
            log.warning("영상을 지우지 못했어요: %s", path)
            return True
        return False
    return path is not None


def _analysis_view(bb):
    return {"status": bb["status"], "reason": bb.get("reason"), "message": bb.get("message"),
            "analyzer": bb.get("analyzer"), "video": bb.get("video"), "scenario": (bb.get("hints") or {}).get("fake")}


def analyze_case(case_id, is_cancelled=None):
    """분석 → 영상 삭제 → 시각 맞추기 → 합치기·판정 → 저장 (3.3).
    is_cancelled(case_id): 분석 중에 사건이 지워졌는지 (기본: 이 프로세스의 cancel 표시. 작업자는 DB 행이 있는지로 봄)"""
    is_cancelled = is_cancelled or cancelled
    row = store.get(case_id)
    if row is None or row["status"] != "analyzing":
        return None
    path = video_file(case_id)
    meta = row["meta"] or {}
    filename = meta.get("filename")
    if path is None:
        return store.finish(case_id, "failed", None, None,
                            {"analysis": {"status": "failed", "reason": "video_missing",
                                          "message": "분석할 영상이 없어요"}})
    pre = sync.start_candidates(filename, meta, path)
    start = sync.pick_start(pre)

    def progress(n):
        if is_cancelled(case_id):
            raise Cancelled(case_id)
        store.set_progress(case_id, n)

    pick = row["pick"] if (row.get("pick") or {}).get("pending") else None   # PUT collision으로 다시 분석
    bb = analyzer.run(path, {"start_ms": start["start_ms"], "source": start["source"]} if start else None,
                      work_dir=store.case_dir(case_id), progress=progress,
                      scenario=row["scenario"], filename=filename, collision_t=pick["t"] if pick else None)
    if is_cancelled(case_id):
        return None                                                    # 사건 폴더는 _loop(작업자)가 지움
    duration = (bb.get("video") or {}).get("duration_s")
    candidates = sync.start_candidates(filename, meta, path, duration)   # 수정 시각은 길이를 알아야 계산

    review = analyzer.collision_review(bb)
    if pick is not None:
        last = {"t": pick["t"], "picked_at": pick["picked_at"], "status": bb["status"], "reason": bb.get("reason"),
                "message": bb.get("message")}
        if bb["status"] == "ok" and not review["needed"]:
            review["picked"] = {"t": pick["t"], "picked_at": pick["picked_at"]}
        elif row["bb_facts"] is not None:
            # 고른 순간으로도 판정하지 못함: 고르기 전 분석 결과로 되돌리고(판정·답 그대로) 다시 고를 수 있게 영상을 둠
            bb = row["bb_facts"]
            review = dict(analyzer.collision_review(bb), last_pick=last)
        pick = dict(pick, pending=False, result=last)
    # 사고 순간을 사용자가 정해야 하면 영상을 둠 (Q13의 예외). 기한은 처음 분석이 끝난 때부터 7일 (다시 골라도 늘지 않음)
    until = None
    if review["needed"]:
        until = (pick or {}).get("until") or store.now_ms() + PICK_MS
        kept = True
    else:
        kept = _delete_video(path)                                    # 확정 Q13: 분석이 끝나면 원본 삭제
    review = pick_window(review, until)
    analysis = _analysis_view(bb)
    if bb["status"] != "ok":
        s = sync.sync(candidates, None, None, server_ms=row["created_at"])
        if row["vehicle"]:   # 판정은 안 하지만 시계 경고는 차량 기록도 봄
            s["clock_warnings"] = clock.warnings(row["created_at"], s["start_ms"], s["start_source"],
                                                 row["vehicle"]["range"])
        return store.finish(case_id, bb["status"], bb, s,
                            {"analysis": analysis, "sync": s, "collision_review": review}, video_kept=kept,
                            video_until=until, pick=pick)

    s, vreq = match_clock(bb, candidates, row["vehicle"], row["created_at"], uncertain=review["needed"])
    record = adapter.build(bb, vreq, s, row["answers"] or {})
    view = {**record["view"], "analysis": analysis, "sync": s, "collision_review": review}
    return store.finish(case_id, view["status"], bb, s, view, record, video_kept=kept, video_until=until, pick=pick)


def pick_window(review, until):
    """collision_review에 고르기 가능 여부: can_pick(영상이 남아 있어 PUT collision을 받음), pick_until(기한, epoch ms)"""
    return dict(review, can_pick=bool(review["needed"] and until), pick_until=until if review["needed"] else None)


def _cropped(vehicle, bb, start_ms, start_source):
    duration = (bb.get("video") or {}).get("duration_s")
    vreq = crop_vehicle(vehicle, start_ms, duration, sync.margin_for(start_source))
    return vreq if vreq and vreq["samples"] else None


def match_clock(bb, candidates, vehicle, server_ms=None, uncertain=False):
    """시각 맞추기 (5절): 차량 기록을 영상 구간으로 자르고 sync. 반환 (sync, 자른 차량 기록 또는 None).
    server_ms: 서버가 사건을 받은 시각 (영상·차량 기록 시계가 하루 넘게 다르면 sync.clock_warnings).
    uncertain: 영상 사고 순간이 불확실 (collision_review.needed) → 등급 none, 차량 기록 값을 쓰지 않음"""
    best = sync.pick_start(candidates) or {}
    vreq = _cropped(vehicle, bb, best.get("start_ms"), best.get("source"))
    s = sync.sync(candidates, bb["facts"]["collision"]["t"], vreq["range"] if vreq else None,
                  samples=vreq["samples"] if vreq else None, ego_motion=bb.get("ego_motion"),
                  duration_s=(bb.get("video") or {}).get("duration_s"),
                  uploaded_range=vehicle["range"] if vehicle else None, server_ms=server_ms,
                  collision_uncertain=uncertain)
    return s, vreq


def expire_videos(now=None):
    """사고 순간 고르기 기한(7일)이 지난 사건의 영상을 지움 (HMTM_KEEP_VIDEO=1이면 파일은 남김). 고르기는 끝남:
    collision_review.can_pick false, expired true (needed는 그대로: 사고 순간은 여전히 확인되지 않음). 반환: 처리한 사건 수"""
    now = store.now_ms() if now is None else now
    n = 0
    for cid in store.waiting_videos(now):
        row = store.get(cid)
        if row is None:
            continue
        path = video_file(cid)
        kept = _delete_video(path) if path else False
        view = dict(row["view"])
        view["collision_review"] = dict(view.get("collision_review") or {}, can_pick=False, pick_until=None,
                                        expired=True)
        store.end_wait(cid, view, kept)
        log.info("사고 순간을 고르지 않아 영상을 지웠어요 (%d일): %s", PICK_DAYS, cid)
        n += 1
    return n


_expiry = None


def _expiry_loop():
    while True:
        try:
            expire_videos()
        except Exception:
            log.exception("기한 지난 영상 지우기 실패")
        time.sleep(EXPIRE_EVERY_SEC)


def start_expiry():
    """API 프로세스에서 기한 지난 영상을 주기적으로 지우는 스레드 (fake·mtm 모두. 작업자 프로세스는 하지 않음)"""
    global _expiry
    with _lock:
        if _expiry is None or not _expiry.is_alive():
            _expiry = threading.Thread(target=_expiry_loop, name="bb-video-expiry", daemon=True)
            _expiry.start()


def rejudge(row, answers):
    """PUT answers: 저장한 bb_facts·차량 기록·시각 맞추기로 처음부터 다시 판정 (영상은 지워서 다시 분석하지 않음)"""
    bb, s = row["bb_facts"], row["sync"]
    vreq = _cropped(row["vehicle"], bb, s.get("start_ms"), s.get("start_source"))
    record = adapter.build(bb, vreq, s, answers)
    view = {**record["view"], "analysis": row["view"].get("analysis"), "sync": s,
            "collision_review": row["view"].get("collision_review") or analyzer.collision_review(bb)}
    return store.update_answers(row["id"], answers, view, record)


def resume():
    """서버를 켤 때: analyzing으로 남은 사건을 다시 넣음 (영상은 분석이 끝나야 지우므로 남아 있음).
    작업자 프로세스 모드(mtm)면 작업자가 켜질 때 스스로 가져가므로 여기서는 아무것도 안 함"""
    if analyzer.uses_worker():
        return
    for cid in store.analyzing_ids():
        enqueue(cid)


# ---------- 주소 ----------

def own_case(case_id, user):
    row = store.get(case_id)
    if row is None or row["owner"] != user["id"]:
        raise VehicleError("bb_case_not_found", "블랙박스 사건을 찾지 못했어요.", status=404)
    return row


def _check_analyzer(scenario):
    """분석기를 쓸 수 있는지. 가짜 분석기면 시나리오 이름도 확인. 진짜 분석기면 scenario는 무시(None)"""
    try:
        an = analyzer.get_analyzer()
    except analyzer.AnalyzerNotReady as e:
        raise VehicleError("analyzer_not_ready", e.message, status=503)
    if an.name != fake.NAME:
        return None
    if scenario and fake.load_scenario(scenario) is None:
        raise VehicleError("scenario_unknown", f"가짜 분석기에 없는 시나리오예요: {scenario} "
                                               f"(있는 것: {', '.join(fake.scenario_names())})")
    return scenario or None


@router.post("", status_code=202)
def create_case(video: UploadFile = File(...), meta: str | None = Form(None), vehicle: str | None = Form(None),
                scenario: str | None = Form(None), user=Depends(me)):
    """영상 + 선택 차량 기록 올리기 → 분석 줄에 넣고 바로 analyzing으로 답함"""
    meta_d = _json_form(meta, "meta") or {}
    vreq = None
    vbody = _json_form(vehicle, "vehicle")
    if vbody is not None:
        vreq = validate_vehicle(vbody)
    scenario = _check_analyzer(scenario)
    name = os.path.basename(meta_d.get("filename") or video.filename or "video.mp4")
    meta_d["filename"] = name
    ext = os.path.splitext(name)[1].lower()
    ext = ext if ext in VIDEO_EXTS else ".mp4"

    cid = store.create(user["id"], meta_d, vreq, scenario)
    path = os.path.join(store.case_dir(cid), "video" + ext)
    size = 0
    with open(path, "wb") as f:
        while chunk := video.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                break
            f.write(chunk)
    if size == 0 or size > MAX_UPLOAD_MB << 20:
        store.delete(cid)
        if size == 0:
            raise VehicleError("video_empty", "영상 파일이 비어 있어요")
        raise VehicleError("video_too_large", f"영상은 {MAX_UPLOAD_MB}MB까지 올릴 수 있어요", status=413)
    enqueue(cid)
    return store.get(cid)["view"]


JUDGED = ("needs_answers", "done")
LIST_MAX = 50


def summary(row):
    """사건 목록 한 줄 (3.6 GET /api/bb-cases). 앱의 지난 분석 화면"""
    view, meta, s = row["view"] or {}, row["meta"] or {}, row["sync"] or {}
    result = view.get("result") or {}
    with_v = view.get("result_with_vehicle") or {}
    other = view.get("other_cls") or {}
    analysis = view.get("analysis") or {}
    dq = view.get("data_quality") or {}
    return {
        "id": row["id"], "status": row["status"], "progress": row["progress"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "filename": meta.get("filename"), "recorded_at_ms": s.get("start_ms"),
        "collision_t": (view.get("event") or {}).get("collision_t"),
        "other_cls": {"value": other.get("value"), "label": other.get("label"), "source": other.get("source")}
        if other else None,
        "chapter": result.get("chapter"), "rule_id": result.get("rule_id"), "title": result.get("title"),
        "fault_by_party": result.get("fault_by_party"), "fault_display": result.get("fault_display"),
        "provisional": result.get("provisional"), "remaining_count": view.get("remaining_count"),
        "reason": analysis.get("reason") if row["status"] not in JUDGED + ("analyzing",) else None,
        # 차량 기록 (2026-11-10): 있는지, 시각 맞추기 등급, 입증하면 바뀌는 비율
        "vehicle_record": dq.get("vehicle_record") if row["status"] in JUDGED else bool(row.get("has_vehicle")),
        "sync_grade": s.get("grade"),
        "fault_display_with_vehicle": with_v.get("fault_display"),
        "vehicle_changes": any(e.get("applied") for e in view.get("vehicle_effects") or []),
        "collision_review_needed": bool((view.get("collision_review") or {}).get("needed")),
        "collision_pick_until": (view.get("collision_review") or {}).get("pick_until"),   # 고르기 기한 (없으면 null)
    }


@router.get("")
def list_cases(before: int | None = None, limit: int = 20, user=Depends(me)):
    """내 블랙박스 사건 목록 (최근 것부터). 다음 쪽은 마지막 사건의 created_at을 before로"""
    limit = max(1, min(limit, LIST_MAX))
    return [summary(r) for r in store.list_owner(user["id"], before, limit)]


@router.get("/{case_id}")
def get_case(case_id: str, user=Depends(me)):
    """분석 중이면 진행률, 끝났으면 블랙박스 사건 객체"""
    return own_case(case_id, user)["view"]


def put_answers(case_id, user, answers):
    row = own_case(case_id, user)
    if row["status"] == "analyzing":
        raise VehicleError("bb_case_analyzing", "아직 영상을 분석하고 있어요. 끝난 뒤에 답해 주세요.", status=409)
    if row["status"] not in JUDGED:
        raise VehicleError("bb_case_not_judged", f"판정하지 않은 사건이에요 (상태 {row['status']})", status=409)
    return rejudge(row, answers)


@router.put("/{case_id}/answers")
async def answer_case(case_id: str, request: Request, user=Depends(me)):
    """지금까지의 답 전부 → 다시 판정. 사용자 답이 차량·영상 값과 다르면 source_conflicts (차량 명세 2.2와 같은 규칙)"""
    body = await json_body(request)
    answers = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(answers, dict):
        raise VehicleError("answers_shape", "answers는 {질문 키: 값} 객체여야 해요")
    return await run_in_threadpool(put_answers, case_id, user, answers)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def put_collision(case_id, user, body):
    """사용자가 고른 사고 순간 (3.2 PUT collision). 영상이 남아 있고 사고 순간 확인이 필요한 사건만.
    받으면 분석 줄에 다시 넣고 analyzing으로 답함 (mtm은 작업자, fake는 API 스레드가 그 순간으로 다시 분석)"""
    if not isinstance(body, dict) or "t" not in body:
        raise VehicleError("request_invalid", '요청은 {"t": 초} 모양이어야 해요')
    t = body["t"]
    row = own_case(case_id, user)
    if row["status"] == "analyzing":
        raise VehicleError("bb_case_analyzing", "아직 영상을 분석하고 있어요. 끝난 뒤에 골라 주세요.", status=409)
    review = (row["view"] or {}).get("collision_review") or {}
    if not review.get("needed"):
        raise VehicleError("collision_not_needed", "이 사건은 사고 순간을 고를 필요가 없어요", status=409)
    if row["video_until"] is not None and row["video_until"] <= store.now_ms():
        expire_videos()
        row = store.get(case_id)
    if row["video_until"] is None or video_file(case_id) is None:
        raise VehicleError("video_gone", f"영상 보관 기간({PICK_DAYS}일)이 지나 영상을 지웠어요. 영상을 다시 올려 주세요",
                           status=410)
    duration = ((row["bb_facts"] or {}).get("video") or {}).get("duration_s")
    if not (_num(t) and t >= 0 and (duration is None or t <= duration + 1e-6)):
        raise VehicleError("collision_invalid", "t는 영상 안의 시각(0 이상, 영상 길이 이하 초)이어야 해요"
                           + (f" (영상 {duration:g}초)" if duration else ""))
    _check_analyzer(None)                                       # mtm 가중치가 준비 안 됐으면 503 (사건은 그대로)
    pick = {"t": round(float(t), 3), "picked_at": store.now_ms(), "pending": True, "until": row["video_until"],
            "review": review}
    view = store.start_pick(case_id, pick)
    enqueue(case_id)
    return view


@router.put("/{case_id}/collision", status_code=202)
async def pick_collision(case_id: str, request: Request, user=Depends(me)):
    """사고 순간 고르기: {"t": 영상 안 초} → 202 analyzing. 끝나면 GET으로 결과 (POST와 같이 폴링)"""
    body = await json_body(request)
    return await run_in_threadpool(put_collision, case_id, user, body)


@router.delete("")
def delete_all(user=Depends(me)):
    """내 블랙박스 사건 전부 삭제 (앱 "모든 기록 삭제"). 분석 중인 사건은 분석도 멈춤. 반환 {"deleted": 개수}"""
    for cid in store.analyzing_ids(user["id"]):
        cancel(cid)
    return {"deleted": store.delete_owner(user["id"])}


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: str, user=Depends(me)):
    """사건 전부 삭제: 행(bb_facts·차량 기록·답·결과)과 사건 폴더(분석 중인 영상·보관 영상). 분석 중이면 분석도 멈춤"""
    row = own_case(case_id, user)
    if row["status"] == "analyzing":
        cancel(case_id)
    store.delete(case_id)
    return Response(status_code=204)


WITHDRAW = ("DELETE", "/api/me")


async def delete_on_withdraw(request: Request, call_next):
    """탈퇴가 끝나면(204) 그 회원의 블랙박스 사건(행·사건 폴더)을 지움 (차량 사건 미들웨어와 같은 방식)"""
    if (request.method, request.url.path) != WITHDRAW:
        return await call_next(request)
    try:
        owner = auth.user_of(request.headers.get("authorization"), signed_up=False)["id"]
    except Exception:
        owner = None
    response = await call_next(request)
    if owner and response.status_code == 204:
        await run_in_threadpool(store.delete_owner, owner)
    return response


def install(app):
    """라우터, 탈퇴 때 블랙박스 사건 삭제, 서버를 켤 때 남은 분석 다시 넣기·기한 지난 영상 지우기 스레드.
    오류 처리기는 차량 사건 install이 건 VehicleError 처리기를 같이 씀 (차량 사건 install 뒤에 부름)"""
    app.include_router(router)
    app.middleware("http")(delete_on_withdraw)
    inner = app.router.lifespan_context   # 이 FastAPI 판에는 add_event_handler가 없어 lifespan을 감쌈

    @asynccontextmanager
    async def lifespan(a):
        await run_in_threadpool(resume)
        start_expiry()
        async with inner(a) as state:
            yield state

    app.router.lifespan_context = lifespan
