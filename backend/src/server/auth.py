"""로그인 (docs/app_flow.md 2절)

안드로이드 앱의 카카오·구글 SDK가 로그인하고, 앱은 받은 토큰을 서버에 보낸다.
서버는 그 토큰을 카카오·구글에 확인해서 회원을 찾거나 만들고, 우리 토큰 두 개를 준다.

  access   API를 부를 때 Authorization: Bearer <access>. 짧게 (기본 30분)
  refresh  access가 만료되면 새로 받는 데 씀. 길게 (기본 30일). 쓸 때마다 새것으로 바뀌고 이전 것은 못 씀

설정은 .env (git에 안 올라감): MTM_JWT_SECRET(비밀), MTM_KAKAO_APP_ID(카카오 앱 ID), MTM_GOOGLE_CLIENT_IDS(쉼표로 여러 개).
MTM_DEV_LOGIN=1이면 SDK 없이 쓰는 개발용 로그인(provider "dev", 토큰 = 아무 이름)을 켠다. 서비스에서는 끔.
"""
import os
import secrets
import time

import httpx
import jwt

from src.server import db

SECRET = os.environ.get("MTM_JWT_SECRET") or secrets.token_hex(32)   # 없으면 서버를 켤 때마다 바뀜 (개발용)
ACCESS_SEC = int(os.environ.get("MTM_ACCESS_MIN", "30")) * 60
REFRESH_SEC = int(os.environ.get("MTM_REFRESH_DAYS", "30")) * 86400
KAKAO_APP_ID = os.environ.get("MTM_KAKAO_APP_ID", "")   # 카카오 디벨로퍼스의 앱 ID (숫자, 비밀 값 아님)
GOOGLE_CLIENT_IDS = [c for c in os.environ.get("MTM_GOOGLE_CLIENT_IDS", "").split(",") if c]
DEV_LOGIN = os.environ.get("MTM_DEV_LOGIN") == "1"


class AuthError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def verify_kakao(token):
    """카카오 access token → 카카오 회원번호. 카카오에 토큰 정보를 물어서, 우리 앱(KAKAO_APP_ID)에서 발급된
    토큰인지도 확인함 (안 그러면 다른 앱에서 받은 카카오 토큰으로도 로그인됨)"""
    if not KAKAO_APP_ID:
        raise AuthError(503, "provider_not_configured", "카카오 로그인이 아직 설정되지 않았어요.")
    r = httpx.get("https://kapi.kakao.com/v1/user/access_token_info",
                  headers={"Authorization": f"Bearer {token}"}, timeout=10)
    info = r.json() if r.status_code == 200 else {}
    if str(info.get("app_id")) != KAKAO_APP_ID or "id" not in info:
        raise AuthError(401, "provider_token_invalid", "카카오 로그인을 확인하지 못했어요. 다시 로그인해 주세요.")
    return str(info["id"])


def verify_google(token):
    """구글 ID token → 구글 회원 id(sub). 구글에 토큰을 확인하고, 우리 앱용으로 발급된 토큰인지(aud) 봄"""
    r = httpx.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": token}, timeout=10)
    info = r.json() if r.status_code == 200 else {}
    if (info.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
            or info.get("aud") not in GOOGLE_CLIENT_IDS or "sub" not in info):
        raise AuthError(401, "provider_token_invalid", "구글 로그인을 확인하지 못했어요. 다시 로그인해 주세요.")
    return info["sub"]


def verify_dev(token):
    if not DEV_LOGIN:
        raise AuthError(404, "provider_invalid", "지원하지 않는 로그인이에요")
    return str(token)


VERIFIERS = {"kakao": verify_kakao, "google": verify_google, "dev": verify_dev}   # 시험에서 바꿔 끼움


def issue(user_id):
    """access·refresh 토큰. refresh의 id(jti)는 sessions 표에 남겨서 로그아웃·재발급 때 지울 수 있게 함"""
    now = int(time.time())
    jti = db.new_id()
    db.run("INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)", jti, user_id, now + REFRESH_SEC)
    access = jwt.encode({"sub": user_id, "typ": "access", "iat": now, "exp": now + ACCESS_SEC}, SECRET, "HS256")
    refresh = jwt.encode({"sub": user_id, "typ": "refresh", "jti": jti, "iat": now, "exp": now + REFRESH_SEC},
                         SECRET, "HS256")
    return {"access": access, "refresh": refresh, "access_expires_in": ACCESS_SEC}


def decode(token, typ):
    try:
        claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "token_expired", "로그인이 만료됐어요. 다시 로그인해 주세요.")
    except jwt.InvalidTokenError:
        raise AuthError(401, "token_invalid", "로그인 정보가 올바르지 않아요. 다시 로그인해 주세요.")
    if claims.get("typ") != typ:
        raise AuthError(401, "token_invalid", "로그인 정보가 올바르지 않아요. 다시 로그인해 주세요.")
    return claims


def login(provider, token):
    """소셜 토큰 확인 → 회원 찾기(없으면 만들기) → 우리 토큰. 닉네임·약관 동의 전이면 needs_signup"""
    if provider not in VERIFIERS:
        raise AuthError(404, "provider_invalid", "지원하지 않는 로그인이에요")
    pid = VERIFIERS[provider](token)
    user = db.user_by_provider(provider, pid)
    uid = user["id"] if user else db.new_user(provider, pid)
    return {**issue(uid), "user": public_user(db.get_user(uid))}


def refresh(token):
    """refresh 토큰으로 새 토큰 두 개. 쓴 refresh는 지워서 다시 못 씀 (훔친 토큰을 오래 못 쓰게)"""
    claims = decode(token, "refresh")
    if db.run("DELETE FROM sessions WHERE id = ? AND expires_at > ?", claims["jti"], time.time()) == 0:
        raise AuthError(401, "token_invalid", "로그인 정보가 올바르지 않아요. 다시 로그인해 주세요.")
    if not db.get_user(claims["sub"]):
        raise AuthError(401, "token_invalid", "회원 정보를 찾지 못했어요. 다시 로그인해 주세요.")
    return issue(claims["sub"])


def logout(token):
    db.run("DELETE FROM sessions WHERE id = ?", decode(token, "refresh")["jti"])


def user_of(authorization, signed_up=True):
    """Authorization 헤더 → 회원. signed_up이면 닉네임·약관 동의까지 끝난 회원만"""
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError(401, "login_required", "로그인이 필요해요.")
    user = db.get_user(decode(authorization[7:], "access")["sub"])
    if user is None:
        raise AuthError(401, "token_invalid", "회원 정보를 찾지 못했어요. 다시 로그인해 주세요.")
    if signed_up and not (user["nickname"] and user["terms_at"]):
        raise AuthError(403, "signup_required", "닉네임과 약관 동의를 먼저 해 주세요.")
    return user


def public_user(user):
    return {"id": user["id"], "provider": user["provider"], "nickname": user["nickname"],
            "needs_signup": not (user["nickname"] and user["terms_at"]),
            "train_consent": user["train_consent_at"] is not None}
