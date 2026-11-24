"""System tables of the application and schema installation/migration."""

from __future__ import annotations

from .db import Column as C
from .db import Conn, Table
from .db.database import utcnow

#: Version of the database layout.  History:
#: 1 - first release
#: 2 - SQLite only: decimal and currency columns store exact text (see
#:     erp.db.dialects.SQLiteDialect.type_sql); :func:`migrate` converts them.
SCHEMA_VERSION = 2
DATA_TABLE_PREFIX = "d_"

#: Columns every user defined (data) table has.  Field names may not reuse them.
SYSTEM_COLUMNS = ("id", "created_at", "updated_at", "created_by", "updated_by", "api_key_id")


SYSTEM_TABLES: list[Table] = [
    Table("erp_meta", [C("meta_key", "varchar", False, 100), C("meta_value", "text")],
          [("ux_erp_meta_key", ["meta_key"], True)]),
    Table("erp_settings", [C("setting_key", "varchar", False, 100), C("setting_value", "text")],
          [("ux_erp_settings_key", ["setting_key"], True)]),
    Table(
        "erp_users",
        [
            C("id", "pk"),
            C("username", "varchar", False, 100),
            C("password_hash", "varchar", False, 255),
            C("full_name", "varchar", True, 200),
            C("email", "varchar", True, 200),
            C("role", "varchar", False, 20),
            C("language", "varchar", True, 10),
            C("active", "bool", False),
            C("created_at", "datetime"),
            C("last_login_at", "datetime"),
        ],
        [("ux_erp_users_username", ["username"], True)],
    ),
    Table(
        "erp_sessions",
        [
            C("token_hash", "varchar", False, 64),
            C("user_id", "int", False),
            C("created_at", "datetime"),
            C("expires_at", "datetime"),
            C("ip", "varchar", True, 64),
            C("user_agent", "varchar", True, 255),
        ],
        [("ux_erp_sessions_token", ["token_hash"], True)],
    ),
    Table(
        "erp_menus",
        [
            C("id", "pk"),
            C("parent_id", "int"),
            C("title", "varchar", False, 200),
            C("sort_order", "int"),
        ],
    ),
    Table(
        "erp_entities",
        [
            C("id", "pk"),
            C("name", "varchar", False, 50),
            C("label", "varchar", False, 200),
            C("description", "text"),
            C("menu_id", "int"),
            C("sort_order", "int"),
            C("perm_user", "varchar", False, 10),
            C("perm_dealer", "varchar", False, 10),
            C("title_field", "varchar", True, 50),
            C("is_sensor", "bool", False),
            C("read_interval_ms", "int"),
            C("page_size", "int"),
            C("created_at", "datetime"),
        ],
        [("ux_erp_entities_name", ["name"], True)],
    ),
    Table(
        "erp_fields",
        [
            C("id", "pk"),
            C("entity_id", "int", False),
            C("name", "varchar", False, 50),
            C("label", "varchar", False, 200),
            C("field_type", "varchar", False, 20),
            C("required", "bool", False),
            C("is_unique", "bool", False),
            C("show_in_list", "bool", False),
            C("max_length", "int"),
            C("decimal_places", "int"),
            C("currency", "varchar", True, 3),
            C("options", "text"),
            C("ref_entity", "varchar", True, 50),
            C("default_value", "varchar", True, 255),
            C("help_text", "varchar", True, 500),
            C("sort_order", "int"),
        ],
        [("ux_erp_fields_entity_name", ["entity_id", "name"], True)],
    ),
    Table(
        "erp_files",
        [
            C("id", "pk"),
            C("entity", "varchar", True, 50),
            C("original_name", "varchar", False, 255),
            C("mime_type", "varchar", False, 100),
            C("kind", "varchar", False, 20),
            C("size_bytes", "int", False),
            C("sha256", "varchar", False, 64),
            C("storage_key", "varchar", False, 100),
            C("created_at", "datetime"),
            C("created_by", "int"),
        ],
    ),
    Table(
        "erp_api_keys",
        [
            C("id", "pk"),
            C("name", "varchar", False, 100),
            C("token_prefix", "varchar", False, 16),
            C("token_hash", "varchar", False, 64),
            C("entities", "text"),
            C("can_read", "bool", False),
            C("can_write", "bool", False),
            C("allowed_ips", "text"),
            C("min_interval_ms", "int"),
            C("expires_at", "datetime"),
            C("active", "bool", False),
            C("created_at", "datetime"),
            C("created_by", "int"),
            C("last_used_at", "datetime"),
        ],
        [("ux_erp_api_keys_hash", ["token_hash"], True)],
    ),
    Table(
        "erp_audit",
        [
            C("id", "pk"),
            C("created_at", "datetime"),
            C("user_id", "int"),
            C("username", "varchar", True, 100),
            C("action", "varchar", False, 50),
            C("target", "varchar", True, 255),
            C("detail", "text"),
        ],
    ),
]

