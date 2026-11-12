"""User defined entities (data screens) and their fields.

Each entity owns a real database table named ``d_<entity name>``.  Adding or
removing a field alters that table, so data stays in ordinary, queryable
database columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..db import Column, Conn, Table
from ..db.database import utcnow
from ..fieldtypes import FIELD_NAME_RE, FIELD_TYPES, Field, ValidationError, field_from_row
from ..schema import SYSTEM_COLUMNS, data_table_name

PERM_USER = ("write", "read", "none")
PERM_DEALER = ("none", "read", "own")
RESERVED_ENTITY_NAMES = {"new", "api", "admin", "files"}


@dataclass(slots=True)
class Entity:
    id: int | None
    name: str
    label: str
    description: str = ""
    menu_id: int | None = None
    sort_order: int = 0
    perm_user: str = "write"
    perm_dealer: str = "none"
    title_field: str | None = None
    is_sensor: bool = False
    read_interval_ms: int = 5000
    page_size: int | None = None
    fields: list[Field] = field(default_factory=list)

    @property
    def table(self) -> str:
        return data_table_name(self.name)

    def field(self, name: str) -> Field | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def list_fields(self) -> list[Field]:
        shown = [f for f in self.fields if f.show_in_list]
        return shown or self.fields[:5]

    @property
    def title_field_obj(self) -> Field | None:
        if self.title_field:
            f = self.field(self.title_field)
            if f:
                return f
        for f in self.fields:
            if f.field_type in ("text", "choice", "email"):
                return f
        return self.fields[0] if self.fields else None

    def record_title(self, record: dict) -> str:
        f = self.title_field_obj
        if f is not None and record.get(f.name) not in (None, ""):
            return str(record[f.name])
        return f"#{record.get('id')}"

    # -- permissions ---------------------------------------------------------
    def can_read(self, user: dict) -> bool:
        match user["role"]:
            case "admin":
                return True
            case "user":
                return self.perm_user in ("read", "write")
            case "dealer":
                return self.perm_dealer in ("read", "own")
        return False

    def can_write(self, user: dict) -> bool:
        match user["role"]:
            case "admin":
                return True
            case "user":
                return self.perm_user == "write"
            case "dealer":
                return self.perm_dealer == "own"
        return False

    def owner_filter(self, user: dict) -> int | None:
        """User id records must belong to, or ``None`` when all are visible."""
        if user["role"] == "dealer" and self.perm_dealer == "own":
            return user["id"]
        return None

    def table_def(self) -> Table:
        cols = [
            Column("id", "pk"),
            Column("created_at", "datetime"),
            Column("updated_at", "datetime"),
            Column("created_by", "int"),
            Column("updated_by", "int"),
            Column("api_key_id", "int"),
        ]
        cols += [f.column() for f in self.fields]
        return Table(self.table, cols, [(f"ix_{self.table}_created", ["created_at"], False)])

    def as_dict(self, with_fields: bool = True) -> dict:
        d = {
            "name": self.name,
            "label": self.label,
            "description": self.description or "",
            "menu_id": self.menu_id,
            "sort_order": self.sort_order,
            "perm_user": self.perm_user,
            "perm_dealer": self.perm_dealer,
            "title_field": self.title_field,
            "is_sensor": self.is_sensor,
            "read_interval_ms": self.read_interval_ms,
            "page_size": self.page_size,
        }
        if with_fields:
            d["fields"] = [f.as_dict() for f in self.fields]
        return d


def _entity_from_row(row: dict) -> Entity:
    return Entity(
        id=row["id"],
        name=row["name"],
        label=row["label"],
        description=row.get("description") or "",
        menu_id=row.get("menu_id"),
        sort_order=int(row.get("sort_order") or 0),
        perm_user=row.get("perm_user") or "write",
        perm_dealer=row.get("perm_dealer") or "none",
        title_field=row.get("title_field") or None,
        is_sensor=bool(row.get("is_sensor")),
        read_interval_ms=int(row.get("read_interval_ms") or 5000),
        page_size=row.get("page_size") or None,
    )


def list_entities(conn: Conn) -> list[Entity]:
    rows = conn.all(
        f"SELECT * FROM {conn.q('erp_entities')} ORDER BY {conn.q('sort_order')}, {conn.q('label')}"
    )
    entities = [_entity_from_row(r) for r in rows]
    by_id = {e.id: e for e in entities}
    for frow in conn.all(
        f"SELECT * FROM {conn.q('erp_fields')} ORDER BY {conn.q('sort_order')}, {conn.q('id')}"
    ):
        ent = by_id.get(frow["entity_id"])
        if ent is not None:
            ent.fields.append(field_from_row(frow))
    return entities


def get_entity(conn: Conn, name: str) -> Entity | None:
    row = conn.one(f"SELECT * FROM {conn.q('erp_entities')} WHERE {conn.q('name')} = ?", [name])
    if row is None:
        return None
    ent = _entity_from_row(row)
    ent.fields = [
        field_from_row(r)
        for r in conn.all(
            f"SELECT * FROM {conn.q('erp_fields')} WHERE {conn.q('entity_id')} = ? "
            f"ORDER BY {conn.q('sort_order')}, {conn.q('id')}",
            [ent.id],
        )
    ]
    return ent


def get_entity_by_id(conn: Conn, entity_id: int) -> Entity | None:
    name = conn.scalar(f"SELECT {conn.q('name')} FROM {conn.q('erp_entities')} WHERE {conn.q('id')} = ?", [entity_id])
    return get_entity(conn, name) if name else None


def validate_entity(ent: Entity, is_new: bool) -> dict[str, str]:
    errors: dict[str, str] = {}
    if is_new:
        if not FIELD_NAME_RE.match(ent.name or "") or ent.name in RESERVED_ENTITY_NAMES:
            errors["name"] = "error.invalid_identifier"
    if not (ent.label or "").strip():
        errors["label"] = "error.required"
    if ent.perm_user not in PERM_USER:
        errors["perm_user"] = "error.invalid_value"
    if ent.perm_dealer not in PERM_DEALER:
        errors["perm_dealer"] = "error.invalid_value"
    if not 100 <= int(ent.read_interval_ms or 0) <= 86_400_000:
        errors["read_interval_ms"] = "error.invalid_interval"
    if ent.page_size is not None and not 5 <= int(ent.page_size) <= 500:
        errors["page_size"] = "error.invalid_value"
    return errors


def _entity_values(ent: Entity) -> dict:
    return {
        "label": ent.label.strip(),
        "description": ent.description or "",
        "menu_id": ent.menu_id,
        "sort_order": int(ent.sort_order or 0),
        "perm_user": ent.perm_user,
        "perm_dealer": ent.perm_dealer,
        "title_field": ent.title_field or None,
        "is_sensor": bool(ent.is_sensor),
        "read_interval_ms": int(ent.read_interval_ms or 5000),
        "page_size": ent.page_size,
    }


def create_entity(conn: Conn, ent: Entity, create_fields: bool = False) -> int:
    """Create the entity row and its data table.

    With ``create_fields`` the fields already attached to ``ent`` are created
    too (used when importing definitions).
    """
    errors = validate_entity(ent, is_new=True)
    if errors:
        raise ValidationError(next(iter(errors.values())))
    if get_entity(conn, ent.name) is not None:
        raise ValidationError("error.duplicate_name")
    fields = list(ent.fields) if create_fields else []
    for f in fields:
        _validate_field(f, ent, is_new=True)
    ent.fields = fields
    if conn.table_exists(ent.table):
        raise ValidationError("error.table_exists", table=ent.table)
    conn.script(conn.dialect.create_table_sql(ent.table_def(), if_not_exists=False))
    values = _entity_values(ent) | {"name": ent.name, "created_at": utcnow()}
    ent.id = conn.insert("erp_entities", values)
    for i, f in enumerate(fields):
        f.entity_id = ent.id
        f.id = conn.insert("erp_fields", _field_values(f) | {"entity_id": ent.id, "name": f.name,
                                                               "field_type": f.field_type,
                                                               "sort_order": f.sort_order or (i + 1) * 10})
    return ent.id


def update_entity(conn: Conn, ent: Entity) -> None:
    errors = validate_entity(ent, is_new=False)
    if errors:
        raise ValidationError(next(iter(errors.values())))
    conn.update("erp_entities", _entity_values(ent), {"id": ent.id})


def delete_entity(conn: Conn, ent: Entity) -> list[dict]:
    """Drop the entity and its table; returns file rows that must be removed."""
    files = conn.all(f"SELECT * FROM {conn.q('erp_files')} WHERE {conn.q('entity')} = ?", [ent.name])
    conn.delete("erp_files", {"entity": ent.name})
    conn.delete("erp_fields", {"entity_id": ent.id})
    conn.delete("erp_entities", {"id": ent.id})
    conn.update("erp_fields", {"ref_entity": None}, {"ref_entity": ent.name})
    conn.execute(conn.dialect.drop_table_sql(ent.table)).close()
    return files


# ---------------------------------------------------------------- fields
def _validate_field(f: Field, ent: Entity, is_new: bool) -> None:
    if is_new:
        if not FIELD_NAME_RE.match(f.name or "") or f.name in SYSTEM_COLUMNS or f.name == "new":
            raise ValidationError("error.invalid_identifier")
        if any(o.name == f.name and o is not f for o in ent.fields):
            raise ValidationError("error.duplicate_name")
        if f.field_type not in FIELD_TYPES:
            raise ValidationError("error.invalid_value")
        if f.field_type == "text" and not 1 <= int(f.max_length or 255) <= 4000:
            raise ValidationError("error.invalid_length")
        if f.field_type in ("decimal", "currency") and f.decimal_places is not None:
            if not 0 <= int(f.decimal_places) <= 8:
                raise ValidationError("error.invalid_value")
    if not (f.label or "").strip():
        raise ValidationError("error.required")
    if f.field_type == "reference" and not f.ref_entity:
        raise ValidationError("error.reference_required")
    if f.field_type == "choice" and not f.choices:
        raise ValidationError("error.options_required")
    if f.default_value not in (None, ""):
        if f.is_file or f.field_type == "reference":
            raise ValidationError("error.no_default_allowed")
        f.parse(f.default_value)


def _field_values(f: Field) -> dict:
    return {
        "label": f.label.strip(),
        "required": bool(f.required),
        "is_unique": bool(f.is_unique),
        "show_in_list": bool(f.show_in_list),
        "max_length": f.max_length if f.field_type == "text" else None,
        "decimal_places": f.decimal_places if f.field_type in ("decimal", "currency") else None,
        "currency": (f.currency or None) if f.field_type == "currency" else None,
        "options": f.options or None,
        "ref_entity": f.ref_entity or None,
        "default_value": f.default_value or None,
        "help_text": f.help_text or None,
        "sort_order": int(f.sort_order or 0),
    }


def add_field(conn: Conn, ent: Entity, f: Field) -> int:
    if f.field_type == "text" and not f.max_length:
        f.max_length = 255
    ent.fields.append(f)
    try:
        _validate_field(f, ent, is_new=True)
    finally:
        ent.fields.remove(f)
    if f.field_type == "reference" and get_entity(conn, f.ref_entity or "") is None:
        raise ValidationError("error.reference_required")
    if not f.sort_order:
        f.sort_order = (max((x.sort_order for x in ent.fields), default=0) // 10 + 1) * 10
    conn.execute(conn.dialect.add_column_sql(ent.table, f.column())).close()
    values = _field_values(f) | {"entity_id": ent.id, "name": f.name, "field_type": f.field_type}
    f.id = conn.insert("erp_fields", values)
    f.entity_id = ent.id
    return f.id


def update_field(conn: Conn, ent: Entity, f: Field) -> None:
    _validate_field(f, ent, is_new=False)
    values = _field_values(f)
    # Storage relevant properties can not change after creation.
    for key in ("max_length", "decimal_places", "ref_entity"):
        values.pop(key, None)
    conn.update("erp_fields", values, {"id": f.id})


def delete_field(conn: Conn, ent: Entity, f: Field) -> list[dict]:
    files: list[dict] = []
    if f.is_file:
        ids = [r[f.name] for r in conn.all(
            f"SELECT {conn.q(f.name)} FROM {conn.q(ent.table)} WHERE {conn.q(f.name)} IS NOT NULL")]
        for file_id in ids:
            row = conn.one(f"SELECT * FROM {conn.q('erp_files')} WHERE {conn.q('id')} = ?", [file_id])
            if row:
                files.append(row)
                conn.delete("erp_files", {"id": file_id})
    conn.delete("erp_fields", {"id": f.id})
    if ent.title_field == f.name:
        conn.update("erp_entities", {"title_field": None}, {"id": ent.id})
    conn.execute(conn.dialect.drop_column_sql(ent.table, f.name)).close()
    return files
