"""User defined menu groups used to organise data screens."""

from __future__ import annotations

from ..db import Conn


def list_menus(conn: Conn) -> list[dict]:
    return conn.all(
        f"SELECT * FROM {conn.q('erp_menus')} ORDER BY {conn.q('sort_order')}, {conn.q('title')}"
    )


def get_menu(conn: Conn, menu_id: int) -> dict | None:
    return conn.one(f"SELECT * FROM {conn.q('erp_menus')} WHERE {conn.q('id')} = ?", [menu_id])


def save_menu(conn: Conn, menu_id: int | None, title: str, parent_id: int | None, sort_order: int) -> int:
    values = {"title": title, "parent_id": parent_id, "sort_order": sort_order}
    if menu_id:
        conn.update("erp_menus", values, {"id": menu_id})
        return menu_id
    return conn.insert("erp_menus", values)


def descendants(menus: list[dict], menu_id: int) -> set[int]:
    result: set[int] = set()
    stack = [menu_id]
    while stack:
        current = stack.pop()
        for m in menus:
            if m["parent_id"] == current and m["id"] not in result:
                result.add(m["id"])
                stack.append(m["id"])
    return result


def delete_menu(conn: Conn, menu_id: int) -> None:
    """Delete a menu; its children and entities move to the parent menu."""
    menu = get_menu(conn, menu_id)
    if menu is None:
        return
    parent = menu["parent_id"]
    conn.update("erp_menus", {"parent_id": parent}, {"parent_id": menu_id})
    conn.update("erp_entities", {"menu_id": parent}, {"menu_id": menu_id})
    conn.delete("erp_menus", {"id": menu_id})


def menu_path(menus: list[dict], menu_id: int | None) -> list[dict]:
    """Breadcrumb list from the root to ``menu_id``."""
    by_id = {m["id"]: m for m in menus}
    path: list[dict] = []
    seen: set[int] = set()
    while menu_id and menu_id in by_id and menu_id not in seen:
        seen.add(menu_id)
        path.append(by_id[menu_id])
        menu_id = by_id[menu_id]["parent_id"]
    return list(reversed(path))