SYSTEM_TABLE_MAP = {t.name: t for t in SYSTEM_TABLES}


def data_table_name(entity_name: str) -> str:
    """Database table of an entity: ``customers`` is stored in ``d_customers``."""
    return DATA_TABLE_PREFIX + entity_name


def is_installed(conn: Conn) -> bool:
    """True when the database already holds an ERP-Software installation (a schema version)."""
    if not conn.table_exists("erp_meta"):
        return False
    return conn.scalar(
        f"SELECT COUNT(*) FROM {conn.q('erp_meta')} WHERE {conn.q('meta_key')} = ?", ["schema_version"]
    ) > 0


def create_system_tables(conn: Conn) -> None:
    """Create every system table that does not exist yet.

    Existing tables are left alone, so this is safe on an existing database
    and is the first step of every migration.
    """
    for table in SYSTEM_TABLES:
        if conn.table_exists(table.name):
            continue
        conn.script(conn.dialect.create_table_sql(table, if_not_exists=False))


def install_schema(conn: Conn) -> None:
    """Create all system tables and record the schema version."""
    create_system_tables(conn)
    if not is_installed(conn):
        conn.insert("erp_meta", {"meta_key": "schema_version", "meta_value": str(SCHEMA_VERSION)}, False)
        conn.insert("erp_meta", {"meta_key": "installed_at", "meta_value": utcnow().isoformat()}, False)


def migrate(conn: Conn) -> None:
    """Bring an existing installation up to the current schema version."""
    create_system_tables(conn)
    current = conn.scalar(
        f"SELECT {conn.q('meta_value')} FROM {conn.q('erp_meta')} WHERE {conn.q('meta_key')} = ?",
        ["schema_version"],
    )
    if current is None:
        install_schema(conn)
        return
    version = int(current)
    if version < 2:
        _sqlite_exact_decimals(conn)
    # Future migrations go here: ``if version < 3: ...``
    if version < SCHEMA_VERSION:
        conn.update("erp_meta", {"meta_value": str(SCHEMA_VERSION)}, {"meta_key": "schema_version"})


def _sqlite_exact_decimals(conn: Conn) -> None:
    """Schema version 2: rebuild SQLite decimal columns with TEXT affinity.

    Older SQLite installations declared decimal and currency columns as plain
    ``DECIMAL``, whose NUMERIC affinity keeps only about 15 significant digits.
    Each such column is renamed, re-created with the exact text type and filled
    with the values written as fixed point text, then the old column is dropped.
    Digits that were already lost can not come back, but no further ones are.
    The function is idempotent: columns that already have the new type are
    skipped, so it is safe after restoring an old backup too.
    """
    if conn.dialect.name != "sqlite":
        return
    from .repo import entities as entities_repo  # imported here: the repo modules import this module

    for ent in entities_repo.list_entities(conn):
        if not conn.table_exists(ent.table):
            continue
        declared = {r["name"]: (r["type"] or "").upper() for r in conn.all(f"PRAGMA table_info({conn.q(ent.table)})")}
        for f in ent.fields:
            if f.type.column_kind != "decimal" or "TEXT" in declared.get(f.name, "TEXT"):
                continue
            table, col, old = conn.q(ent.table), conn.q(f.name), conn.q(f.name + "__old")
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN {col} TO {old}").close()
            conn.execute(conn.dialect.add_column_sql(ent.table, f.column())).close()
            for row in conn.all(f"SELECT {conn.q('id')}, {old} AS v FROM {table} WHERE {old} IS NOT NULL"):
                value = f.normalize(row["v"])  # Decimal quantized to the field's scale
                conn.update(ent.table, {f.name: value}, {"id": row["id"]})
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {old}").close()
