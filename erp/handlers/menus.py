"""Menu screens: the interface is navigated by moving through menus."""

from __future__ import annotations

import html
import re
from pathlib import Path

import tornado.web

from ..repo import entities as entities_repo
from ..repo import menus as menus_repo
from .base import BaseHandler

MENU_KEYS = "123456789abcdfghijklmopqrstuvwxyz"  # no "e" and "n": used as shortcuts elsewhere
DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"


def numbered(items: list[dict]) -> list[dict]:
    for i, item in enumerate(items):
        item["key"] = MENU_KEYS[i] if i < len(MENU_KEYS) else ""
    return items


def visible_tree(menus: list[dict], entities, user: dict) -> tuple[set[int], list]:
    """Return ids of menus that contain something readable, and readable entities."""
    readable = [e for e in entities if e.can_read(user)]
    if user["role"] == "admin":
        return {m["id"] for m in menus}, readable
    used: set[int] = set()
    by_id = {m["id"]: m for m in menus}
    for ent in readable:
        mid = ent.menu_id
        seen: set[int] = set()
        while mid and mid in by_id and mid not in seen:
            seen.add(mid)
            used.add(mid)
            mid = by_id[mid]["parent_id"]
    return used, readable


class MenuHandler(BaseHandler):
    async def get(self, menu_id: str | None = None) -> None:
        def load(conn):
            return menus_repo.list_menus(conn), entities_repo.list_entities(conn)

        menus, entities = await self.db(load)
        mid = int(menu_id) if menu_id else None
        menu_ids = {m["id"] for m in menus}
        if mid is not None and mid not in menu_ids:
            raise tornado.web.HTTPError(404)
        visible, readable = visible_tree(menus, entities, self.user)
        # Entities whose menu was removed show up at the top level.
        items: list[dict] = []
        for m in menus:
            if m["parent_id"] == mid and m["id"] in visible:
                items.append({"label": m["title"], "url": f"/menu/{m['id']}", "submenu": True})
        for ent in readable:
            parent = ent.menu_id if ent.menu_id in menu_ids else None
            if parent == mid:
                hint = self.t("menu.sensor_hint") if ent.is_sensor else ""
                items.append({"label": ent.label, "url": f"/data/{ent.name}", "hint": hint})
        crumbs = self.crumbs(*[(m["title"], f"/menu/{m['id']}") for m in menus_repo.menu_path(menus, mid)])
        if mid is None:
            sep = bool(items)
            if self.is_admin():
                items.append({"label": self.t("menu.admin"), "url": "/admin", "submenu": True, "sep": sep})
                sep = False
            items.append({"label": self.t("menu.account"), "url": "/account", "sep": sep})
            items.append({"label": self.t("menu.help"), "url": "/help"})
            items.append({"label": self.t("menu.logout"), "url": "/logout"})
            title = self.cfg.get("company_name") or self.t("menu.main")
        else:
            title = crumbs[-1][0]
        empty = None
        if not readable and mid is None:
            empty = self.t("menu.no_entities_admin") if self.is_admin() else self.t("menu.no_entities")
        self.render("menu.html", title=title, items=numbered(items), crumbs=crumbs, empty=empty)


class AdminMenuHandler(BaseHandler):
    roles = ("admin",)

    def get(self) -> None:
        t = self.t
        items = [
            {"label": t("admin.entities"), "url": "/admin/entities", "hint": t("admin.entities_hint")},
            {"label": t("admin.menus"), "url": "/admin/menus", "hint": t("admin.menus_hint")},
            {"label": t("admin.users"), "url": "/admin/users", "hint": t("admin.users_hint")},
            {"label": t("admin.apikeys"), "url": "/admin/apikeys", "hint": t("admin.apikeys_hint")},
            {"label": t("admin.settings"), "url": "/admin/settings", "hint": t("admin.settings_hint")},
            {"label": t("admin.backup"), "url": "/admin/backup", "hint": t("admin.backup_hint"), "submenu": True},
            {"label": t("admin.audit"), "url": "/admin/audit", "hint": t("admin.audit_hint")},
            {"label": t("admin.system"), "url": "/admin/system", "hint": t("admin.system_hint")},
        ]
        self.render("menu.html", title=t("menu.admin"), items=numbered(items),
                    crumbs=self.crumbs((t("menu.admin"), "/admin")), empty=None)


