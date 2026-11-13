"""API keys for authorised machine-to-machine access (REST API, sensors)."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import secrets

from ..db import Conn
from ..db.database import utcnow

TOKEN_PREFIX = "erp"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _row(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = dict(row)
    for key in ("can_read", "can_write", "active"):
        row[key] = bool(row.get(key))
    try:
        row["entity_list"] = json.loads(row.get("entities") or "[]")
    except ValueError:
        row["entity_list"] = []
    row["ip_list"] = [x.strip() for x in (row.get("allowed_ips") or "").replace(",", "\n").splitlines() if x.strip()]
    row["min_interval_ms"] = int(row.get("min_interval_ms") or 0)
    return row


def create_key(conn: Conn, name: str, entities: list[str], can_read: bool, can_write: bool,
               allowed_ips: str, min_interval_ms: int, expires_at: dt.datetime | None,
               created_by: int | None) -> tuple[int, str]:
    """Create a key and return ``(id, token)``.  The token is shown only once."""
    prefix = secrets.token_hex(4)
    token = f"{TOKEN_PREFIX}_{prefix}_{secrets.token_urlsafe(32)}"
    key_id = conn.insert(
        "erp_api_keys",
        {
            "name": name,
            "token_prefix": prefix,
            "token_hash": _hash(token),
            "entities": json.dumps(sorted(set(entities))),
            "can_read": bool(can_read),
            "can_write": bool(can_write),
            "allowed_ips": allowed_ips or "",
            "min_interval_ms": int(min_interval_ms or 0),
            "expires_at": expires_at,
            "active": True,
            "created_at": utcnow(),
            "created_by": created_by,
        },
    )
    return key_id, token


def update_key(conn: Conn, key_id: int, values: dict) -> None:
    values = dict(values)
    if "entities" in values and isinstance(values["entities"], (list, set, tuple)):
        values["entities"] = json.dumps(sorted(set(values["entities"])))
    allowed = {"name", "entities", "can_read", "can_write", "allowed_ips", "min_interval_ms", "expires_at", "active"}
    conn.update("erp_api_keys", {k: v for k, v in values.items() if k in allowed}, {"id": key_id})


def list_keys(conn: Conn) -> list[dict]:
    return [_row(r) for r in conn.all(f"SELECT * FROM {conn.q('erp_api_keys')} ORDER BY {conn.q('name')}")]


def get_key(conn: Conn, key_id: int) -> dict | None:
    return _row(conn.one(f"SELECT * FROM {conn.q('erp_api_keys')} WHERE {conn.q('id')} = ?", [key_id]))


def delete_key(conn: Conn, key_id: int) -> None:
    conn.delete("erp_api_keys", {"id": key_id})


def authenticate(conn: Conn, token: str, ip: str) -> dict | None:
    if not token or len(token) > 200:
        return None
    row = _row(conn.one(f"SELECT * FROM {conn.q('erp_api_keys')} WHERE {conn.q('token_hash')} = ?", [_hash(token)]))
    if row is None or not row["active"]:
        return None
    expires = row.get("expires_at")
    if expires is not None and expires < utcnow():
        return None
    if row["ip_list"] and not ip_allowed(ip, row["ip_list"]):
        return None
    conn.update("erp_api_keys", {"last_used_at": utcnow()}, {"id": row["id"]})
    return row


def ip_allowed(ip: str, networks: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for net in networks:
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def key_allows(key: dict, entity: str, write: bool) -> bool:
    if write and not key["can_write"]:
        return False
    if not write and not key["can_read"]:
        return False
    return not key["entity_list"] or entity in key["entity_list"]
