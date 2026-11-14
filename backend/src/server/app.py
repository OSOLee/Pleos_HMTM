"""앱 API (FastAPI). 주소와 응답 모양은 docs/backend.md 3절, 분석 결과(app.json)는 docs/app_io.md,
로그인·보관함·투표 흐름은 docs/app_flow.md

  cd ~/MTM && .venv/bin/uvicorn src.server.app:app --host 0.0.0.0 --port 8000   # API 서버
  cd ~/MTM && .venv/bin/python -m src.server.worker                           # 작업자 (따로 띄움)

무거운 일(탐지·판정)은 작업 줄에 넣고 작업자가 한다. 이 서버는 요청을 받고, 파일을 저장하고, 상태를 돌려주기만 한다.
모서리 검사(set_scene)만 여기서 바로 한다 (1초 안쪽이고, 잘못 찍었으면 바로 422로 알려 주려고).
로그인(auth.py)은 /api/auth/*, /api/token/* 말고 모든 주소에 필요하다: Authorization: Bearer <access>.
오류 응답은 {"error": 코드, "message": 사용자에게 보여 줄 한국어}.
"""
import json
import os
import time
from datetime import datetime, timezone

import cv2
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.app import pipeline
from src.app.pipeline import InputError
from src.server import auth, db, evidence, posts, worker
from src.server.auth import AuthError

MAX_UPLOAD_MB = int(os.environ.get("MTM_MAX_UPLOAD_MB", "200"))   # docs/backend.md 7절

app = FastAPI(title="MTM 과실비율 API", version="0.2")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("MTM_CORS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


@app.exception_handler(ApiError)
@app.exception_handler(AuthError)
def api_error(_req: Request, e):
    return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)


@app.exception_handler(InputError)
def input_error(_req: Request, e: InputError):
    return JSONResponse({"error": e.code, "message": e.message}, status_code=422)


# Authorization: Bearer 헤더. 보안 방식으로 등록해 두면 /docs 오른쪽 위에 Authorize 버튼이 생김.
# auto_error=False: 헤더가 없을 때 FastAPI 기본 오류 대신 우리 오류 모양(login_required)으로 답하려고
bearer = HTTPBearer(auto_error=False)


def header_of(cred: HTTPAuthorizationCredentials | None):
    return f"Bearer {cred.credentials}" if cred else None


