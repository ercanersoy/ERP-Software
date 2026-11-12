"""Records of user defined entities."""

from __future__ import annotations

from ..db import Conn
from ..db.database import utcnow
from ..fieldtypes import ValidationError
from .entities import Entity

META_COLUMNS = ("id", "created_at", "updated_at", "created_by", "updated_by", "api_key_id")


def normalize(ent: Entity, row: dict) -> dict:
    out = {}
    for key in META_COLUMNS:
        value = row.get(key)
        if key in ("created_at", "updated_at") and isinstance(value, str):
            from ..fieldtypes import parse_datetime

            value = parse_datetime(value)
        elif key in ("created_at", "updated_at") and value is not None and getattr(value, "tzinfo", None):
            value = value.replace(tzinfo=None)
        elif value is not None and key not in ("created_at", "updated_at"):
            value = int(value)
        out[key] = value
    for f in ent.fields:
        out[f.name] = f.normalize(row.get(f.name))
    return out


def validate(ent: Entity, data: dict, partial: bool = False) -> tuple[dict, dict[str, ValidationError]]:
    """Convert raw input values.  Returns ``(values, errors)``."""
    values: dict = {}
    errors: dict[str, ValidationError] = {}
    for f in ent.fields:
        if f.name not in data:
            if partial:
                continue
            if f.field_type == "boolean":
                values[f.name] = False
                continue
            raw = None
        else:
            raw = data[f.name]
        try:
            value = f.parse(raw)
        except ValidationError as exc:
            errors[f.name] = exc
            continue
        if value is None and f.required:
            errors[f.name] = ValidationError("error.required")
            continue
        values[f.name] = value
    return values, errors


def apply_defaults(ent: Entity, data: dict) -> dict:
    """Fill missing values with field default values (strings)."""
    data = dict(data)
    for f in ent.fields:
        if f.name not in data and f.default_value not in (None, ""):
            data[f.name] = f.default_value
    return data


def _where(conn: Conn, ent: Entity, search: str | None, owner_id: int | None, since_id: int | None,
           filters: dict | None = None) -> tuple[str, list]:
    conds: list[str] = []
    params: list = []
    if owner_id is not None:
        conds.append(f"{conn.q('created_by')} = ?")
        params.append(owner_id)
    if since_id is not None:
        conds.append(f"{conn.q('id')} > ?")
        params.append(since_id)
    for name, value in (filters or {}).items():
        conds.append(f"{conn.q(name)} = ?")
        params.append(value)
    if search:
        term = conn.dialect.search_term(search)
        parts = []
        for f in ent.fields:
            if f.field_type in ("text", "longtext", "choice", "email"):
                parts.append(conn.dialect.like_sql(conn.q(f.name)))
                params.append(term)
            elif f.field_type in ("integer", "decimal", "currency", "date"):
                parts.append(conn.dialect.like_sql(conn.dialect.cast_text_sql(conn.q(f.name))))
                params.append(term)
        if search.strip().isdigit():
            parts.append(f"{conn.q('id')} = ?")
            params.append(int(search.strip()))
        conds.append("(" + (" OR ".join(parts) or "1 = 0") + ")")
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


def list_records(conn: Conn, ent: Entity, *, search: str | None = None, order: str = "id",
                 desc: bool = True, limit: int | None = 25, offset: int = 0, owner_id: int | None = None,
                 since_id: int | None = None, filters: dict | None = None) -> list[dict]:
    if order not in META_COLUMNS and ent.field(order) is None:
        order = "id"
    where, params = _where(conn, ent, search, owner_id, since_id, filters)
    direction = "DESC" if desc else "ASC"
    order_sql = f" ORDER BY {conn.q(order)} {direction}"
    if order != "id":
        order_sql += f", {conn.q('id')} {direction}"
    sql = f"SELECT * FROM {conn.q(ent.table)}{where}{order_sql}{conn.dialect.limit_sql(limit, offset)}"
    return [normalize(ent, r) for r in conn.all(sql, params)]


def count_records(conn: Conn, ent: Entity, *, search: str | None = None, owner_id: int | None = None) -> int:
    where, params = _where(conn, ent, search, owner_id, None)
    return int(conn.scalar(f"SELECT COUNT(*) FROM {conn.q(ent.table)}{where}", params))


def get_record(conn: Conn, ent: Entity, record_id: int) -> dict | None:
    row = conn.one(f"SELECT * FROM {conn.q(ent.table)} WHERE {conn.q('id')} = ?", [record_id])
    return normalize(ent, row) if row else None


