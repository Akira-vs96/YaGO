"""Opaque browser sessions, CSRF validation, and role checks."""
import hashlib
import base64
import hmac
import os
import secrets
import struct
import time
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import get_db, row_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])
DB = Annotated[Session, Depends(get_db)]
SESSION_SECONDS = 60 * 60 * 24 * 14
FAILED_LOGINS = {}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def failed_login(db: Session, email: str, action: str, user_id=None):
    db.execute(text("""INSERT INTO audit_events(actor_id,action,subject_type,subject_id)
        VALUES (:user,:action,'email_hash',:email_hash)"""),
        {"user": user_id, "action": action, "email_hash": digest(email)})
    db.commit()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        _, cost, salt, expected = (encoded or "").split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(cost), r=8, p=1)
        return secrets.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def public_user(db: Session, user_id: str) -> dict:
    user = row_dict(db.execute(text("""SELECT id,email,full_name,phone,student_verified,
        (two_factor_secret IS NOT NULL) two_factor_enabled FROM users WHERE id=:id"""), {"id": user_id}).first())
    user["id"] = str(user["id"])
    user["roles"] = db.execute(text("SELECT role_code FROM user_roles WHERE user_id=:id ORDER BY role_code"), {"id": user_id}).scalars().all()
    return user


def session_user(db: Session, token: str | None):
    if not token:
        return None
    row = db.execute(text("""
        SELECT s.id session_id,s.csrf_hash,u.id user_id FROM sessions s
        JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=:token AND s.revoked_at IS NULL AND s.expires_at>now() AND u.is_active
    """), {"token": digest(token)}).first()
    return row_dict(row)


