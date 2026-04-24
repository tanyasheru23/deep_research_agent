"""
Auth — register, login, JWT tokens.
Uses SQLAlchemy session passed in from FastAPI dependency.
"""

from __future__ import annotations
import base64, hashlib, hmac, json, os, time, uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import User

SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
TOKEN_TTL  = 60 * 60 * 24 * 7  # 7 days


# ── Password ──────────────────────────────────────────────────────────────
def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}${dk.hex()}"

def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, dk_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (4 - len(s) % 4))

def make_token(payload: dict) -> str:
    header = _b64(json.dumps({"alg": "HS256"}).encode())
    body   = _b64(json.dumps(payload).encode())
    sig    = hmac.new(SECRET_KEY.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"

def decode_token(token: str) -> dict | None:
    try:
        header, body, sig = token.split(".")
        expected = hmac.new(SECRET_KEY.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(sig), expected):
            return None
        payload = json.loads(_b64d(body))
        return payload if payload.get("exp", 0) > time.time() else None
    except Exception:
        return None


# ── Exceptions ────────────────────────────────────────────────────────────
class AuthError(Exception):
    pass


# ── DB operations ─────────────────────────────────────────────────────────
async def register(session: AsyncSession, username: str, email: str, password: str) -> User:
    if len(password) < 6:
        raise AuthError("Password must be at least 6 characters.")
    if not email or "@" not in email:
        raise AuthError("A valid email is required.")

    username = username.strip().lower()
    existing = await session.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise AuthError("Username already taken.")

    user = User(
        id            = str(uuid.uuid4()),
        username      = username,
        email         = email.strip(),
        password_hash = _hash_password(password),
        created_at    = time.time(),
    )
    session.add(user)
    await session.commit()
    return user


async def login(session: AsyncSession, username: str, password: str) -> str:
    username = username.strip().lower()
    result   = await session.execute(select(User).where(User.username == username))
    user     = result.scalar_one_or_none()

    if not user or not _verify_password(password, user.password_hash):
        raise AuthError("Invalid username or password.")

    return make_token({
        "sub":      user.id,
        "username": user.username,
        "email":    user.email,
        "exp":      time.time() + TOKEN_TTL,
    })


async def update_email(session: AsyncSession, user_id: str, new_email: str) -> None:
    if not new_email or "@" not in new_email:
        raise AuthError("A valid email is required.")
    result = await session.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if user:
        user.email = new_email.strip()
        await session.commit()


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()