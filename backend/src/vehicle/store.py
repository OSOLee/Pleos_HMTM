"""차량 사건 저장 (docs/api-spec.md 8.6)

기존 서버 DB 파일(src.server.db.connect)을 같이 쓰고, 표 vehicle_cases는 여기서 CREATE TABLE IF NOT EXISTS로 만든다
(db.py는 고치지 않음). 사건 하나 = 행 하나. samples도 요청 원본에 넣어 두어, 지울 때 행 하나만 지우면 끝난다.

  request       정리한 요청 원본 (samples.validate 결과, samples 포함)
  answers       사용자 답 {field: value} (PUT answers에서 채움)
  rule_results  규칙 결과 전체 (facts·params 포함). 나중에 규칙을 바꿔도 예전 결과를 설명하려고 둠
  rules         쓴 규칙 이름·버전 목록 (예: ["movement_v0", "turn_signal_v0"])
  view          응답(2.5 차량 사건 객체) 그대로. GET은 이것을 돌려준다 (2.3)
"""
import json
import time
from contextlib import contextmanager

from src.server import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle_cases (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,          -- 회원 id
  status TEXT NOT NULL,         -- needs_answers / done
  request TEXT NOT NULL,        -- JSON
  answers TEXT NOT NULL,        -- JSON
  rule_results TEXT NOT NULL,   -- JSON
  rules TEXT NOT NULL,          -- JSON
  view TEXT NOT NULL,           -- JSON
  judge_version TEXT,
  created_at INTEGER NOT NULL,  -- epoch ms (6.1)
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS vehicle_cases_owner ON vehicle_cases(owner, created_at);
"""
JSON_COLS = ("request", "answers", "rule_results", "rules", "view")


@contextmanager
def connect():
    """기존 DB 파일을 열고 vehicle_cases 표가 없으면 만든다"""
    with db.connect() as con:
        con.executescript(SCHEMA)
        yield con


def now_ms():
    return int(time.time() * 1000)


def _dump(v):
    return json.dumps(v, ensure_ascii=False)


def create(owner, request, answers, record):
    """새 사건 저장. record: adapter.build 결과 {view, rule_results, rules, judge_version}.
    반환: id·시각을 넣은 view (2.5)"""
    cid, now = db.new_id(), now_ms()
    view = {"id": cid, "status": record["view"]["status"], "created_at": now, "updated_at": now, **record["view"]}
    with connect() as con:
        con.execute("INSERT INTO vehicle_cases (id, owner, status, request, answers, rule_results, rules, view, "
                    "judge_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cid, owner, view["status"], _dump(request), _dump(answers), _dump(record["rule_results"]),
                     _dump(record["rules"]), _dump(view), record.get("judge_version"), now, now))
    return view


def get(case_id):
    """행 하나 (JSON 칸은 풀어서). 없으면 None"""
    with connect() as con:
        r = con.execute("SELECT * FROM vehicle_cases WHERE id = ?", (case_id,)).fetchone()
    if r is None:
        return None
    out = dict(r)
    for k in JSON_COLS:
        out[k] = json.loads(out[k])
    return out


def update(case_id, answers, record):
    """PUT answers: 답과 다시 계산한 결과로 행을 덮어씀. id·created_at은 그대로, updated_at만 바뀜.
    반환: 새 view (2.5). 행이 없으면 None"""
    row = get(case_id)
    if row is None:
        return None
    now = max(now_ms(), row["updated_at"])
    view = {"id": case_id, "status": record["view"]["status"], "created_at": row["created_at"], "updated_at": now,
            **record["view"]}
    with connect() as con:
        con.execute("UPDATE vehicle_cases SET status = ?, answers = ?, rule_results = ?, rules = ?, view = ?, "
                    "judge_version = ?, updated_at = ? WHERE id = ?",
                    (view["status"], _dump(answers), _dump(record["rule_results"]), _dump(record["rules"]),
                     _dump(view), record.get("judge_version"), now, case_id))
    return view


def delete(case_id):
    """사건 하나를 지움. samples가 행 안에 있어 행 하나면 끝 (2.4, 되돌릴 수 없음)"""
    with connect() as con:
        con.execute("DELETE FROM vehicle_cases WHERE id = ?", (case_id,))


def delete_owner(owner):
    """회원의 차량 사건 전부 (탈퇴, 8.5). 지운 개수"""
    with connect() as con:
        return con.execute("DELETE FROM vehicle_cases WHERE owner = ?", (owner,)).rowcount
