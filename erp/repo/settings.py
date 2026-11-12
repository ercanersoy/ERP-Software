"""Application wide settings stored in the database."""

from __future__ import annotations

from ..db import Conn

DEFAULT_SETTINGS: dict[str, str] = {
    "company_name": "ERP",
    "default_language": "tr-TR",
    "default_charset": "utf-8",
    "timezone": "Europe/Istanbul",
    "default_currency": "TRY",
    "page_size": "25",
    "session_hours": "12",
    "api_enabled": "1",
}


def get_settings(conn: Conn) -> dict[str, str]:
    settings = dict(DEFAULT_SETTINGS)
    for row in conn.all(f"SELECT * FROM {conn.q('erp_settings')}"):
        settings[row["setting_key"]] = row["setting_value"] or ""
    return settings


def save_settings(conn: Conn, values: dict[str, str]) -> None:
    for key, value in values.items():
        value = "" if value is None else str(value)
        n = conn.update("erp_settings", {"setting_value": value}, {"setting_key": key})
        if not n:
            exists = conn.scalar(
                f"SELECT COUNT(*) FROM {conn.q('erp_settings')} WHERE {conn.q('setting_key')} = ?", [key]
            )
            if not exists:
                conn.insert("erp_settings", {"setting_key": key, "setting_value": value}, False)


def replace_settings(conn: Conn, values: dict[str, str]) -> None:
    conn.delete("erp_settings", {})
    for key, value in values.items():
        conn.insert("erp_settings", {"setting_key": key, "setting_value": str(value)}, False)
