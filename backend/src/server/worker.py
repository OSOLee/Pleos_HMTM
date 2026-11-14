"""작업자: jobs 표에서 작업을 하나씩 꺼내 파이프라인(src/app/pipeline.py)을 돌리고 사건 상태를 바꾼다

  cd ~/MTM && .venv/bin/python -m src.server.worker      # API 서버와 따로 띄움 (docs/backend.md 4절)

탐지가 수십 초 동안 CPU를 다 쓰므로 API 서버와 프로세스를 나눈다. 이 프로세스가 torch·YOLO를 한 번만 불러 두어서
답 반영이 매번 라이브러리를 새로 불러오지 않는다 (run_app.py는 실행마다 2.3초).

작업 종류
  prepare  영상을 받자마자: 카메라 확인 → (보정) → 배경 그림 → 탐지
  solve    모서리와 탐지가 둘 다 끝나면: 나머지 단계 → 판정 (답이 있으면 같이)
  answer   답을 받았을 때: 판정 다시 (탐지는 다시 안 함)
"""
import os
import shutil
import time
import traceback

from src.app import pipeline
from src.app.pipeline import InputError
from src.server import db

POLL_SEC = 0.5
CLEAN_EVERY_SEC = 3600   # 보관 기간 지난 사건을 지우는 간격
VIDEO = "video.mp4"
JUDGE_DIR = os.environ.get("MTM_JUDGE_DIR", pipeline.JUDGE_DIR)


def video_path(case_id):
    return os.path.join(db.case_dir(case_id), VIDEO)


def answers_of(case_id):
    p = os.path.join(db.case_dir(case_id), "answers.json")
    return pipeline.load(p) if os.path.exists(p) else {}


def run_prepare(case):
    cid, d = case["id"], db.case_dir(case["id"])
    db.update_case(cid, stage="detect", progress=0)

    def progress(done, total):   # 15프레임마다 불림. DB 쓰기는 몇 ms라 탐지 속도에 영향 없음
        if total > 0:
            db.update_case(cid, progress=min(99, done * 100 // total))

    if pipeline.prepare(d, video_path(cid), case["source"], case["name"], progress=progress) == "unsupported":
        db.update_case(cid, status="unsupported", stage=None)
        return
    db.update_case(cid, prepared=1, stage=None, progress=100)
    if db.get_case(cid)["has_scene"]:   # 모서리가 먼저 와 있었으면 바로 판정
        db.add_job(cid, "solve")
        db.update_case(cid, status="analyzing")
    else:
        db.update_case(cid, status="waiting_scene")


def run_solve(case):
    cid = case["id"]
    app = pipeline.solve(db.case_dir(cid), video_path(cid), answers_of(cid), JUDGE_DIR, case["name"])
    db.update_case(cid, status=app["status"], error=None)


def run_job(job):
    """작업 하나. 사용자 입력 문제(InputError)는 사건에 오류로 남기고 이전 결과 상태로 되돌림.
    그 밖의 예외는 failed (서버 오류)"""
    case = db.get_case(job["case_id"])
    if case is None:   # 작업이 도는 사이에 사건이 지워짐
        db.finish_job(job["id"], "skipped")
        return
    try:
        if job["kind"] == "prepare":
            run_prepare(case)
        else:
            run_solve(case)
        db.finish_job(job["id"])
    except InputError as e:
        app = os.path.join(db.case_dir(case["id"]), "app.json")
        prev = pipeline.load(app)["status"] if os.path.exists(app) else "waiting_scene"
        db.update_case(case["id"], status=prev, stage=None, error={"error": e.code, "message": e.message})
        db.finish_job(job["id"], "failed")
    except Exception as e:   # noqa: BLE001  서버 오류. 자세한 내용은 작업자 로그에만 (사용자 답·영상 이름은 안 남김)
        traceback.print_exc()
        db.update_case(case["id"], status="failed", stage=None,
                       error={"error": "server_error", "message": "분석 중 문제가 생겼어요. 다시 시도해 주세요."})
        db.finish_job(job["id"], "failed")


def remove_case(case_id):
    """사건 표(투표글 포함)와 폴더(영상·결과, 투표글 그림)를 지움"""
    for p in db.rows("SELECT id FROM posts WHERE case_id = ?", case_id):
        shutil.rmtree(os.path.join(db.CASES_DIR, "posts", p["id"]), ignore_errors=True)
    db.delete_case(case_id)
    shutil.rmtree(db.case_dir(case_id), ignore_errors=True)


def clean_expired(now=None):
    """보관함에 저장 안 한 채 보관 기간(기본 7일)이 지난 사건을 지움 (docs/app_flow.md 7절).
    작업이 도는 중인 사건은 다음 번에. 지운 개수를 돌려줌"""
    n = 0
    for cid in db.expired_cases(now):
        if not db.running(cid):
            remove_case(cid)
            n += 1
    return n


def run_once():
    """작업 하나를 처리하면 True, 없으면 False (테스트에서 직접 부름)"""
    job = db.take_job()
    if job is None:
        return False
    run_job(job)
    return True


def main():
    print(f"작업자 시작 (사건 폴더 {db.CASES_DIR})")
    db.requeue_running()   # 지난번 작업자가 작업 도중 꺼졌으면 그 작업을 다시 줄에 세움
    last_clean = 0
    while True:
        if time.time() - last_clean > CLEAN_EVERY_SEC:
            print(f"보관 기간 지난 사건 {clean_expired()}개 지움")
            last_clean = time.time()
        if not run_once():
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