def current(request: Request, db: DB) -> dict:
    session = session_user(db, request.cookies.get("yago_session"))
    if session is None:
        raise HTTPException(401, "Войдите в аккаунт")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or csrf != request.cookies.get("yago_csrf") or digest(csrf) != session["csrf_hash"]:
            raise HTTPException(403, "Обновите страницу и повторите действие")
        origin = request.headers.get("origin")
        allowed = [v.strip() for v in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
        if origin and origin not in allowed:
            raise HTTPException(403, "Недопустимый источник запроса")
    return {**session, **public_user(db, str(session["user_id"]))}


User = Annotated[dict, Depends(current)]


def require(user: dict, *roles: str):
    if not set(roles).intersection(user["roles"]):
        raise HTTPException(403, "Недостаточно прав")


def set_cookies(response: Response, token: str, csrf: str):
    secure = os.getenv("COOKIE_SECURE", "0") == "1"
    response.set_cookie("yago_session", token, max_age=SESSION_SECONDS, httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie("yago_csrf", csrf, max_age=SESSION_SECONDS, httponly=False, secure=secure, samesite="lax", path="/")


def verify_origin(request: Request):
    origin = request.headers.get("origin")
    allowed = [v.strip() for v in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
    if origin and origin not in allowed:
        raise HTTPException(403, "Недопустимый источник запроса")


def totp(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest_value = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest_value[-1] & 15
    value = struct.unpack(">I", digest_value[offset:offset + 4])[0] & 0x7fffffff
    return f"{value % 1000000:06d}"


def valid_totp(secret: str, code: str) -> bool:
    if not re.fullmatch(r"\d{6}", code):
        return False
    step = int(time.time() // 30)
    return any(secrets.compare_digest(totp(secret, step + delta), code) for delta in (-1, 0, 1))


def issue_session(db: Session, response: Response, user_id: str):
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
    db.execute(text("""INSERT INTO sessions(user_id,token_hash,csrf_hash,expires_at)
        VALUES (:user,:token,:csrf,:expires)"""), {"user": user_id, "token": digest(token), "csrf": digest(csrf), "expires": datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)})
    db.commit()
    set_cookies(response, token, csrf)


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Укажите корректную почту")
        return value


class Registration(Credentials):
    full_name: str = Field(min_length=2, max_length=120)


@router.post("/register", status_code=201)
def register(body: Registration, response: Response, request: Request, db: DB):
    verify_origin(request)
    email = str(body.email).lower()
    if db.execute(text("SELECT 1 FROM users WHERE lower(email)=:email"), {"email": email}).first():
        raise HTTPException(409, "Этот адрес уже зарегистрирован")
    user_id = str(db.execute(text("INSERT INTO users(email,full_name,password_hash) VALUES (:email,:name,:hash) RETURNING id"),
        {"email": email, "name": body.full_name.strip(), "hash": password_hash(body.password)}).scalar_one())
    db.execute(text("INSERT INTO user_roles(user_id,role_code) VALUES (:user,'client')"), {"user": user_id})
    db.execute(text("INSERT INTO audit_events(actor_id,action) VALUES (:user,'register')"), {"user": user_id})
    issue_session(db, response, user_id)
    return public_user(db, user_id)


@router.post("/login")
def login(body: Credentials, response: Response, request: Request, db: DB):
    verify_origin(request)
    email = str(body.email).lower()
    now = time.monotonic()
    attempts = [t for t in FAILED_LOGINS.get(email, []) if now - t < 300]
    if len(attempts) >= 5:
        failed_login(db, email, "login_rate_limited")
        raise HTTPException(429, "Слишком много попыток. Повторите через 5 минут")
    user = db.execute(text("SELECT id,password_hash,two_factor_secret FROM users WHERE lower(email)=:email AND is_active"), {"email": email}).first()
    if not user or not verify_password(body.password, user.password_hash):
        FAILED_LOGINS[email] = attempts + [now]
        failed_login(db, email, "login_failed", user.id if user else None)
        raise HTTPException(401, "Неверная почта или пароль")
    FAILED_LOGINS.pop(email, None)
    if user.two_factor_secret:
        token = secrets.token_urlsafe(40)
        db.execute(text("""INSERT INTO login_challenges(token_hash,user_id,expires_at)
            VALUES (:hash,:user,:expires)"""), {"hash": digest(token), "user": user.id,
            "expires": datetime.now(timezone.utc) + timedelta(minutes=5)})
        db.commit()
        response.set_cookie("yago_2fa", token, max_age=300, httponly=True,
                            secure=os.getenv("COOKIE_SECURE", "0") == "1", samesite="lax", path="/api/auth")
        return {"requires2fa": True}
    issue_session(db, response, str(user.id))
    db.execute(text("INSERT INTO audit_events(actor_id,action) VALUES (:user,'login')"), {"user": user.id})
    db.commit()
    return public_user(db, str(user.id))


@router.get("/me")
def me(user: User):
    return {k: user[k] for k in ("id", "email", "full_name", "phone", "roles",
                                 "student_verified", "two_factor_enabled")}


class SecondFactor(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


@router.post("/verify-2fa")
def verify_2fa(body: SecondFactor, response: Response, request: Request, db: DB):
    verify_origin(request)
    token = request.cookies.get("yago_2fa")
    challenge = db.execute(text("""SELECT c.user_id,c.failed_attempts,u.two_factor_secret
        FROM login_challenges c JOIN users u ON u.id=c.user_id
        WHERE c.token_hash=:hash AND c.expires_at>now() AND c.failed_attempts<5
        AND u.is_active FOR UPDATE OF c"""), {"hash": digest(token or "")}).first()
    if not challenge:
        failed_login(db, digest(token or ""), "login_2fa_expired")
        raise HTTPException(401, "Код устарел. Войдите снова")
    if not valid_totp(challenge.two_factor_secret, body.code):
        db.execute(text("UPDATE login_challenges SET failed_attempts=failed_attempts+1 WHERE token_hash=:hash"),
                   {"hash": digest(token)})
        db.execute(text("""INSERT INTO audit_events(actor_id,action)
            VALUES (:user,'login_2fa_failed')"""), {"user": challenge.user_id})
        db.commit()
        raise HTTPException(401, "Неверный код")
    db.execute(text("DELETE FROM login_challenges WHERE token_hash=:hash"), {"hash": digest(token)})
    response.delete_cookie("yago_2fa", path="/api/auth")
    issue_session(db, response, str(challenge.user_id))
    db.execute(text("INSERT INTO audit_events(actor_id,action) VALUES (:user,'login_2fa')"),
               {"user": challenge.user_id})
    db.commit()
    return public_user(db, str(challenge.user_id))


@router.post("/2fa/setup")
def setup_2fa(user: User, db: DB):
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    db.execute(text("UPDATE users SET two_factor_pending_secret=:secret WHERE id=:id"),
               {"secret": secret, "id": user["id"]})
    db.commit()
    return {"secret": secret, "uri": f"otpauth://totp/YaGo:{quote(user['email'])}?secret={secret}&issuer=YaGo"}


@router.post("/2fa/enable")
def enable_2fa(body: SecondFactor, user: User, db: DB):
    secret = db.scalar(text("SELECT two_factor_pending_secret FROM users WHERE id=:id"), {"id": user["id"]})
    if not secret or not valid_totp(secret, body.code):
        raise HTTPException(422, "Неверный код приложения")
    db.execute(text("""UPDATE users SET two_factor_secret=two_factor_pending_secret,
        two_factor_pending_secret=NULL WHERE id=:id"""), {"id": user["id"]})
    db.execute(text("INSERT INTO audit_events(actor_id,action) VALUES (:id,'2fa_enable')"), {"id": user["id"]})
    db.commit()
    return {"ok": True}


@router.post("/2fa/disable")
def disable_2fa(body: SecondFactor, user: User, db: DB):
    secret = db.scalar(text("SELECT two_factor_secret FROM users WHERE id=:id"), {"id": user["id"]})
    if not secret or not valid_totp(secret, body.code):
        raise HTTPException(422, "Неверный код приложения")
    db.execute(text("UPDATE users SET two_factor_secret=NULL WHERE id=:id"), {"id": user["id"]})
    db.execute(text("INSERT INTO audit_events(actor_id,action) VALUES (:id,'2fa_disable')"), {"id": user["id"]})
    db.commit()
    return {"ok": True}


class StudentCode(BaseModel):
    code: str = Field(min_length=4, max_length=80)


@router.post("/student/verify")
def verify_student(body: StudentCode, user: User, db: DB):
    if os.getenv("DEMO_MODE") != "1":
        raise HTTPException(404, "Учебная проверка недоступна")
    if not secrets.compare_digest(body.code, os.getenv("DEMO_STUDENT_CODE", "YAGO-STUDENT")):
        raise HTTPException(422, "Неверный учебный код")
    db.execute(text("UPDATE users SET student_verified=true WHERE id=:id"), {"id": user["id"]})
    db.execute(text("INSERT INTO audit_events(actor_id,action) VALUES (:id,'student_verify')"), {"id": user["id"]})
    db.commit()
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, user: User, db: DB):
    db.execute(text("UPDATE sessions SET revoked_at=now() WHERE id=:id"), {"id": user["session_id"]})
    db.commit()
    response.delete_cookie("yago_session", path="/")
    response.delete_cookie("yago_csrf", path="/")
    return {"ok": True}


@router.get("/sessions")
def sessions(user: User, db: DB):
    return [{**row_dict(r), "id": str(r.id), "current": str(r.id) == str(user["session_id"])} for r in db.execute(text("""
        SELECT id,created_at,expires_at FROM sessions WHERE user_id=:user AND revoked_at IS NULL AND expires_at>now()
        ORDER BY created_at DESC
    """), {"user": user["id"]})]


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, user: User, db: DB):
    result = db.execute(text("UPDATE sessions SET revoked_at=now() WHERE id=:id AND user_id=:user AND revoked_at IS NULL"),
        {"id": session_id, "user": user["id"]})
    if not result.rowcount:
        raise HTTPException(404, "Сессия не найдена")
    db.commit()
    return {"ok": True}
