"""Acceso opcional con contraseña única (ACCESS_PASSWORD). Sin contraseña, la app queda abierta (red local)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .. import settings_store as S
from ..config import get_env

COOKIE = "claqueta_session"
TTL = 60 * 60 * 24 * 60  # 60 días
OPEN_PATHS = ("/api/health", "/api/auth/")

router = APIRouter(prefix="/api/auth")
_attempts: dict[str, list[float]] = {}
_lock = threading.Lock()


def _secret() -> bytes:
    key = get_env().secret_key or S.get_raw("x_secret")
    if not key:
        key = secrets.token_hex(32)
        S.set_raw("x_secret", key)
    return key.encode()


def _sign(expires: int) -> str:
    pw = get_env().access_password.encode()
    mac = hmac.new(_secret() + pw, f"ok:{expires}".encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{mac}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp_s, _ = token.split(".", 1)
    if not exp_s.isdigit() or int(exp_s) < time.time():
        return False
    return hmac.compare_digest(token, _sign(int(exp_s)))


def required() -> bool:
    return bool(get_env().access_password)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if required() and path.startswith("/api/") and not path.startswith(OPEN_PATHS):
            if not valid_token(request.cookies.get(COOKIE)):
                return JSONResponse({"detail": "Acceso restringido", "code": "auth_required"}, status_code=401)
        return await call_next(request)


@router.get("/status")
def status(request: Request):
    return {"required": required(), "authenticated": (not required()) or valid_token(request.cookies.get(COOKIE))}


class LoginIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.time()
    with _lock:
        recent = [t for t in _attempts.get(ip, []) if now - t < 300]
        if len(recent) >= 8:
            raise HTTPException(429, "Demasiados intentos: espera unos minutos")
        recent.append(now)
        _attempts[ip] = recent
    pw = get_env().access_password
    if not pw or not hmac.compare_digest(body.password.encode(), pw.encode()):
        time.sleep(.6)
        raise HTTPException(401, "Contraseña incorrecta")
    with _lock:
        _attempts.pop(ip, None)
    token = _sign(int(now) + TTL)
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}