def me(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    """가입(닉네임·약관)까지 끝난 회원"""
    return auth.user_of(header_of(cred))


def me_any(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    """로그인만 한 회원 (가입 화면에서 씀)"""
    return auth.user_of(header_of(cred), signed_up=False)


@app.get("/")
def root():
    """서버가 살아 있는지 (주소만 열었을 때 404 대신). API 목록은 /docs"""
    return {"service": "MTM 과실비율 API", "docs": "/docs"}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None


# ---------------------------------------------------------------- 로그인·회원

class LoginIn(BaseModel):
    token: str


class RefreshIn(BaseModel):
    refresh: str


class MeIn(BaseModel):
    nickname: str | None = None
    agree_terms: bool | None = None     # 필수 약관 (서비스 이용약관, 개인정보 처리방침)
    train_consent: bool | None = None   # 선택: 학습 데이터 이용 (app_flow.md 6절)


@app.post("/api/auth/{provider}")
def login(provider: str, body: LoginIn):
    """앱의 카카오(access token)·구글(ID token) 로그인 결과를 보내면 우리 토큰을 줌.
    user.needs_signup이면 닉네임·약관 화면(PUT /api/me)으로"""
    return auth.login(provider, body.token)


@app.post("/api/token/refresh")
def refresh(body: RefreshIn):
    return auth.refresh(body.refresh)


@app.post("/api/token/logout", status_code=204)
def logout(body: RefreshIn):
    auth.logout(body.refresh)
    return Response(status_code=204)


@app.get("/api/me")
def get_me(user=Depends(me_any)):
    return auth.public_user(user)


@app.put("/api/me")
def put_me(body: MeIn, user=Depends(me_any)):
    """가입(닉네임 + 약관 동의)과 정보 고치기. 학습 동의는 언제든 켜고 끔"""
    fields = {}
    if body.nickname is not None:
        nick = body.nickname.strip()
        if not 2 <= len(nick) <= 12:
            raise ApiError(422, "nickname_length", "닉네임은 2~12자로 해 주세요")
        if db.row("SELECT id FROM users WHERE nickname = ? AND id != ?", nick, user["id"]):
            raise ApiError(409, "nickname_taken", "이미 쓰는 닉네임이에요")
        fields["nickname"] = nick
    if body.agree_terms:
        fields["terms_at"] = user["terms_at"] or time.time()
    if body.train_consent is not None:
        # 철회하면 동의 시각을 지움. 학습용 사본(흐림 처리)은 아직 만들지 않아서 지울 것도 없음 (app_flow.md 10절 5단계)
        fields["train_consent_at"] = (user["train_consent_at"] or time.time()) if body.train_consent else None
    if fields:
        db.update_user(user["id"], **fields)
    return auth.public_user(db.get_user(user["id"]))


@app.delete("/api/me", status_code=204)
def delete_me(user=Depends(me_any)):
    """탈퇴: 내 사건(영상·결과)과 투표글, 투표·신고, 로그인 기록을 모두 지움"""
    for c in db.rows("SELECT id FROM cases WHERE owner = ?", user["id"]):
        worker.remove_case(c["id"])
    db.delete_user(user["id"])
    return Response(status_code=204)


# ---------------------------------------------------------------- 사건 (분석)

def own_case(case_id, user):
    """내 사건. 남의 사건이나 없는 사건은 똑같이 404 (있는지도 알려 주지 않음)"""
    case = db.get_case(case_id)
    if case is None or case["owner"] != user["id"]:
        raise ApiError(404, "case_not_found", "사건을 찾지 못했어요. 지워졌거나 주소가 틀렸어요.")
    return case


def file_url(case_id, rel):
    return f"/api/cases/{case_id}/files/{rel}" if rel else None


def with_urls(obj, case_id):
    """app.json 안의 그림 경로(사건 폴더 기준, 예: frames/f00063.jpg)를 이 서버의 파일 주소로 바꿈"""
    if isinstance(obj, dict):
        return {k: (file_url(case_id, v) if k == "image" and isinstance(v, str) else with_urls(v, case_id))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [with_urls(v, case_id) for v in obj]
    return obj


def case_view(case, full=True):
    """사건 화면. full이 아니면 결과(app.json)를 빼고 목록용으로"""
    d = db.case_dir(case["id"])
    app_path = os.path.join(d, "app.json")
    app = pipeline.load(app_path) if os.path.exists(app_path) else None
    result = app if full else None
    post = db.row("SELECT id FROM posts WHERE case_id = ?", case["id"])
    v = (app or {}).get("verdict") or {}
    return {
        "id": case["id"],
        "name": case["name"],
        "status": case["status"],
        "stage": case["stage"],
        "progress": case["progress"],   # 탐지 진행률 0~100 (준비 중일 때 "분석 중 40%")
        "error": json.loads(case["error"]) if case["error"] else None,   # 마지막 작업의 입력 오류
        "saved": bool(case["saved"]),
        "delete_at": iso(case["delete_at"]) if not case["saved"] else None,   # 저장 안 하면 이때 지워짐
        "post_id": post["id"] if post else None,
        "background": file_url(case["id"], "background.jpg") if os.path.exists(os.path.join(d, "background.jpg")) else None,
        "scene_image": file_url(case["id"], "scene.jpg") if os.path.exists(os.path.join(d, "scene.jpg")) else None,
        # 다시 판정하는 중(analyzing)에도 직전 결과를 같이 줌. 앱은 status를 보고 "갱신 중"으로 보여 주면 됨
        "result": with_urls(result, case["id"]) if result else None,
        # 목록(기록) 화면용 요약. 판정이 아직 없으면 null
        # track_order: 당사자 순서 (근거 화면의 파랑·주황 순서와 같음). fault_by_track은 판정 모듈이 정한 순서라
        # 그대로 쓰면 기록 화면에서 비율이 뒤집혀 보였음 (결과 30:70, 기록 70:30)
        "summary": {"rule_id": v.get("rule_id"), "title": v.get("title"), "fault_by_track": v.get("fault_by_track"),
                    "provisional": v.get("provisional"),
                    "status": v.get("status"),   # ok, no_rule 등. 기록 화면이 비율 없는 이유를 보여 줄 때 씀
                    "track_order": [t for t in (((app or {}).get("collision") or {}).get(k) for k in ("a", "b")) if t]}
        if v else None,
        "created_at": iso(case["created_at"]),
    }


@app.post("/api/cases", status_code=201)
def create_case(video: UploadFile = File(...), source: str = Form("cctv"), user=Depends(me)):
    """영상 올리기. 저장하고 바로 준비 작업(탐지)을 줄에 넣음"""
    if source not in ("cctv", "blackbox"):
        raise ApiError(422, "source_invalid", "영상 종류는 cctv 또는 blackbox여야 해요")
    cid = db.new_case(source, os.path.splitext(os.path.basename(video.filename or "video"))[0], user["id"])
    path = worker.video_path(cid)
    size = 0
    with open(path, "wb") as f:
        while chunk := video.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                f.close()
                worker.remove_case(cid)
                raise ApiError(413, "video_too_large", f"영상은 {MAX_UPLOAD_MB}MB까지 올릴 수 있어요")
            f.write(chunk)
    if source == "blackbox":   # 분석하지 않고 바로 안내 (prepare가 app.json에 unsupported를 남김)
        pipeline.prepare(db.case_dir(cid), path, source, db.get_case(cid)["name"])
        db.update_case(cid, status="unsupported")
    else:
        try:
            pipeline.check_video(path)
        except InputError:
            worker.remove_case(cid)
            raise
        db.add_job(cid, "prepare")
    return case_view(db.get_case(cid))


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, user=Depends(me)):
    """사건 상태. 앱이 몇 초마다 물어봄"""
    return case_view(own_case(case_id, user))


@app.get("/api/cases/{case_id}/background.jpg")
def background(case_id: str, user=Depends(me)):
    """모서리 찍기용 배경 그림 (지나가는 차를 지운 그림)"""
    own_case(case_id, user)
    p = os.path.join(db.case_dir(case_id), "background.jpg")
    if not os.path.exists(p):
        raise ApiError(409, "not_ready", "아직 그림을 만드는 중이에요. 잠시 뒤 다시 시도해 주세요.")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/cases/{case_id}/frames/{n}.jpg")
def frame(case_id: str, n: int, user=Depends(me)):
    """영상의 n번째 장면 (모서리 찍기 슬라이더, 당사자 직접 표시). 보정 영상이 있으면 보정된 장면"""
    own_case(case_id, user)
    d = db.case_dir(case_id)
    cap = cv2.VideoCapture(pipeline.analysis_video(d, worker.video_path(case_id)))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not 0 <= n < max(total, 1):
        cap.release()
        raise ApiError(422, "frame_range", f"장면 번호는 0~{total - 1} 사이여야 해요")
    cap.set(cv2.CAP_PROP_POS_FRAMES, n)
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise ApiError(422, "frame_unreadable", "그 장면을 읽지 못했어요")
    return Response(cv2.imencode(".jpg", img)[1].tobytes(), media_type="image/jpeg")


class SceneIn(BaseModel):
    corners: list
    closed: str | None = None
    frame_ref: int = 0
    place: str = "intersection"


@app.put("/api/cases/{case_id}/scene")
def put_scene(case_id: str, body: SceneIn, user=Depends(me)):
    """장소 종류와 교차로 네 모서리. 바로 검사하고 장면 그림을 만듦. 탐지가 끝났으면 판정 작업을 줄에 넣음.
    다시 보내면(모서리 다시 찍기) 새 모서리로 다시 판정"""
    case = own_case(case_id, user)
    if case["status"] in ("unsupported", "failed"):
        raise ApiError(409, "case_closed", "이 사건은 분석할 수 없어요. 영상을 다시 올려 주세요.")
    pipeline.set_scene(db.case_dir(case_id), worker.video_path(case_id), body.corners, body.closed,
                       body.frame_ref, body.place)
    db.update_case(case_id, has_scene=1, error=None)
    if case["prepared"]:
        db.add_job(case_id, "solve")
        db.update_case(case_id, status="analyzing")
    return case_view(db.get_case(case_id))


@app.put("/api/cases/{case_id}/answers", status_code=202)
def put_answers(case_id: str, answers: dict, user=Depends(me)):
    """지금까지의 답 전부 (docs/app_io.md 2.2·2.3). 저장하고 다시 판정하는 작업을 줄에 넣음. 결과는 GET으로"""
    case = own_case(case_id, user)
    if not (case["prepared"] and case["has_scene"]) or case["status"] in ("unsupported", "failed"):
        raise ApiError(409, "not_ready", "분석이 끝난 뒤에 답을 보낼 수 있어요.")
    pipeline.check_answers(answers)
    pipeline.save(answers, os.path.join(db.case_dir(case_id), "answers.json"))
    db.add_job(case_id, "answer")
    db.update_case(case_id, status="analyzing", error=None)
    return case_view(db.get_case(case_id))


class SaveIn(BaseModel):
    saved: bool


@app.put("/api/cases/{case_id}/save")
def save_case(case_id: str, body: SaveIn, user=Depends(me)):
    """내 보관함에 저장 / 저장 취소. 저장하면 자동 삭제되지 않음. 취소하면 그때부터 보관 기간(7일) 뒤 지워짐"""
    own_case(case_id, user)
    if not body.saved and db.row("SELECT id FROM posts WHERE case_id = ?", case_id):
        raise ApiError(409, "has_post", "투표에 올린 사건이에요. 투표글을 먼저 지워 주세요.")
    db.update_case(case_id, saved=int(body.saved),
                   delete_at=None if body.saved else time.time() + db.KEEP_UNSAVED_SEC)
    return case_view(db.get_case(case_id), full=False)


@app.get("/api/me/cases")
def my_cases(user=Depends(me)):
    """내 분석 기록 (최근 것부터). 저장 안 한 것은 delete_at에 지워짐"""
    return [case_view(c, full=False) for c in
            db.rows("SELECT * FROM cases WHERE owner = ? ORDER BY created_at DESC", user["id"])]


@app.get("/api/cases/{case_id}/evidence")
def case_evidence(case_id: str, user=Depends(me)):
    """근거 화면: 두 당사자 궤적 박스(화면 비율, 초 단위)와 사건 기록, 영상 크기. 판정 전이면 409"""
    own_case(case_id, user)
    d = db.case_dir(case_id)
    cap = cv2.VideoCapture(pipeline.analysis_video(d, worker.video_path(case_id)))
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    ev = evidence.build(d, size)
    if ev is None:
        raise ApiError(409, "not_ready", "아직 분석이 끝나지 않았어요.")
    return ev


@app.get("/api/cases/{case_id}/files/{path:path}")
def case_file(case_id: str, path: str, user=Depends(me)):
    """질문 그림 등 사건 폴더의 파일. 폴더 밖 경로(../)와 원본 영상은 안 내줌"""
    own_case(case_id, user)
    root = os.path.realpath(db.case_dir(case_id))
    p = os.path.realpath(os.path.join(root, path))
    if not p.startswith(root + os.sep) or not os.path.isfile(p) or os.path.basename(p) == worker.VIDEO:
        raise ApiError(404, "file_not_found", "파일을 찾지 못했어요")
    return FileResponse(p)


@app.delete("/api/cases/{case_id}", status_code=204)
def delete_case(case_id: str, user=Depends(me)):
    """사건과 영상·결과를 지움. 투표에 올렸으면 그 글도 같이 지워짐 (앱이 먼저 알림)"""
    own_case(case_id, user)
    worker.remove_case(case_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- 투표

class PostIn(BaseModel):
    case_id: str
    title: str
    body: str | None = None
    visibility: str = "frames"


class VoteIn(BaseModel):
    a_ratio: int


class ReportIn(BaseModel):
    reason: str | None = None


def open_post(post_id, user):
    """보이는 글. 신고로 숨겨진 글은 글쓴이만 봄"""
    post = db.row("SELECT * FROM posts WHERE id = ?", post_id)
    if post is None or (post["status"] != "open" and post["author"] != user["id"]):
        raise ApiError(404, "post_not_found", "글을 찾지 못했어요. 지워졌거나 숨겨진 글이에요.")
    return post


@app.post("/api/posts", status_code=201)
def create_post(body: PostIn, user=Depends(me)):
    """투표글 쓰기. 보관함에 저장한, 분석이 끝난(done) 내 사건만. 사건 하나에 글 하나"""
    case = own_case(body.case_id, user)
    if case["status"] != "done":
        raise ApiError(409, "case_not_done", "질문에 다 답해서 결과가 나온 사건만 올릴 수 있어요.")
    if not case["saved"]:
        raise ApiError(409, "case_not_saved", "보관함에 저장한 사건만 올릴 수 있어요.")
    if db.row("SELECT id FROM posts WHERE case_id = ?", case["id"]):
        raise ApiError(409, "post_exists", "이 사고는 이미 투표에 올렸어요.")
    if body.visibility != "frames":
        raise ApiError(422, "visibility_unsupported", "지금은 장면 그림만 올릴 수 있어요 (영상 공개는 준비 중).")
    title = body.title.strip()
    if not 1 <= len(title) <= 50:
        raise ApiError(422, "title_length", "제목은 1~50자로 해 주세요")
    pid = db.new_id()
    snap = posts.snapshot(case["id"], pid)
    db.run("INSERT INTO posts (id, case_id, author, title, body, visibility, snapshot, status, created_at) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)", pid, case["id"], user["id"], title, body.body,
           body.visibility, json.dumps(snap, ensure_ascii=False), time.time())
    return posts.view(db.row("SELECT * FROM posts WHERE id = ?", pid), user["id"])


@app.get("/api/posts")
def list_posts(before: float | None = None, limit: int = 20, user=Depends(me)):
    """투표 목록 (최근 것부터). 다음 쪽은 마지막 글의 created_at을 before로"""
    limit = max(1, min(limit, 50))
    rs = db.rows("SELECT * FROM posts WHERE status = 'open' AND created_at < ? ORDER BY created_at DESC LIMIT ?",
                 before or time.time() + 1, limit)
    return [posts.summary(p) for p in rs]


@app.get("/api/me/posts")
def my_posts(user=Depends(me)):
    return [posts.summary(p) | {"status": p["status"]} for p in
            db.rows("SELECT * FROM posts WHERE author = ? ORDER BY created_at DESC", user["id"])]


@app.get("/api/posts/{post_id}")
def get_post(post_id: str, user=Depends(me)):
    """글 보기. AI 결과(ai)와 집계(votes)는 투표한 뒤에만 들어감"""
    return posts.view(open_post(post_id, user), user["id"])


@app.put("/api/posts/{post_id}/vote")
def vote(post_id: str, body: VoteIn, user=Depends(me)):
    """투표 (A의 과실 %, 10 단위). 다시 보내면 바꿈. 글쓴이는 못 함. 응답에 AI 결과·집계가 들어감"""
    post = open_post(post_id, user)
    if post["author"] == user["id"]:
        raise ApiError(403, "own_post", "내 글에는 투표할 수 없어요.")
    if body.a_ratio % posts.VOTE_STEP or not 0 <= body.a_ratio <= 100:
        raise ApiError(422, "ratio_invalid", "비율은 0~100 사이 10 단위로 골라 주세요")
    db.run("INSERT INTO votes (post_id, user_id, a_ratio, created_at) VALUES (?, ?, ?, ?) "
           "ON CONFLICT (post_id, user_id) DO UPDATE SET a_ratio = excluded.a_ratio, created_at = excluded.created_at",
           post_id, user["id"], body.a_ratio, time.time())
    return posts.view(post, user["id"])


@app.post("/api/posts/{post_id}/report", status_code=204)
def report(post_id: str, body: ReportIn, user=Depends(me)):
    """신고 (한 사람 한 번). HIDE_REPORTS번 쌓이면 숨김 (관리자 확인 전까지)"""
    post = open_post(post_id, user)
    if post["author"] == user["id"]:
        raise ApiError(403, "own_post", "내 글은 신고할 수 없어요.")
    db.run("INSERT OR IGNORE INTO reports (post_id, user_id, reason, created_at) VALUES (?, ?, ?, ?)",
           post_id, user["id"], (body.reason or "")[:200], time.time())
    if db.row("SELECT count(*) AS n FROM reports WHERE post_id = ?", post_id)["n"] >= posts.HIDE_REPORTS:
        db.run("UPDATE posts SET status = 'hidden' WHERE id = ?", post_id)
    return Response(status_code=204)


@app.delete("/api/posts/{post_id}", status_code=204)
def delete_post(post_id: str, user=Depends(me)):
    """글쓴이가 글을 지움. 분석 기록(사건)은 남음"""
    post = db.row("SELECT * FROM posts WHERE id = ?", post_id)
    if post is None or post["author"] != user["id"]:
        raise ApiError(404, "post_not_found", "글을 찾지 못했어요.")
    posts.remove(post_id)
    return Response(status_code=204)


@app.get("/api/posts/{post_id}/files/{name}")
def post_file(post_id: str, name: str, user=Depends(me)):
    """글 그림 (충돌 장면, 경로). 글 폴더 안 파일 이름만"""
    open_post(post_id, user)
    p = os.path.join(posts.post_dir(post_id), os.path.basename(name))
    if not os.path.isfile(p):
        raise ApiError(404, "file_not_found", "파일을 찾지 못했어요")
    return FileResponse(p)


from src.vehicle.api import install as install_vehicle; install_vehicle(app)   # 차량 사건 API (docs/api-spec.md)
from src.blackbox.api import install as install_bb; install_bb(app)   # 블랙박스 사건 API (docs/design-blackbox.md)
