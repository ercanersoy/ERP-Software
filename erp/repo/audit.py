"""Audit log of administrative and data changing actions."""

from __future__ import annotations

from ..db import Conn
from ..db.database import utcnow


def log(conn: Conn, user: dict | None, action: str, target: str = "", detail: str = "") -> None:
    conn.insert(
        "erp_audit",
        {
            "created_at": utcnow(),
            "user_id": user["id"] if user else None,
            "username": user["username"] if user else None,
            "action": action[:50],
            "target": (target or "")[:255],
            "detail": detail or "",
        },
    )


def list_entries(conn: Conn, limit: int = 50, offset: int = 0) -> list[dict]:
    sql = f"SELECT * FROM {conn.q('erp_audit')} ORDER BY {conn.q('id')} DESC"
    return conn.all(sql + conn.dialect.limit_sql(limit, offset))


def count_entries(conn: Conn) -> int:
    return int(conn.scalar(f"SELECT COUNT(*) FROM {conn.q('erp_audit')}"))
