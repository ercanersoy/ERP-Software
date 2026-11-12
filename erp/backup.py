"""Export (backup) and import (restore) as SQL or TOML files.

Kinds of export:

``config``  all configuration: settings, menus and data definitions
``schema``  data formats only: entity and field definitions
``data``    records of the selected entities
``full``    the whole database: everything above plus users, API keys,
            file metadata and the audit log
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import json
import tomllib

from . import __version__, charsets, tomlwriter
from .db import Conn, Dialect, Table, get_dialect
from .db.database import utcnow
from .fieldtypes import Field, ValidationError, parse_datetime
from .repo import entities as entities_repo
from .repo import files as files_repo
from .repo import records as records_repo
from .repo import settings as settings_repo
from .schema import SCHEMA_VERSION, SYSTEM_TABLE_MAP, SYSTEM_TABLES

KINDS = ("config", "schema", "data", "full")
FORMATS = ("toml", "sql")
FORMAT_ID = "erp-software"

CONFIG_TABLES = ("erp_settings", "erp_menus", "erp_entities", "erp_fields")
SCHEMA_TABLES = ("erp_entities", "erp_fields")
#: Tables exported in a full backup, in restore order.
FULL_TABLES = ("erp_meta", "erp_settings", "erp_users", "erp_menus", "erp_entities", "erp_fields",
               "erp_files", "erp_api_keys", "erp_audit")


class BackupError(Exception):
    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


# ====================================================================== helpers
def coerce(kind: str, value):
    """Coerce a raw database value to the Python type of a column kind."""
    if value is None:
        return None
    match kind:
        case "bool":
            if isinstance(value, (bytes, bytearray)):
                return value not in (b"\x00", b"0", b"")
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes")
            return bool(value)
        case "int" | "pk":
            return int(value)
        case "decimal":
            return value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))
        case "float":
            return float(value)
        case "datetime":
            if isinstance(value, str):
                return parse_datetime(value)
            if isinstance(value, dt.datetime) and value.tzinfo is not None:
                return value.astimezone(dt.UTC).replace(tzinfo=None)
            return value
        case "date":
            if isinstance(value, str):
                return dt.date.fromisoformat(value[:10])
            if isinstance(value, dt.datetime):
                return value.date()
            return value
        case "varchar" | "text":
            return str(value)
    return value


def _table_rows(conn: Conn, table: Table, where: str = "", params=()) -> list[dict]:
    order = f" ORDER BY {conn.q('id')}" if table.column("id") else ""
    rows = conn.all(f"SELECT * FROM {conn.q(table.name)}{where}{order}", params)
    out = []
    for row in rows:
        out.append({c.name: coerce(c.kind, row.get(c.name)) for c in table.columns})
    return out


def _entity_rows(conn: Conn, ent) -> list[dict]:
    rows = records_repo.list_records(conn, ent, order="id", desc=False, limit=None)
    return rows


def _file_rows(conn: Conn, entity_names: list[str] | None) -> list[dict]:
    table = SYSTEM_TABLE_MAP["erp_files"]
    if entity_names is None:
        return _table_rows(conn, table)
    if not entity_names:
        return []
    marks = ", ".join("?" for _ in entity_names)
    return _table_rows(conn, table, f" WHERE {conn.q('entity')} IN ({marks})", entity_names)


# ====================================================================== snapshot
def snapshot(conn: Conn, kind: str, entity_names: list[str] | None = None) -> dict:
    """Collect everything belonging to an export kind."""
    if kind not in KINDS:
        raise BackupError("error.invalid_value")
    entities = entities_repo.list_entities(conn)
    if kind == "data" and entity_names is not None:
        wanted = set(entity_names)
        entities = [e for e in entities if e.name in wanted]
    snap: dict = {"kind": kind, "entities": entities, "tables": {}, "data": {}, "files": []}
    if kind == "config":
        tables = CONFIG_TABLES
    elif kind == "schema":
        tables = SCHEMA_TABLES
    elif kind == "full":
        tables = FULL_TABLES
    else:
        tables = ()
    for name in tables:
        snap["tables"][name] = _table_rows(conn, SYSTEM_TABLE_MAP[name])
    if kind in ("data", "full"):
        for ent in entities:
            snap["data"][ent.name] = _entity_rows(conn, ent)
        if kind == "data":
            snap["files"] = _file_rows(conn, [e.name for e in entities])
        else:
            snap["files"] = snap["tables"]["erp_files"]
    return snap


# ====================================================================== TOML
def _strip_none(row: dict) -> dict:
    return {k: v for k, v in row.items() if v is not None}


def to_toml(conn: Conn, kind: str, charset: str = "utf-8", entity_names: list[str] | None = None,
            include_files: bool = False, upload_dir: str | None = None) -> bytes:
    charset = charsets.normalize(charset)
    snap = snapshot(conn, kind, entity_names)
    doc: dict = {
        "backup": {
            "format": FORMAT_ID,
            "kind": kind,
            "schema_version": SCHEMA_VERSION,
            "app_version": __version__,
            "source_dialect": conn.dialect.name,
            "created_at": utcnow().replace(microsecond=0),
            "charset": charset,
        }
    }
    tables = snap["tables"]
    if "erp_settings" in tables:
        doc["settings"] = {r["setting_key"]: r["setting_value"] or "" for r in tables["erp_settings"]}
    if "erp_menus" in tables:
        doc["menus"] = [_strip_none(r) for r in tables["erp_menus"]]
    if kind in ("config", "schema", "full"):
        ents = []
        for ent in snap["entities"]:
            d = _strip_none(ent.as_dict(with_fields=False))
            d["id"] = ent.id
            d["fields"] = [_strip_none(f.as_dict()) for f in ent.fields]
            ents.append(d)
        doc["entities"] = ents
    if kind == "full":
        doc["meta"] = {r["meta_key"]: r["meta_value"] or "" for r in tables["erp_meta"]}
        doc["users"] = [_strip_none(r) for r in tables["erp_users"]]
        doc["api_keys"] = [_strip_none(r) for r in tables["erp_api_keys"]]
        doc["audit"] = [_strip_none(r) for r in tables["erp_audit"]]
    if kind in ("data", "full"):
        if kind == "data":
            doc["entities"] = [
                _strip_none({"name": e.name, "label": e.label}) | {"fields": [_strip_none(f.as_dict()) for f in e.fields]}
                for e in snap["entities"]
            ]
        files = []
        for row in snap["files"]:
            row = _strip_none(dict(row))
            if include_files and upload_dir:
                try:
                    data = files_repo.storage_path(upload_dir, row["storage_key"]).read_bytes()
                    row["content_base64"] = base64.b64encode(data).decode("ascii")
                except (OSError, ValueError):
                    pass
            files.append(row)
        doc["files"] = files
        doc["data"] = {
            name: [_strip_none(r) for r in rows] for name, rows in snap["data"].items()
        }
    comments = [
        f"charset: {charset}",
        f"ERP-Software {kind} export, {doc['backup']['created_at'].isoformat()} UTC",
        "Values that are missing in a row are NULL.",
    ]
    text = tomlwriter.dumps(doc, charset, comments)
    return charsets.encode(text, charset, errors="replace")


# ====================================================================== SQL
def _insert_statements(d: Dialect, table: Table, rows: list[dict]) -> list[str]:
    if not rows:
        return []
    cols = [c.name for c in table.columns]
    collist = ", ".join(d.quote(c) for c in cols)
    stmts = []
    has_id = table.column("id") is not None and table.column("id").kind == "pk"
    if has_id:
        stmts += d.explicit_id_begin(table.name)
    for row in rows:
        values = ", ".join(d.literal(coerce(table.column(c).kind, row.get(c))) for c in cols)
        stmts.append(f"INSERT INTO {d.quote(table.name)} ({collist}) VALUES ({values})")
    if has_id:
        stmts += d.explicit_id_end(table.name)
    return stmts


def to_sql(conn: Conn, kind: str, dialect_name: str | None = None, charset: str = "utf-8",
           entity_names: list[str] | None = None) -> bytes:
    charset = charsets.normalize(charset)
    d = get_dialect(dialect_name or conn.dialect.name)
    snap = snapshot(conn, kind, entity_names)
    entities = snap["entities"]
    stmts: list[str] = []
    stmts += d.dump_preamble()
    if kind == "full":
        for ent in entities:
            stmts.append(d.drop_table_sql(ent.table))
        for table in reversed(SYSTEM_TABLES):
            stmts.append(d.drop_table_sql(table.name))
        for table in SYSTEM_TABLES:
            stmts += d.create_table_sql(table, if_not_exists=False)
        for ent in entities:
            stmts += d.create_table_sql(ent.table_def(), if_not_exists=False)
        for name in FULL_TABLES:
            stmts += _insert_statements(d, SYSTEM_TABLE_MAP[name], snap["tables"][name])
        for ent in entities:
            stmts += _insert_statements(d, ent.table_def(), snap["data"][ent.name])
    elif kind in ("config", "schema"):
        names = CONFIG_TABLES if kind == "config" else SCHEMA_TABLES
        for name in names:
            stmts += d.create_table_sql(SYSTEM_TABLE_MAP[name], if_not_exists=True)
        for ent in entities:
            stmts += d.create_table_sql(ent.table_def(), if_not_exists=True)
        for name in reversed(names):
            stmts.append(f"DELETE FROM {d.quote(name)}")
        for name in names:
            stmts += _insert_statements(d, SYSTEM_TABLE_MAP[name], snap["tables"][name])
    else:  # data
        files_table = SYSTEM_TABLE_MAP["erp_files"]
        stmts += d.create_table_sql(files_table, if_not_exists=True)
        for ent in entities:
            stmts += d.create_table_sql(ent.table_def(), if_not_exists=True)
            stmts.append(f"DELETE FROM {d.quote(ent.table)}")
            stmts.append(f"DELETE FROM {d.quote('erp_files')} WHERE {d.quote('entity')} = {d.literal(ent.name)}")
        stmts += _insert_statements(d, files_table, snap["files"])
        for ent in entities:
            stmts += _insert_statements(d, ent.table_def(), snap["data"][ent.name])
    stmts += d.dump_postamble()
    header = [
        f"charset: {charset}",
        f"ERP-Software {kind} export for {d.title}",
        f"Created: {utcnow().replace(microsecond=0).isoformat()} UTC, application version {__version__}",
    ]
    if kind in ("data", "full"):
        header.append("Uploaded file contents are stored in the upload directory, not in the database.")
    if not charsets.is_unicode(charset):
        header.append(f"Characters that can not be written in {charset} are replaced with '?'.")
    text = d.comment("\n".join(header)) + "\n\n"
    text += "\n".join(s + d.statement_terminator() for s in stmts) + "\n"
    return charsets.encode(text, charset, errors="replace")


# ====================================================================== import
def load_toml(data: bytes, charset: str | None = None) -> dict:
    declared = charsets.detect_declared(data)
    cs = charsets.normalize(charset) if charset else (declared or "utf-8")
    text = charsets.decode(data, cs)
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise BackupError("error.invalid_toml", detail=str(exc)) from None
    meta = doc.get("backup")
    if not isinstance(meta, dict) or meta.get("format") != FORMAT_ID or meta.get("kind") not in KINDS:
        raise BackupError("error.not_a_backup")
    return doc


def _field_from_dict(d: dict) -> Field:
    return Field(
        id=None,
        entity_id=None,
        name=str(d.get("name", "")),
        label=str(d.get("label") or d.get("name", "")),
        field_type=str(d.get("field_type", "text")),
        required=bool(d.get("required", False)),
        is_unique=bool(d.get("is_unique", False)),
        show_in_list=bool(d.get("show_in_list", True)),
        max_length=d.get("max_length"),
        decimal_places=d.get("decimal_places"),
        currency=d.get("currency"),
        options=d.get("options"),
        ref_entity=d.get("ref_entity"),
        default_value=d.get("default_value"),
        help_text=d.get("help_text"),
        sort_order=int(d.get("sort_order") or 0),
    )


def _entity_from_dict(d: dict) -> entities_repo.Entity:
    ent = entities_repo.Entity(
        id=None,
        name=str(d.get("name", "")),
        label=str(d.get("label") or d.get("name", "")),
        description=str(d.get("description") or ""),
        menu_id=d.get("menu_id"),
        sort_order=int(d.get("sort_order") or 0),
        perm_user=str(d.get("perm_user") or "write"),
        perm_dealer=str(d.get("perm_dealer") or "none"),
        title_field=d.get("title_field"),
        is_sensor=bool(d.get("is_sensor", False)),
        read_interval_ms=int(d.get("read_interval_ms") or 5000),
        page_size=d.get("page_size"),
    )
    ent.fields = [_field_from_dict(f) for f in d.get("fields", []) if isinstance(f, dict)]
    return ent


def _merge_entities(conn: Conn, items: list[dict], menu_ids: set[int]) -> dict[str, int]:
    """Create missing entities and fields, update labels of existing ones."""
    stats = {"entities_created": 0, "fields_created": 0, "entities_updated": 0}
    for item in items:
        new = _entity_from_dict(item)
        if new.menu_id not in menu_ids:
            new.menu_id = None
        current = entities_repo.get_entity(conn, new.name)
        if current is None:
            entities_repo.create_entity(conn, new, create_fields=True)
            stats["entities_created"] += 1
            stats["fields_created"] += len(new.fields)
            continue
        new.id = current.id
        new.fields = current.fields
        if new.title_field and current.field(new.title_field) is None:
            new.title_field = current.title_field
        entities_repo.update_entity(conn, new)
        stats["entities_updated"] += 1
        for fd in item.get("fields", []):
            f = _field_from_dict(fd)
            existing = current.field(f.name)
            if existing is None:
                entities_repo.add_field(conn, current, f)
                current.fields.append(f)
                stats["fields_created"] += 1
            elif existing.field_type == f.field_type:
                f.id = existing.id
                f.entity_id = current.id
                entities_repo.update_field(conn, current, f)
    return stats


def _insert_explicit(conn: Conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    conn.script(conn.dialect.explicit_id_begin(table))
    for row in rows:
        conn.insert(table, row, return_id=False)
    conn.script(conn.dialect.explicit_id_end(table))


def _system_row(table_name: str, item: dict) -> dict:
    table = SYSTEM_TABLE_MAP[table_name]
    return {c.name: coerce(c.kind, item.get(c.name)) for c in table.columns if c.name in item}


def _convert_record(ent, item: dict) -> tuple[dict, dict]:
    # partial=True: rows are kept even if a now-required value is missing.
    values, errors = records_repo.validate(ent, {k: v for k, v in item.items() if ent.field(k)}, partial=True)
    meta = {}
    for key in ("id", "created_by", "updated_by", "api_key_id"):
        if item.get(key) is not None:
            meta[key] = int(item[key])
    for key in ("created_at", "updated_at"):
        if item.get(key) is not None:
            meta[key] = coerce("datetime", item[key])
    return values | meta, errors


def _import_data(conn: Conn, data: dict, mode: str, entity_ids_ok: bool = True) -> dict:
    stats = {"records": 0, "skipped": 0}
    for name, rows in data.items():
        ent = entities_repo.get_entity(conn, name)
        if ent is None or not isinstance(rows, list):
            stats["skipped"] += len(rows) if isinstance(rows, list) else 0
            continue
        if mode == "replace":
            conn.delete(ent.table, {})
        prepared = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            values, errors = _convert_record(ent, item)
            if errors:
                stats["skipped"] += 1
                continue
            now = utcnow()
            values.setdefault("created_at", now)
            values.setdefault("updated_at", now)
            if mode != "replace":
                values.pop("id", None)
            prepared.append(values)
        if mode == "replace" and entity_ids_ok:
            _insert_explicit(conn, ent.table, [p for p in prepared if "id" in p])
            for p in prepared:
                if "id" not in p:
                    conn.insert(ent.table, p)
        else:
            for p in prepared:
                conn.insert(ent.table, p)
        stats["records"] += len(prepared)
    return stats


def _restore_files(doc_files: list[dict], upload_dir: str | None) -> list[dict]:
    rows = []
    for item in doc_files:
        if not isinstance(item, dict):
            continue
        content = item.pop("content_base64", None)
        row = _system_row("erp_files", item)
        if content and upload_dir:
            path = files_repo.storage_path(upload_dir, row["storage_key"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(content))
        rows.append(row)
    return rows


def import_toml(conn: Conn, doc: dict, mode: str = "append", upload_dir: str | None = None) -> dict:
    """Apply a parsed TOML backup.  ``mode`` is ``append`` or ``replace`` for data."""
    kind = doc["backup"]["kind"]
    stats: dict = {"kind": kind}
    if kind == "full":
        return restore_full(conn, doc, upload_dir)
    if kind == "config":
        if isinstance(doc.get("settings"), dict):
            settings_repo.replace_settings(conn, {k: str(v) for k, v in doc["settings"].items()})
        if isinstance(doc.get("menus"), list):
            conn.delete("erp_menus", {})
            _insert_explicit(conn, "erp_menus", [_system_row("erp_menus", m) for m in doc["menus"]])
    if kind in ("config", "schema"):
        menu_ids = {int(m["id"]) for m in conn.all(f"SELECT {conn.q('id')} FROM {conn.q('erp_menus')}")}
        stats |= _merge_entities(conn, [e for e in doc.get("entities", []) if isinstance(e, dict)], menu_ids)
    if kind == "data":
        file_rows = _restore_files(list(doc.get("files", [])), upload_dir)
        known = {int(r["id"]) for r in files_repo.list_files(conn)}
        _insert_explicit(conn, "erp_files", [r for r in file_rows if r.get("id") not in known])
        stats |= _import_data(conn, doc.get("data", {}) or {}, mode)
    return stats


def restore_full(conn: Conn, doc: dict, upload_dir: str | None = None) -> dict:
    """Replace the complete database content with a full backup."""
    entity_items = [e for e in doc.get("entities", []) if isinstance(e, dict)]
    new_entities = [_entity_from_dict(e) for e in entity_items]
    for ent in new_entities:  # validate everything before destroying anything
        errors = entities_repo.validate_entity(ent, is_new=True)
        if errors:
            raise BackupError(next(iter(errors.values())))
    if not any(isinstance(u, dict) and u.get("role") == "admin" for u in doc.get("users", [])):
        raise BackupError("error.backup_without_admin")

    for ent in entities_repo.list_entities(conn):
        conn.execute(conn.dialect.drop_table_sql(ent.table)).close()
    for name in reversed(FULL_TABLES):
        conn.delete(name, {})
    conn.delete("erp_sessions", {})

    for key, value in (doc.get("meta") or {}).items():
        conn.insert("erp_meta", {"meta_key": key, "meta_value": str(value)}, False)
    if not conn.scalar(f"SELECT COUNT(*) FROM {conn.q('erp_meta')}"):
        conn.insert("erp_meta", {"meta_key": "schema_version", "meta_value": str(SCHEMA_VERSION)}, False)
    settings_repo.replace_settings(conn, {k: str(v) for k, v in (doc.get("settings") or {}).items()})
    _insert_explicit(conn, "erp_users", [_system_row("erp_users", u) for u in doc.get("users", [])])
    _insert_explicit(conn, "erp_menus", [_system_row("erp_menus", m) for m in doc.get("menus", [])])

    stats = {"kind": "full", "entities_created": 0, "fields_created": 0}
    for item, ent in zip(entity_items, new_entities):
        conn.script(conn.dialect.create_table_sql(ent.table_def(), if_not_exists=False))
        row = _system_row("erp_entities", item | {"created_at": utcnow()})
        row.update(
            perm_user=ent.perm_user, perm_dealer=ent.perm_dealer, is_sensor=ent.is_sensor,
            read_interval_ms=ent.read_interval_ms, label=ent.label, name=ent.name,
        )
        _insert_explicit(conn, "erp_entities", [row])
        entity_id = int(item["id"]) if item.get("id") is not None else conn.scalar(
            f"SELECT {conn.q('id')} FROM {conn.q('erp_entities')} WHERE {conn.q('name')} = ?", [ent.name])
        for i, f in enumerate(ent.fields):
            values = entities_repo._field_values(f) | {
                "entity_id": entity_id, "name": f.name, "field_type": f.field_type,
                "sort_order": f.sort_order or (i + 1) * 10,
            }
            conn.insert("erp_fields", values)
        stats["entities_created"] += 1
        stats["fields_created"] += len(ent.fields)

    file_rows = _restore_files(list(doc.get("files", [])), upload_dir)
    _insert_explicit(conn, "erp_files", file_rows)
    _insert_explicit(conn, "erp_api_keys", [_system_row("erp_api_keys", k) for k in doc.get("api_keys", [])])
    _insert_explicit(conn, "erp_audit", [_system_row("erp_audit", a) for a in doc.get("audit", [])])
    stats |= _import_data(conn, doc.get("data", {}) or {}, "replace")
    return stats


# ====================================================================== CSV
def to_csv(conn: Conn, ent, charset: str = "utf-8", delimiter: str = ";", rows: list[dict] | None = None) -> bytes:
    import csv
    import io

    if rows is None:
        rows = _entity_rows(conn, ent)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(["id"] + [f.name for f in ent.fields] + ["created_at", "updated_at"])
    for r in rows:
        writer.writerow(
            [r["id"]] + [f.to_text(r.get(f.name)) for f in ent.fields]
            + [r["created_at"].isoformat(sep=" ", timespec="seconds") if r.get("created_at") else "",
               r["updated_at"].isoformat(sep=" ", timespec="seconds") if r.get("updated_at") else ""]
        )
    return charsets.encode(buf.getvalue(), charsets.normalize(charset), errors="replace")


def parse_csv(ent, data: bytes, charset: str = "utf-8", delimiter: str = ";") -> tuple[list[dict], list[tuple[int, str, ValidationError]]]:
    """Parse CSV data for an entity.  Returns ``(values list, errors)``."""
    import csv
    import io

    text = charsets.decode(data, charsets.normalize(charset))
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    good: list[dict] = []
    errors: list[tuple[int, str, ValidationError]] = []
    for lineno, raw in enumerate(reader, start=2):
        item = {k.strip(): v for k, v in raw.items() if k and ent.field(k.strip()) and not ent.field(k.strip()).is_file}
        values, errs = records_repo.validate(ent, records_repo.apply_defaults(ent, item))
        if errs:
            for name, err in errs.items():
                errors.append((lineno, name, err))
            continue
        good.append(values)
    return good, errors


def file_name(kind: str, fmt: str, company: str = "erp", entity: str | None = None) -> str:
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    import unicodedata

    ascii_name = unicodedata.normalize("NFKD", company.replace("ı", "i").replace("İ", "I"))
    ascii_name = ascii_name.encode("ascii", "ignore").decode().lower()
    base = "-".join("".join(c if c.isalnum() else " " for c in ascii_name).split()) or "erp"
    part = f"-{entity}" if entity else ""
    return f"{base}-{kind}{part}-{stamp}.{fmt}"


def json_default(value):
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    raise TypeError(type(value))


def dumps_json(value) -> str:
    return json.dumps(value, default=json_default, ensure_ascii=False)


__all__ = [
    "BackupError", "KINDS", "FORMATS", "to_toml", "to_sql", "load_toml", "import_toml", "restore_full",
    "to_csv", "parse_csv", "file_name", "dumps_json",
]
