"""블랙박스 사건 저장 (docs/design-blackbox.md 3.5)

기존 서버 DB 파일(src.server.db.connect)을 같이 쓰고, 표 bb_cases는 여기서 CREATE TABLE IF NOT EXISTS로 만든다
(db.py는 고치지 않음, 차량 사건 store와 같은 방식). 영상은 행에 넣지 않고 사건 폴더 BB_DIR/<id>/에
분석하는 동안만 둔다 (분석이 끝나면 지움, 확정 Q13).

  meta              업로드 정보 (원래 파일 이름, 앱이 보낸 촬영 시각 후보·수정 시각)
  vehicle           정리한 차량 기록 (samples 포함) 또는 null
  analyzer_name/_version  결과를 낸 분석기 (영상을 지우므로 어느 분석기의 결과인지 남김)
  bb_facts          분석기 출력 (bb-0.2, bb-0.1도 받음)
  sync              시각 맞추기 결과 (5절)
  answers           사용자 답
  rule_results, rules  차량 규칙 결과·이름
  view              응답(블랙박스 사건 객체) 그대로. GET은 이것을 돌려준다
  video_kept        분석 뒤 영상을 남겼는지 (HMTM_KEEP_VIDEO=1, 개발 모드, 또는 사고 순간 고르기를 기다림)
  video_until       사고 순간 고르기를 기다리며 영상을 둔 기한 (epoch ms, 3.2 Q13 예외). 지나면 영상을 지움. 기다리지 않으면 NULL
  pick              사용자가 고른 사고 순간 {"t", "picked_at", "pending", "review", "until"} (PUT collision) 또는 NULL
"""
import json
import os
import shutil
import time
from contextlib import contextmanager

from src.server import db

BB_DIR = os.environ.get("HMTM_BB_CASES_DIR", os.path.join("data", "bb_cases"))
SCHEMA = """
CREATE TABLE IF NOT EXISTS bb_cases (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  status TEXT NOT NULL,          -- analyzing / needs_answers / done / no_collision / unsupported / failed
  progress INTEGER,
  scenario TEXT,                 -- 가짜 분석기 시나리오 요청 (진짜 분석기는 무시)
  analyzer_name TEXT,
  analyzer_version TEXT,
  meta TEXT NOT NULL,            -- JSON
  vehicle TEXT,                  -- JSON 또는 NULL
  bb_facts TEXT,                 -- JSON (분석이 끝나면)
  sync TEXT,                     -- JSON
  answers TEXT NOT NULL,         -- JSON
  rule_results TEXT,             -- JSON
  rules TEXT,                    -- JSON
  view TEXT NOT NULL,            -- JSON
  judge_version TEXT,
  video_kept INTEGER NOT NULL DEFAULT 0,
  video_until INTEGER,           -- 사고 순간 고르기를 기다리는 영상의 기한 (epoch ms)
  pick TEXT,                     -- JSON: 사용자가 고른 사고 순간
  created_at INTEGER NOT NULL,   -- epoch ms
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS bb_cases_owner ON bb_cases(owner, created_at);
CREATE INDEX IF NOT EXISTS bb_cases_status ON bb_cases(status);
"""
JSON_COLS = ("meta", "vehicle", "bb_facts", "sync", "answers", "rule_results", "rules", "view", "pick")
# 표를 만든 뒤 더한 칸 (이전 DB 파일에는 없음 → ALTER TABLE로 더함, 2026-11-12)
ADDED_COLS = (("video_until", "INTEGER"), ("pick", "TEXT"))
_migrated = set()


@contextmanager
def connect():
    with db.connect() as con:
        con.executescript(SCHEMA)
        if db.DB_PATH not in _migrated:
            have = {r[1] for r in con.execute("PRAGMA table_info(bb_cases)")}
            for name, kind in ADDED_COLS:
                if name not in have:
                    con.execute(f"ALTER TABLE bb_cases ADD COLUMN {name} {kind}")
            _migrated.add(db.DB_PATH)
        yield con


def now_ms():
    return int(time.time() * 1000)


def _dump(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)


def case_dir(case_id):
    return os.path.join(BB_DIR, case_id)


def analyzing_view(case_id, now, progress=0):
    return {"id": case_id, "status": "analyzing", "progress": progress, "created_at": now, "updated_at": now}


def create(owner, meta, vehicle, scenario=None):
    """새 사건 (status analyzing). 반환: 사건 id. 영상은 부르는 쪽이 case_dir(id)에 쓴다"""
    cid, now = db.new_id(), now_ms()
    with connect() as con:
        con.execute("INSERT INTO bb_cases (id, owner, status, progress, scenario, meta, vehicle, answers, view, "
                    "created_at, updated_at) VALUES (?, ?, 'analyzing', 0, ?, ?, ?, '{}', ?, ?, ?)",
                    (cid, owner, scenario, _dump(meta), _dump(vehicle), _dump(analyzing_view(cid, now)), now, now))
    os.makedirs(case_dir(cid), exist_ok=True)
    return cid


def get(case_id):
    with connect() as con:
        r = con.execute("SELECT * FROM bb_cases WHERE id = ?", (case_id,)).fetchone()
    if r is None:
        return None
    out = dict(r)
    for k in JSON_COLS:
        out[k] = json.loads(out[k]) if out[k] is not None else None
    out["video_kept"] = bool(out["video_kept"])
    return out


def set_progress(case_id, progress):
    with connect() as con:
        r = con.execute("SELECT view FROM bb_cases WHERE id = ? AND status = 'analyzing'", (case_id,)).fetchone()
        if r is None:
            return
        view = json.loads(r["view"])
        view["progress"] = progress
        con.execute("UPDATE bb_cases SET progress = ?, view = ? WHERE id = ?", (progress, _dump(view), case_id))


