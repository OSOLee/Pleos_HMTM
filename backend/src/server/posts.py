"""투표글 (docs/app_flow.md 4절)

글은 올리는 순간의 사고 설명과 AI 결과를 스냅샷으로 따로 저장한다. 그 뒤 보관함에서 답을 바꿔 다시 판정해도
투표 중인 글은 그대로다. 그림도 posts/<글 id>/로 복사해 둔다 (다시 판정하면 사건 폴더의 그림이 바뀌므로).
당사자는 충돌의 a(빨강)·b(파랑)를 A·B로 부르고, 투표는 A의 과실(%)로 받는다.
"""
import json
import os
import shutil

from src.app import pipeline, situation
from src.server import db

HIDE_REPORTS = int(os.environ.get("MTM_HIDE_REPORTS", "3"))   # 신고가 이만큼 쌓이면 숨김
VOTE_STEP = 10


def post_dir(post_id):
    return os.path.join(db.CASES_DIR, "posts", post_id)


def snapshot(case_id, post_id):
    """사건 폴더(app.json, facts.json, answers.json) → 글에 남길 사고 설명·AI 결과. 그림은 글 폴더로 복사"""
    d = db.case_dir(case_id)
    app = pipeline.load(os.path.join(d, "app.json"))
    facts = pipeline.load(os.path.join(d, "facts.json"))
    p = os.path.join(d, "answers.json")
    user = pipeline.load(p) if os.path.exists(p) else {}
    col = app["collision"]
    ids = {"A": str(col["a"]), "B": str(col["b"])}
    os.makedirs(post_dir(post_id), exist_ok=True)

    def copy(rel, name):
        src = os.path.join(d, rel) if rel else None
        if src and os.path.exists(src):
            shutil.copy(src, os.path.join(post_dir(post_id), name))
            return name
        return None

    parties = {}
    for k, tid in ids.items():
        parties[k] = {"cls": situation.effective(facts, user, tid, "cls"),
                      "movement": situation.effective(facts, user, tid, "movement"),
                      "entry_from": situation.effective(facts, user, tid, "entry_from"),
                      "path_image": copy(os.path.join("frames", f"path_{tid}.jpg"), f"path_{k}.jpg")}
    v = app["verdict"]
    fault = v.get("fault_by_track") or {}
    return {
        "place": user.get("road.location") or (facts.get("road") or {}).get("location"),
        "signal_present": user.get("road.signal_present"),
        "parties": parties,
        "collision_image": copy(col.get("image"), "collision.jpg"),
        "collision_t": col.get("t"),
        "ai": {"rule_id": v.get("rule_id"), "fault": {k: fault.get(tid) for k, tid in ids.items()},
               "applied_modifiers": v.get("applied_modifiers", []), "provisional": v.get("provisional"),
               # 수정요소별 근거 (영상 / 사용자 입력). 당사자 track은 A·B로 바꿈
               "modifiers": [{**m, "party": next((k for k, t in ids.items() if t == str(m.get("track"))), m.get("party")),
                              "track": None} for m in v.get("modifier_details", [])]},
    }


def stats(post_id):
    vs = [r["a_ratio"] for r in db.rows("SELECT a_ratio FROM votes WHERE post_id = ?", post_id)]
    dist = {str(k): vs.count(k) for k in range(0, 101, VOTE_STEP)}
    return {"count": len(vs), "a_avg": round(sum(vs) / len(vs), 1) if vs else None, "distribution": dist}


def file_url(post_id, name):
    return f"/api/posts/{post_id}/files/{name}" if name else None


def view(post, viewer_id):
    """글 화면. AI 결과와 투표 집계는 투표한 사람(또는 글쓴이)에게만 (먼저 보이면 AI 숫자를 따라 투표하게 돼서)"""
    snap = json.loads(post["snapshot"])
    mine = db.row("SELECT a_ratio FROM votes WHERE post_id = ? AND user_id = ?", post["id"], viewer_id)
    is_author = post["author"] == viewer_id
    author = db.get_user(post["author"])
    s = stats(post["id"])
    out = {
        "id": post["id"], "title": post["title"], "body": post["body"], "visibility": post["visibility"],
        "author": author["nickname"] if author else None, "is_author": is_author,
        "created_at": post["created_at"],
        "place": snap["place"], "signal_present": snap["signal_present"], "collision_t": snap["collision_t"],
        "collision_image": file_url(post["id"], snap["collision_image"]),
        "parties": {k: {**{x: p[x] for x in ("cls", "movement", "entry_from")},
                        "path_image": file_url(post["id"], p["path_image"])} for k, p in snap["parties"].items()},
        "my_vote": mine["a_ratio"] if mine else None,
        "vote_count": s["count"],
    }
    if mine or is_author:
        out["ai"] = snap["ai"]
        out["votes"] = s
    return out


def summary(post):
    snap = json.loads(post["snapshot"])
    author = db.get_user(post["author"])
    return {"id": post["id"], "title": post["title"], "author": author["nickname"] if author else None,
            "created_at": post["created_at"], "vote_count": stats(post["id"])["count"],
            "thumbnail": file_url(post["id"], snap["collision_image"])}


def remove(post_id):
    with db.connect() as con:
        con.execute("DELETE FROM votes WHERE post_id = ?", (post_id,))
        con.execute("DELETE FROM reports WHERE post_id = ?", (post_id,))
        con.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    shutil.rmtree(post_dir(post_id), ignore_errors=True)
