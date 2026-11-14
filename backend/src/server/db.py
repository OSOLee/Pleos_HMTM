"""서버 표 (SQLite 파일 하나, docs/backend.md 4절, docs/app_flow.md 9절)

  users     회원 (카카오·구글 소셜 로그인)
  sessions  로그인 유지 토큰(refresh)의 id. 로그아웃·탈퇴하면 지워서 그 토큰을 못 쓰게 함
  cases     사건 하나 = 영상 하나. 상태(status)와 결과 폴더(cases/<id>/)
  jobs      작업자가 차례로 가져가는 작업 줄 (prepare / solve / answer)
  posts     투표글 (사건 하나에 하나, 올릴 때의 결과 스냅샷)
  votes     투표 (글 하나에 회원 한 표)
  reports   신고

API 서버와 작업자가 같은 파일을 연다. 요청마다 연결을 새로 열어서 스레드·프로세스가 섞여도 안전하게 함.
"""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

CASES_DIR = os.environ.get("MTM_CASES_DIR", "data/cases")   # 사건 폴더들 (git에 안 올라감)
DB_PATH = os.environ.get("MTM_DB", os.path.join(CASES_DIR, "server.db"))
KEEP_UNSAVED_SEC = float(os.environ.get("MTM_KEEP_DAYS", "7")) * 86400   # 보관함에 저장 안 한 사건 보관 기간

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,       -- kakao / google / dev
  provider_id TEXT NOT NULL,    -- 카카오 회원번호, 구글 sub
  nickname TEXT,                -- 첫 로그인 뒤 정함 (없으면 가입 화면)
  terms_at REAL,                -- 필수 약관 동의 시각 (없으면 가입 안 끝남)
  train_consent_at REAL,        -- 학습 데이터 이용 동의 시각 (선택, 철회하면 NULL)
  created_at REAL NOT NULL,
  UNIQUE (provider, provider_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,          -- refresh 토큰의 jti
  user_id TEXT NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY,
  owner TEXT,                   -- 회원 id
  source TEXT NOT NULL,         -- cctv / blackbox
  name TEXT,                    -- 올린 파일 이름 (화면 표시용)
  status TEXT NOT NULL,         -- preparing / waiting_scene / analyzing / needs_answers / done / no_collision / unsupported / failed
  stage TEXT,                   -- 진행 중인 단계 (preparing일 때)
  progress INTEGER,             -- 탐지 진행률 0~100
  prepared INTEGER DEFAULT 0,   -- 탐지까지 끝남
  has_scene INTEGER DEFAULT 0,
  saved INTEGER DEFAULT 0,      -- 내 보관함에 저장 (안 하면 delete_at에 지움)
  delete_at REAL,
  error TEXT,                   -- 마지막 작업의 오류 {"error", "message"} (JSON)
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL,
  kind TEXT NOT NULL,           -- prepare / solve / answer
  status TEXT NOT NULL,         -- queued / running / done / failed / skipped
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, id);
CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL UNIQUE, -- 사건 하나에 글 하나
  author TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  visibility TEXT NOT NULL,     -- frames (장면 그림만) / video (흐림 처리 영상, 아직 없음)
  snapshot TEXT NOT NULL,       -- 올릴 때의 사고 설명·AI 결과 (JSON)
  status TEXT NOT NULL,         -- open / hidden (신고 누적)
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_new ON posts(status, created_at);
CREATE TABLE IF NOT EXISTS votes (
  post_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  a_ratio INTEGER NOT NULL,     -- 당사자 A의 과실 0~100 (10 단위)
  created_at REAL NOT NULL,
  PRIMARY KEY (post_id, user_id)
);
CREATE TABLE IF NOT EXISTS reports (
  post_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  reason TEXT,
  created_at REAL NOT NULL,
  PRIMARY KEY (post_id, user_id)
);
"""
# 예전 DB 파일에 없던 칸 (CREATE TABLE IF NOT EXISTS는 이미 있는 표에 칸을 더하지 않아서)
ADDED_COLUMNS = {"cases": [("progress", "INTEGER"), ("saved", "INTEGER DEFAULT 0"), ("delete_at", "REAL")]}


@contextmanager
def connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        for table, cols in ADDED_COLUMNS.items():
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for name, kind in cols:
                if name not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        yield con
        con.commit()
    finally:
        con.close()


def new_id():
    return uuid.uuid4().hex   # 추측할 수 없는 id (목록 API가 없는 사건은 id를 아는 사람만 봄)


def row(sql, *args):
    with connect() as con:
        r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def rows(sql, *args):
    with connect() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def run(sql, *args):
    with connect() as con:
        return con.execute(sql, args).rowcount


# ---------------------------------------------------------------- 사건

def case_dir(case_id):
    return os.path.join(CASES_DIR, case_id)


def new_case(source, name, owner=None):
    cid, now = new_id(), time.time()
    run("INSERT INTO cases (id, owner, source, name, status, delete_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", cid, owner, source, name, "preparing", now + KEEP_UNSAVED_SEC, now, now)
    os.makedirs(case_dir(cid), exist_ok=True)
    return cid


def get_case(case_id):
    return row("SELECT * FROM cases WHERE id = ?", case_id)


def update_case(case_id, **fields):
    if "error" in fields and fields["error"] is not None:
        fields["error"] = json.dumps(fields["error"], ensure_ascii=False)
    fields["updated_at"] = time.time()
    keys = ", ".join(f"{k} = ?" for k in fields)
    run(f"UPDATE cases SET {keys} WHERE id = ?", *fields.values(), case_id)


def delete_case(case_id):
    """사건과 그 사건의 작업·투표글·투표·신고 (분석 기록을 지우면 투표글도 지워짐, app_flow.md 4절)"""
    with connect() as con:
        for (pid,) in con.execute("SELECT id FROM posts WHERE case_id = ?", (case_id,)).fetchall():
            con.execute("DELETE FROM votes WHERE post_id = ?", (pid,))
            con.execute("DELETE FROM reports WHERE post_id = ?", (pid,))
        con.execute("DELETE FROM posts WHERE case_id = ?", (case_id,))
        con.execute("DELETE FROM jobs WHERE case_id = ?", (case_id,))
        con.execute("DELETE FROM cases WHERE id = ?", (case_id,))


def expired_cases(now=None):
    """보관 기간이 지난, 보관함에 저장 안 한 사건 id"""
    return [r["id"] for r in rows("SELECT id FROM cases WHERE saved = 0 AND delete_at IS NOT NULL AND delete_at < ?",
                                  now or time.time())]


# ---------------------------------------------------------------- 작업 줄

def add_job(case_id, kind):
    run("INSERT INTO jobs (case_id, kind, status, created_at) VALUES (?, ?, 'queued', ?)", case_id, kind, time.time())


def take_job():
    """가장 오래된 작업 하나를 running으로 바꿔 가져감. 그 사건에 이미 도는 작업이 있으면 건너뜀
    (한 사건 폴더를 동시에 고치지 않게). 답 작업이 여러 개 쌓였으면 마지막 것만 남기고 skipped"""
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        busy = {r[0] for r in con.execute("SELECT case_id FROM jobs WHERE status = 'running'")}
        for job in con.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id").fetchall():
            if job["case_id"] in busy:
                continue
            if job["kind"] in ("solve", "answer"):
                # 같은 사건의 판정 작업은 마지막 것 하나만 돌림 (답은 매번 전부 보내므로 마지막이 최신)
                last = con.execute("SELECT max(id) FROM jobs WHERE case_id = ? AND status = 'queued' "
                                   "AND kind IN ('solve', 'answer')", (job["case_id"],)).fetchone()[0]
                con.execute("UPDATE jobs SET status = 'skipped' WHERE case_id = ? AND status = 'queued' "
                            "AND kind IN ('solve', 'answer') AND id < ?", (job["case_id"], last))
                if job["id"] != last:
                    job = con.execute("SELECT * FROM jobs WHERE id = ?", (last,)).fetchone()
            con.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job["id"],))
            return dict(job)
    return None


def requeue_running():
    """작업자를 다시 켤 때: running으로 남은 작업(작업자가 도중에 꺼짐)을 queued로 되돌림. 작업자는 하나라고 가정"""
    run("UPDATE jobs SET status = 'queued' WHERE status = 'running'")


def finish_job(job_id, status="done"):
    run("UPDATE jobs SET status = ? WHERE id = ?", status, job_id)


def running(case_id):
    """그 사건의 작업이 지금 작업자에서 돌고 있는지 (기다리는 작업은 사건과 같이 지워도 됨)"""
    return row("SELECT count(*) AS n FROM jobs WHERE case_id = ? AND status = 'running'", case_id)["n"] > 0


# ---------------------------------------------------------------- 회원

def user_by_provider(provider, provider_id):
    return row("SELECT * FROM users WHERE provider = ? AND provider_id = ?", provider, str(provider_id))


def get_user(user_id):
    return row("SELECT * FROM users WHERE id = ?", user_id)


def new_user(provider, provider_id):
    uid = new_id()
    run("INSERT INTO users (id, provider, provider_id, created_at) VALUES (?, ?, ?, ?)",
        uid, provider, str(provider_id), time.time())
    return uid


def update_user(user_id, **fields):
    keys = ", ".join(f"{k} = ?" for k in fields)
    run(f"UPDATE users SET {keys} WHERE id = ?", *fields.values(), user_id)


def delete_user(user_id):
    """회원과 세션·투표·신고. 사건(영상)과 글은 부르는 쪽이 폴더와 함께 지움"""
    with connect() as con:
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        con.execute("DELETE FROM votes WHERE user_id = ?", (user_id,))
        con.execute("DELETE FROM reports WHERE user_id = ?", (user_id,))
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))