def _check_constraints(conn: Conn, ent: Entity, values: dict, record_id: int | None,
                       user: dict | None) -> dict[str, ValidationError]:
    from . import entities as entities_repo
    from . import files as files_repo

    errors: dict[str, ValidationError] = {}
    for f in ent.fields:
        if f.name not in values or values[f.name] is None:
            continue
        value = values[f.name]
        if f.is_unique:
            sql = f"SELECT COUNT(*) FROM {conn.q(ent.table)} WHERE {conn.q(f.name)} = ?"
            params = [value]
            if record_id is not None:
                sql += f" AND {conn.q('id')} <> ?"
                params.append(record_id)
            if conn.scalar(sql, params):
                errors[f.name] = ValidationError("error.not_unique")
        if f.field_type == "reference":
            target = entities_repo.get_entity(conn, f.ref_entity or "")
            if target is None or get_record(conn, target, value) is None:
                errors[f.name] = ValidationError("error.reference_missing")
        if f.is_file:
            row = files_repo.get_file(conn, value)
            if row is None or row["kind"] != f.field_type or row["entity"] not in (None, ent.name):
                errors[f.name] = ValidationError("error.file_missing")
            elif user is not None and user["role"] == "dealer" and row["created_by"] not in (None, user["id"]):
                errors[f.name] = ValidationError("error.file_missing")
    return errors


def create_record(conn: Conn, ent: Entity, values: dict, user: dict | None = None,
                  api_key_id: int | None = None) -> int:
    errors = _check_constraints(conn, ent, values, None, user)
    if errors:
        raise RecordError(errors)
    now = utcnow()
    row = dict(values)
    row.update(
        created_at=now,
        updated_at=now,
        created_by=user["id"] if user else None,
        updated_by=user["id"] if user else None,
        api_key_id=api_key_id,
    )
    new_id = conn.insert(ent.table, row)
    _claim_files(conn, ent, values)
    return new_id


def update_record(conn: Conn, ent: Entity, record_id: int, values: dict, user: dict | None = None,
                  api_key_id: int | None = None) -> list[dict]:
    """Update a record; returns file rows that were replaced and must be removed."""
    old = get_record(conn, ent, record_id)
    if old is None:
        raise KeyError(record_id)
    errors = _check_constraints(conn, ent, values, record_id, user)
    if errors:
        raise RecordError(errors)
    row = dict(values)
    row.update(updated_at=utcnow(), updated_by=user["id"] if user else None)
    if api_key_id is not None:
        row["api_key_id"] = api_key_id
    conn.update(ent.table, row, {"id": record_id})
    _claim_files(conn, ent, values)
    return _release_files(conn, ent, old, values)


def delete_record(conn: Conn, ent: Entity, record_id: int) -> list[dict]:
    old = get_record(conn, ent, record_id)
    if old is None:
        return []
    conn.delete(ent.table, {"id": record_id})
    return _release_files(conn, ent, old, {f.name: None for f in ent.fields if f.is_file})


def _claim_files(conn: Conn, ent: Entity, values: dict) -> None:
    for f in ent.fields:
        if f.is_file and values.get(f.name):
            conn.update("erp_files", {"entity": ent.name}, {"id": values[f.name]})


def _release_files(conn: Conn, ent: Entity, old: dict, new: dict) -> list[dict]:
    from . import files as files_repo

    removed = []
    for f in ent.fields:
        if not f.is_file or f.name not in new:
            continue
        old_id = old.get(f.name)
        if old_id and old_id != new.get(f.name):
            row = files_repo.get_file(conn, old_id)
            if row:
                conn.delete("erp_files", {"id": old_id})
                removed.append(row)
    return removed


def reference_options(conn: Conn, ent: Entity, limit: int = 1000) -> list[tuple[int, str]]:
    title = ent.title_field_obj
    rows = list_records(conn, ent, order=title.name if title else "id", desc=False, limit=limit)
    return [(r["id"], ent.record_title(r)) for r in rows]


def reference_titles(conn: Conn, ent: Entity, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    ids_list = sorted(ids)[:1000]
    marks = ", ".join("?" for _ in ids_list)
    rows = conn.all(f"SELECT * FROM {conn.q(ent.table)} WHERE {conn.q('id')} IN ({marks})", ids_list)
    return {int(r["id"]): ent.record_title(normalize(ent, r)) for r in rows}


class RecordError(Exception):
    def __init__(self, errors: dict[str, ValidationError]):
        super().__init__(", ".join(errors))
        self.errors = errors
