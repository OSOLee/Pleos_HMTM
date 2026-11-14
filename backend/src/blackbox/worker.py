"""블랙박스 분석 작업자 프로세스 (docs/design-blackbox.md 3.4, 확정 Q6)

  cd backend
  $env:HMTM_BB_ANALYZER="mtm"; .venv\\Scripts\\python -m src.blackbox.worker      # API 서버(uvicorn)와 따로 띄움

HMTM_BB_ANALYZER=mtm이면 API 프로세스는 사건 행(status analyzing)과 영상만 만들고, 이 작업자가 DB에서 analyzing 사건을
오래된 것부터 하나씩 꺼내 분석한다 (api.analyze_case를 그대로 씀). 따로 작업 표를 두지 않고 bb_cases.status가 곧 작업 줄이다.

- **한 작업자 프로세스에서 분석은 한 번에 하나.** video_analyzer가 track_video 모듈 전역(MODEL·IMGSZ·CONF)을 분석 동안만
  바꿔치기하므로 같은 프로세스에서 둘이 겹치면 안 된다. 이 루프는 스레드 하나로 차례로 돌고, MtmAnalyzer.analyze도 잠금으로 막는다.
- 작업자는 하나만 띄운다 (둘을 띄우면 같은 사건을 두 번 분석할 수 있음. 막는 장치는 없음).
- 작업자를 다시 켜면 analyzing으로 남은 사건(분석 도중 꺼진 것 포함)부터 다시 분석한다. 영상은 분석이 끝나야 지우므로 남아 있다.
- 분석 중에 사건이 지워지면(DELETE) 진행률 알림에서 DB 행이 없는 것을 보고 멈추고, 사건 폴더를 다시 지운다.
- 켤 때 가중치 목록(models.json)을 검사해 로그에 남긴다. 준비가 안 됐어도 끄지 않고, 그 사이 사건은 failed / analyzer_not_ready.
"""
import argparse
import logging
import os
import time

from src.blackbox import analyzer, api, store

POLL_SEC = float(os.environ.get("HMTM_BB_WORKER_POLL", "1.0"))
log = logging.getLogger("hmtm.blackbox.worker")


def gone(case_id):
    """분석 중에 사건이 지워졌는지 (API 프로세스의 DELETE)"""
    return store.get(case_id) is None


def next_case():
    ids = store.analyzing_ids()
    return ids[0] if ids else None


def run_one(case_id):
    """사건 하나 분석. 반환: 저장한 view 또는 None (지워졌거나 이미 끝남)"""
    try:
        return api.analyze_case(case_id, is_cancelled=gone)
    except api.Cancelled:
        return None
    except Exception:   # 한 사건이 실패해도 다음 사건은 돌림 (API 스레드와 같은 처리)
        log.exception("블랙박스 분석 실패: %s", case_id)
        try:
            store.finish(case_id, "failed", None, None,
                         {"analysis": {"status": "failed", "reason": "server_error", "message": "분석 중 오류가 났어요"}})
        except Exception:
            log.exception("실패 상태 저장 실패: %s", case_id)
        return None
    finally:
        if gone(case_id):   # 분석 중에 지움: 분석기가 쓰던 파일까지 남김없이
            store.delete(case_id)


def run_once():
    """analyzing 사건 하나를 꺼내 분석. 했으면 True (시험·한 번만 돌릴 때)"""
    cid = next_case()
    if cid is None:
        return False
    log.info("분석 시작: %s", cid)
    run_one(cid)
    # 분석기가 예외 없이 끝났는데 행이 analyzing으로 남는 일은 없지만(finish가 바꿈), 남으면 무한 반복을 막음
    row = store.get(cid)
    if row is not None and row["status"] == "analyzing":
        store.finish(cid, "failed", None, None,
                     {"analysis": {"status": "failed", "reason": "server_error", "message": "분석 중 오류가 났어요"}})
    return True


def report_ready():
    """켤 때 분석기 준비 상태를 로그에 남김. 반환 (준비됨, 문장)"""
    try:
        an = analyzer.get_analyzer()
    except analyzer.AnalyzerNotReady as e:
        log.warning("분석기 준비 안 됨: %s", e.message)
        return False, e.message
    for role, r in (getattr(an, "report", None) or {}).items():
        log.info("가중치 %s: %s %s", role, r["status"], r.get("path"))
    log.info("분석기 %s %s 준비됨", an.name, an.version)
    return True, None


def main(argv=None):
    p = argparse.ArgumentParser(description="블랙박스 분석 작업자 (HMTM_BB_ANALYZER=mtm)")
    p.add_argument("--once", action="store_true", help="남은 사건을 모두 분석하고 끝냄")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if not analyzer.uses_worker():
        log.warning("HMTM_BB_ANALYZER=%s: 작업자는 mtm일 때만 쓴다 (fake는 API 프로세스 스레드가 분석). 그래도 돌림",
                    analyzer.chosen_name())
    report_ready()
    while True:
        if run_once():
            continue
        if args.once:
            return 0
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