class BackupMenuHandler(BaseHandler):
    roles = ("admin",)

    def get(self) -> None:
        t = self.t
        items = [
            {"label": t("backup.kind_config"), "url": "/admin/backup/config", "hint": t("backup.kind_config_hint")},
            {"label": t("backup.kind_schema"), "url": "/admin/backup/schema", "hint": t("backup.kind_schema_hint")},
            {"label": t("backup.kind_data"), "url": "/admin/backup/data", "hint": t("backup.kind_data_hint")},
            {"label": t("backup.kind_full"), "url": "/admin/backup/full", "hint": t("backup.kind_full_hint")},
            {"label": t("backup.restore"), "url": "/admin/restore", "hint": t("backup.restore_hint"), "sep": True},
        ]
        self.render("menu.html", title=t("admin.backup"), items=numbered(items),
                    crumbs=self.crumbs((t("menu.admin"), "/admin"), (t("admin.backup"), "/admin/backup")), empty=None)


# ---------------------------------------------------------------- help pages
_INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\[([^\]]+)\]\(([A-Za-z0-9_-]+)\.md\)"), r'<a href="/help/\2">\1</a>'),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|#[^)\s]*)\)"), r'<a href="\2">\1</a>'),
]


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    for pattern, repl in _INLINE:
        text = pattern.sub(repl, text)
    return text


def markdown_to_html(source: str) -> str:
    """Render the small Markdown subset used by the documentation."""
    out: list[str] = []
    lines = source.splitlines()
    i = 0
    in_list = None
    para: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            close_list()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
        elif stripped.startswith("|"):
            flush_para()
            close_list()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
                i += 1
            i -= 1
            table = ["<table class=\"grid\">"]
            for n, row in enumerate(rows):
                tag = "th" if n == 0 else "td"
                table.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in row) + "</tr>")
            table.append("</table>")
            out.append("".join(table))
        elif m := re.match(r"^(#{1,4})\s+(.*)$", stripped):
            flush_para()
            close_list()
            level = len(m.group(1))
            anchor = re.sub(r"[^a-z0-9]+", "-", m.group(2).lower()).strip("-")
            out.append(f'<h{level + 1} id="{anchor}">{_inline(m.group(2))}</h{level + 1}>')
        elif m := re.match(r"^([-*]|\d+\.)\s+(.*)$", stripped):
            flush_para()
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if in_list != kind:
                close_list()
                out.append(f"<{kind}>")
                in_list = kind
            out.append("<li>" + _inline(m.group(2)) + "</li>")
        elif not stripped:
            flush_para()
            close_list()
        else:
            close_list() if in_list and not line.startswith("  ") else None
            para.append(stripped)
        i += 1
    flush_para()
    close_list()
    return "\n".join(out)


class HelpHandler(BaseHandler):
    require_login = False

    def get(self, page: str | None = None) -> None:
        page = page or "README"
        if not re.match(r"^[A-Za-z0-9_-]+$", page):
            raise tornado.web.HTTPError(404)
        path = DOCS_DIR / self.loc.code / f"{page}.md"
        if not path.exists():
            raise tornado.web.HTTPError(404)
        body = markdown_to_html(path.read_text(encoding="utf-8"))
        pages = []
        for p in sorted((DOCS_DIR / self.loc.code).glob("*.md"), key=lambda p: (p.stem != "README", p.stem)):
            first = p.read_text(encoding="utf-8").split("\n", 1)[0]
            pages.append((p.stem, first.lstrip("# ").strip() or p.stem))
        crumbs = self.crumbs((self.t("menu.help"), "/help")) if self.user else []
        self.render("help.html", title=self.t("menu.help"), body=body, pages=pages, page=page, crumbs=crumbs)