def finish(case_id, status, bb_facts, sync, view, record=None, video_kept=False, video_until=None, pick=None):
    """분석이 끝난 사건 저장. record: adapter.build 결과(status ok일 때) 또는 None. 반환: 저장한 view.
    video_until: 사고 순간 고르기를 기다리며 영상을 둔 기한 (없으면 NULL). pick: 고른 사고 순간 기록 (그대로 둘 때는 행의 값)"""
    row = get(case_id)
    if row is None:
        return None
    now = max(now_ms(), row["updated_at"])
    an = (bb_facts or {}).get("analyzer") or {}
    view = {"id": case_id, "status": status, "progress": 100, "created_at": row["created_at"], "updated_at": now,
            **view}
    with connect() as con:
        con.execute("UPDATE bb_cases SET status = ?, progress = 100, analyzer_name = ?, analyzer_version = ?, "
                    "bb_facts = ?, sync = ?, rule_results = ?, rules = ?, view = ?, judge_version = ?, video_kept = ?, "
                    "video_until = ?, pick = ?, updated_at = ? WHERE id = ?",
                    (status, an.get("name"), an.get("version"), _dump(bb_facts), _dump(sync),
                     _dump(record["rule_results"] if record else None), _dump(record["rules"] if record else None),
                     _dump(view), record.get("judge_version") if record else None, int(bool(video_kept)), video_until,
                     _dump(pick if pick is not None else row["pick"]), now, case_id))
    return view


def start_pick(case_id, pick):
    """PUT collision: 고른 사고 순간을 남기고 다시 분석 줄로 (status analyzing). 반환: 분석 중 view"""
    row = get(case_id)
    if row is None:
        return None
    now = max(now_ms(), row["updated_at"] + 1)
    view = dict(analyzing_view(case_id, row["created_at"]), updated_at=now)
    with connect() as con:
        con.execute("UPDATE bb_cases SET status = 'analyzing', progress = 0, pick = ?, view = ?, updated_at = ? "
                    "WHERE id = ?", (_dump(pick), _dump(view), now, case_id))
    return view


def waiting_videos(before):
    """사고 순간 고르기 기한(video_until)이 before 이하인 사건 id (분석 중인 사건은 뺌)"""
    with connect() as con:
        rs = con.execute("SELECT id FROM bb_cases WHERE video_until IS NOT NULL AND video_until <= ? "
                         "AND status != 'analyzing' ORDER BY video_until", (before,))
        return [r["id"] for r in rs]


def end_wait(case_id, view, video_kept):
    """고르기 기한이 지남: video_until을 비우고 view(collision_review)를 바꿈. updated_at은 그대로"""
    with connect() as con:
        con.execute("UPDATE bb_cases SET video_until = NULL, video_kept = ?, view = ? WHERE id = ?",
                    (int(bool(video_kept)), _dump(view), case_id))


def update_answers(case_id, answers, view, record):
    """PUT answers: 답과 다시 판정한 결과로 덮어씀. id·created_at은 그대로, updated_at만 바뀜.
    반환: 저장한 view. 행이 없으면 None"""
    row = get(case_id)
    if row is None:
        return None
    now = max(now_ms(), row["updated_at"] + 1)
    view = {"id": case_id, "status": view["status"], "progress": 100, "created_at": row["created_at"],
            "updated_at": now, **{k: v for k, v in view.items() if k not in ("id", "created_at", "updated_at")}}
    with connect() as con:
        con.execute("UPDATE bb_cases SET status = ?, answers = ?, rule_results = ?, rules = ?, view = ?, "
                    "judge_version = ?, updated_at = ? WHERE id = ?",
                    (view["status"], _dump(answers), _dump(record["rule_results"]), _dump(record["rules"]),
                     _dump(view), record.get("judge_version"), now, case_id))
    return view


def list_owner(owner, before=None, limit=20):
    """회원의 사건 (최근 것부터, created_at < before). 목록에 쓸 칸만 (bb_facts·차량 기록 원본은 읽지 않음)"""
    with connect() as con:
        rs = con.execute("SELECT id, status, progress, scenario, meta, sync, view, created_at, updated_at, "
                         "vehicle IS NOT NULL AS has_vehicle "
                         "FROM bb_cases WHERE owner = ? AND created_at < ? ORDER BY created_at DESC, id DESC LIMIT ?",
                         (owner, before if before is not None else now_ms() + 1, limit)).fetchall()
    out = []
    for r in rs:
        d = dict(r)
        for k in ("meta", "sync", "view"):
            d[k] = json.loads(d[k]) if d[k] is not None else None
        out.append(d)
    return out


def analyzing_ids(owner=None):
    """서버를 다시 켰을 때 다시 넣을 사건 (3.4). owner를 주면 그 회원 것만 (전체 삭제 때 분석 멈춤)"""
    with connect() as con:
        if owner is None:
            rs = con.execute("SELECT id FROM bb_cases WHERE status = 'analyzing' ORDER BY created_at")
        else:
            rs = con.execute("SELECT id FROM bb_cases WHERE status = 'analyzing' AND owner = ? ORDER BY created_at",
                             (owner,))
        return [r["id"] for r in rs]


def delete(case_id):
    with connect() as con:
        con.execute("DELETE FROM bb_cases WHERE id = ?", (case_id,))
    shutil.rmtree(case_dir(case_id), ignore_errors=True)


def delete_owner(owner):
    """회원의 블랙박스 사건 전부 (탈퇴). 지운 개수"""
    with connect() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM bb_cases WHERE owner = ?", (owner,))]
        con.execute("DELETE FROM bb_cases WHERE owner = ?", (owner,))
    for cid in ids:
        shutil.rmtree(case_dir(cid), ignore_errors=True)
    return len(ids)
