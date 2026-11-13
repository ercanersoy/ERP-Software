"""Uploaded files (documents, images and videos).

File contents are stored on disk under the configured upload directory and
described by rows of the ``erp_files`` table.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import secrets
from pathlib import Path

from ..db import Conn
from ..db.database import utcnow
from ..fieldtypes import FIELD_TYPES, ValidationError, sniff_image, sniff_video

DOCUMENT_EXTENSIONS = {
    ext.strip() for ext in FIELD_TYPES["document"].accept.split(",")
}


def storage_path(upload_dir: str | Path, key: str) -> Path:
    if not key or not all(c in "0123456789abcdef" for c in key):
        raise ValueError("invalid storage key")
    return Path(upload_dir) / key[:2] / key


def detect(kind: str, filename: str, head: bytes, declared: str | None) -> str:
    """Validate an upload and return the MIME type to store."""
    ext = os.path.splitext(filename.lower())[1]
    match kind:
        case "image":
            mime = sniff_image(head)
            if mime is None:
                raise ValidationError("error.invalid_image")
            return mime
        case "video":
            mime = sniff_video(head)
            if mime is None:
                raise ValidationError("error.invalid_video")
            return mime
        case "document":
            if ext not in DOCUMENT_EXTENSIONS:
                raise ValidationError("error.invalid_document")
            return mimetypes.guess_type(filename)[0] or declared or "application/octet-stream"
    raise ValidationError("error.invalid_value")


def safe_name(filename: str) -> str:
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"/\\|?*')
    return (name or "file")[:255]


def save_file(conn: Conn, upload_dir: str | Path, kind: str, filename: str, body: bytes,
              declared_mime: str | None, entity: str | None, user_id: int | None) -> dict:
    filename = safe_name(filename)
    mime = detect(kind, filename, body[:64], declared_mime)
    key = secrets.token_hex(16)
    path = storage_path(upload_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, path)
    row = {
        "entity": entity,
        "original_name": filename,
        "mime_type": mime,
        "kind": kind,
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "storage_key": key,
        "created_at": utcnow(),
        "created_by": user_id,
    }
    try:
        row["id"] = conn.insert("erp_files", row)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return row


def get_file(conn: Conn, file_id: int) -> dict | None:
    return conn.one(f"SELECT * FROM {conn.q('erp_files')} WHERE {conn.q('id')} = ?", [file_id])


def get_files(conn: Conn, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    ids_list = sorted(ids)
    marks = ", ".join("?" for _ in ids_list)
    rows = conn.all(f"SELECT * FROM {conn.q('erp_files')} WHERE {conn.q('id')} IN ({marks})", ids_list)
    return {int(r["id"]): r for r in rows}


def list_files(conn: Conn) -> list[dict]:
    return conn.all(f"SELECT * FROM {conn.q('erp_files')} ORDER BY {conn.q('id')}")


def remove_from_disk(upload_dir: str | Path, rows: list[dict]) -> None:
    for row in rows:
        try:
            storage_path(upload_dir, row["storage_key"]).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def delete_orphans(conn: Conn, upload_dir: str | Path, older_than_hours: int = 24) -> int:
    """Remove uploads that were never attached to a record (e.g. abandoned forms)."""
    import datetime as dt

    from . import entities as entities_repo

    limit = utcnow() - dt.timedelta(hours=older_than_hours)
    used: set[int] = set()
    for ent in entities_repo.list_entities(conn):
        for f in ent.fields:
            if f.is_file:
                used.update(
                    int(r[f.name])
                    for r in conn.all(
                        f"SELECT {conn.q(f.name)} FROM {conn.q(ent.table)} WHERE {conn.q(f.name)} IS NOT NULL"
                    )
                )
    removed = []
    for row in list_files(conn):
        created = row["created_at"]
        if row["id"] not in used and created is not None and created < limit:
            conn.delete("erp_files", {"id": row["id"]})
            removed.append(row)
    remove_from_disk(upload_dir, removed)
    return len(removed)
