"""차량 사건 API (docs/api-spec.md 2절)

  POST   /api/vehicle-cases                 차량 기록 올리기 (2.1)
  PUT    /api/vehicle-cases/{id}/answers    사용자 답 → 다시 계산 (2.2)
  GET    /api/vehicle-cases/{id}            마지막 결과 (2.3)
  DELETE /api/vehicle-cases/{id}            samples 포함 전부 삭제 (2.4)

src/server/app.py 맨 끝의 한 줄로 등록한다 (8.3):
  from src.vehicle.api import install as install_vehicle; install_vehicle(app)

순환 import를 피하려고 src.server.app을 import하지 않는다. 인증 의존성은 app.py의 me와 같은 동작으로 여기서 다시 만들고,
인증 오류(AuthError)는 app.py에 이미 걸린 처리기가 같은 모양으로 낸다.

탈퇴(DELETE /api/me)는 app.py의 delete_me가 vehicle_cases를 모르므로, install(app)이 그 요청을 미들웨어로 감싸
탈퇴가 끝나면(204) 그 회원의 차량 사건을 지운다 (8.5. MTM 코드는 고치지 않음).
"""
import json

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.server import auth
from src.vehicle import adapter, store
from src.vehicle.samples import VehicleError, validate

router = APIRouter(prefix="/api/vehicle-cases")
bearer = HTTPBearer(auto_error=False)


def me(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    """가입(닉네임·약관)까지 끝난 회원 (app.py의 me와 같음)"""
    return auth.user_of(f"Bearer {cred.credentials}" if cred else None)


def own_case(case_id, user):
    """내 사건 행. 없거나 남의 사건이면 404 (남의 사건이 있는지도 알리지 않음)"""
    row = store.get(case_id)
    if row is None or row["owner"] != user["id"]:
        raise VehicleError("vehicle_case_not_found", "차량 사건을 찾지 못했어요.", status=404)
    return row


def create(owner, body):
    req = dict(validate(body), server_ms=store.now_ms())   # 받은 시각: 시계 차이 경고(명세 6.1)용, 요청과 같이 저장
    record = adapter.build(req, {})
    return store.create(owner, req, {}, record)


def put_answers(case_id, user, answers):
    """저장한 요청 원본으로 규칙·질문·판정을 처음부터 다시 돌려 행을 덮어씀"""
    row = own_case(case_id, user)
    record = adapter.build(row["request"], answers)
    return store.update(case_id, answers, record)


async def json_body(request):
    try:
        return json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        raise VehicleError("request_invalid", "요청 본문이 JSON이 아니에요")


@router.post("", status_code=201)
async def create_case(request: Request, user=Depends(me)):
    """차량 기록 올리기 → 자동 답변·남은 질문·임시 판정 결과 (2.1)"""
    body = await json_body(request)
    # 규칙·판정은 CPU 작업이라 이벤트 루프를 막지 않게 스레드에서
    return await run_in_threadpool(create, user["id"], body)


@router.put("/{case_id}/answers")
async def answer_case(case_id: str, request: Request, user=Depends(me)):
    """지금까지의 답 전부 → 자동 답변 다시 계산, 사용자 답 우선, 다르면 answer_conflicts (2.2)"""
    body = await json_body(request)
    answers = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(answers, dict):
        raise VehicleError("answers_shape", "answers는 {질문 키: 값} 객체여야 해요")
    return await run_in_threadpool(put_answers, case_id, user, answers)


@router.get("/{case_id}")
def get_case(case_id: str, user=Depends(me)):
    """마지막 POST·PUT의 결과 그대로 (2.3)"""
    return own_case(case_id, user)["view"]


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: str, user=Depends(me)):
    """사건 행 하나를 지움 (요청 원본·samples·답·규칙 결과·판정 결과가 모두 그 행에 있음). 되돌릴 수 없음 (2.4)"""
    own_case(case_id, user)
    store.delete(case_id)
    return Response(status_code=204)


WITHDRAW = ("DELETE", "/api/me")   # app.py delete_me


async def delete_on_withdraw(request: Request, call_next):
    """탈퇴 요청이면: 탈퇴 전에 회원 id를 알아 두고(탈퇴 뒤에는 토큰의 회원이 없음), 탈퇴가 끝나면 차량 사건을 지움.
    탈퇴가 실패하면(401 등) 아무것도 지우지 않음"""
    if (request.method, request.url.path) != WITHDRAW:
        return await call_next(request)
    try:
        owner = auth.user_of(request.headers.get("authorization"), signed_up=False)["id"]
    except Exception:   # 인증 오류는 delete_me가 같은 이유로 낸다
        owner = None
    response = await call_next(request)
    if owner and response.status_code == 204:
        await run_in_threadpool(store.delete_owner, owner)
    return response


async def vehicle_error(request, e: VehicleError):
    return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)


def install(app):
    """라우터, 차량 사건 오류 처리기, 탈퇴 때 차량 사건 삭제 등록
    (APIRouter에는 예외 처리기·미들웨어를 달 수 없어서 여기서 함)"""
    app.include_router(router)
    app.add_exception_handler(VehicleError, vehicle_error)
    app.middleware("http")(delete_on_withdraw)
