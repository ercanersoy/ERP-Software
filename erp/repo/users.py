"""Users, roles, password hashing and login sessions."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets

from ..db import Conn
from ..db.database import utcnow

ROLES = ("admin", "user", "dealer")
USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789._-@")
MIN_PASSWORD_LENGTH = 8

# scrypt cost: N=2^14, r=8, p=1 uses 16 MB of memory per hash and takes some 50 ms, the parameters recommended
# for interactive logins.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random 16 byte salt.

    The result ``scrypt$N$r$p$salt$digest`` stores the cost parameters too, so
    they can be raised later without breaking existing passwords.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Check ``password`` against a stored hash in constant time; malformed hashes never match."""
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Hash checked for unknown user names, so they take as long as wrong passwords.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def normalize_username(name: str) -> str:
    """User names are case insensitive: trimmed and lower case."""
    return (name or "").strip().lower()


def valid_username(name: str) -> bool:
    """2-100 characters from :data:`USERNAME_CHARS` (letters a-z, digits, ``. _ - @``)."""
    return 2 <= len(name) <= 100 and set(name) <= USERNAME_CHARS


def _public(row: dict | None) -> dict | None:
    """Copy of a user row with ``active`` as a real boolean (drivers return 0/1)."""
    if row is None:
        return None
    row = dict(row)
    row["active"] = bool(row.get("active"))
    return row


def get_user(conn: Conn, user_id: int) -> dict | None:
    """The user with ``user_id``, or ``None``."""
    return _public(conn.one(f"SELECT * FROM {conn.q('erp_users')} WHERE {conn.q('id')} = ?", [user_id]))


def get_user_by_name(conn: Conn, username: str) -> dict | None:
    """The user called ``username`` (case insensitive), or ``None``."""
    return _public(
        conn.one(
            f"SELECT * FROM {conn.q('erp_users')} WHERE {conn.q('username')} = ?", [normalize_username(username)]
        )
    )


def list_users(conn: Conn) -> list[dict]:
    """All users ordered by user name."""
    rows = conn.all(f"SELECT * FROM {conn.q('erp_users')} ORDER BY {conn.q('username')}")
    return [_public(r) for r in rows]


def count_users(conn: Conn) -> int:
    """Number of users (0 right after installation of an empty database)."""
    return int(conn.scalar(f"SELECT COUNT(*) FROM {conn.q('erp_users')}"))


def count_active_admins(conn: Conn) -> int:
    """Number of active administrators; at least one must always remain."""
    return int(
        conn.scalar(
            f"SELECT COUNT(*) FROM {conn.q('erp_users')} WHERE {conn.q('role')} = ? AND {conn.q('active')} = ?",
            ["admin", True],
        )
    )


def create_user(conn: Conn, username: str, password: str, role: str, full_name: str = "",
                email: str = "", language: str = "", active: bool = True) -> int:
    """Create a user and return the new id; the password is stored hashed."""
    return conn.insert(
        "erp_users",
        {
            "username": normalize_username(username),
            "password_hash": hash_password(password),
            "full_name": full_name or "",
            "email": email or "",
            "role": role,
            "language": language or "",
            "active": bool(active),
            "created_at": utcnow(),
        },
    )


def update_user(conn: Conn, user_id: int, values: dict) -> None:
    """Change profile fields; only name, e-mail, role, language and active can be set here."""
    allowed = {"full_name", "email", "role", "language", "active"}
    conn.update("erp_users", {k: v for k, v in values.items() if k in allowed}, {"id": user_id})


def set_password(conn: Conn, user_id: int, password: str) -> None:
    """Set a new password and end all sessions of the user (log out everywhere)."""
    conn.update("erp_users", {"password_hash": hash_password(password)}, {"id": user_id})
    conn.delete("erp_sessions", {"user_id": user_id})


def delete_user(conn: Conn, user_id: int) -> None:
    """Delete a user and their sessions.  Records keep the user id in created_by."""
    conn.delete("erp_sessions", {"user_id": user_id})
    conn.delete("erp_users", {"id": user_id})


def authenticate(conn: Conn, username: str, password: str) -> dict | None:
    """The user for a correct user name and password, else ``None``.

    For unknown users a dummy hash is checked anyway, so the response time
    does not reveal which user names exist.  Inactive users can not log in.
    """
    user = get_user_by_name(conn, username)
    if user is None:
        verify_password(password, _DUMMY_HASH)  # same timing for unknown users
        return None
    if not verify_password(password, user["password_hash"]) or not user["active"]:
        return None
    conn.update("erp_users", {"last_login_at": utcnow()}, {"id": user["id"]})
    return user


# ---------------------------------------------------------------- sessions
def _token_hash(token: str) -> str:
    """SHA-256 of a session token: the database never holds usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: Conn, user_id: int, hours: int, ip: str = "", user_agent: str = "") -> str:
    """Start a login session; returns the token for the session cookie.

    Only the hash of the token is stored, together with the expiry time, the
    client address and the browser (for the administrators' information).
    """
    token = secrets.token_urlsafe(32)
    now = utcnow()
    conn.insert(
        "erp_sessions",
        {
            "token_hash": _token_hash(token),
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + dt.timedelta(hours=max(1, hours)),
            "ip": (ip or "")[:64],
            "user_agent": (user_agent or "")[:255],
        },
        return_id=False,
    )
    return token


def session_user(conn: Conn, token: str) -> dict | None:
    """The active user of a valid, unexpired session token, else ``None`` (expired sessions are removed)."""
    row = conn.one(
        f"SELECT * FROM {conn.q('erp_sessions')} WHERE {conn.q('token_hash')} = ?", [_token_hash(token)]
    )
    if row is None:
        return None
    expires = row["expires_at"]
    if isinstance(expires, str):
        expires = dt.datetime.fromisoformat(expires)
    if expires is None or expires < utcnow():
        conn.delete("erp_sessions", {"token_hash": row["token_hash"]})
        return None
    user = get_user(conn, row["user_id"])
    if user is None or not user["active"]:
        return None
    return user


def delete_session(conn: Conn, token: str) -> None:
    """End one session (logout)."""
    conn.delete("erp_sessions", {"token_hash": _token_hash(token)})


def purge_sessions(conn: Conn) -> int:
    """Delete all expired sessions; returns how many were removed."""
    cur = conn.execute(f"DELETE FROM {conn.q('erp_sessions')} WHERE {conn.q('expires_at')} < ?", [utcnow()])
    n = cur.rowcount
    cur.close()
    return n
