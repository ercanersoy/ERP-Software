"""Administration screens (administrators only)."""

from __future__ import annotations

import datetime as dt
import platform
import sys

import tornado
import tornado.escape
import tornado.web

from .. import __version__, backup, charsets
from ..db import DIALECTS
from ..db.database import server_version
from ..fieldtypes import CURRENCIES, FIELD_TYPES, Field, ValidationError
from ..i18n import LANGUAGES
from ..repo import apikeys as apikeys_repo
from ..repo import audit as audit_repo
from ..repo import entities as entities_repo
from ..repo import files as files_repo
from ..repo import menus as menus_repo
from ..repo import settings as settings_repo
from ..repo import users as users_repo
from .base import BaseHandler, FormField, page_window
from .data import send_download
from .setup import common_timezones


class AdminHandler(BaseHandler):
    roles = ("admin",)

    def admin_crumbs(self, *items):
        return self.crumbs((self.t("menu.admin"), "/admin"), *items)

    def yes_no(self, value) -> str:
        return self.loc.boolean(bool(value))

    def err(self, errors: dict, key: str) -> str:
        if key not in errors:
            return ""
        e = errors[key]
        return self.t(e.key, **e.params) if isinstance(e, ValidationError) else self.t(e)


# ====================================================================== entities
class EntityListHandler(AdminHandler):
    async def get(self) -> None:
        def load(conn):
            return entities_repo.list_entities(conn), {m["id"]: m for m in menus_repo.list_menus(conn)}

        entities, menus = await self.db(load)
        rows = []
        for e in entities:
            menu = menus.get(e.menu_id)
            rows.append({"url": f"/admin/entities/{e.name}", "cells": [
                {"text": e.name}, {"text": e.label}, {"text": str(len(e.fields))},
                {"text": menu["title"] if menu else "—"}, {"text": self.yes_no(e.is_sensor)},
                {"text": self.t(f"perm.{e.perm_user}")}, {"text": self.t(f"perm.{e.perm_dealer}")},
            ]})
        t = self.t
        columns = [{"label": t("entities.name")}, {"label": t("entities.label")}, {"label": t("entities.fields"), "num": True},
                   {"label": t("entities.menu")}, {"label": t("entities.is_sensor")},
                   {"label": t("entities.perm_user")}, {"label": t("entities.perm_dealer")}]
        self.render("list.html", title=t("admin.entities"), crumbs=self.admin_crumbs((t("admin.entities"), "/admin/entities")),
                    columns=columns, rows=rows, search=False, q="", page=1, pages=1, total=len(rows),
                    actions=[{"label": t("entities.new"), "url": "/admin/entities/new", "key": "n", "attr": "data-new"}],
                    empty=t("entities.none"), notice=None, description=t("entities.intro"))


class EntityDetailHandler(AdminHandler):
    async def get(self, name: str) -> None:
        ent = await self.db(entities_repo.get_entity, name)
        if ent is None:
            raise tornado.web.HTTPError(404)
        t = self.t
        rows = [{"url": f"/admin/entities/{ent.name}/fields/{f.name}", "cells": [
            {"text": str(f.sort_order)}, {"text": f.name}, {"text": f.label}, {"text": t(f"type.{f.field_type}")},
            {"text": self.yes_no(f.required)}, {"text": self.yes_no(f.is_unique)}, {"text": self.yes_no(f.show_in_list)},
        ]} for f in ent.fields]
        columns = [{"label": t("fields.sort_order"), "num": True}, {"label": t("fields.name")}, {"label": t("fields.label")},
                   {"label": t("fields.type")}, {"label": t("fields.required")}, {"label": t("fields.is_unique")},
                   {"label": t("fields.show_in_list")}]
        actions = [
            {"label": t("fields.new"), "url": f"/admin/entities/{ent.name}/fields/new", "key": "n", "attr": "data-new"},
            {"label": t("entities.edit"), "url": f"/admin/entities/{ent.name}/edit", "key": "e", "attr": "data-edit"},
            {"label": t("entities.open_data"), "url": f"/data/{ent.name}", "key": "d"},
            {"label": t("entities.delete"), "url": f"/admin/entities/{ent.name}/delete", "key": "Del", "attr": "data-delete"},
        ]
        self.render("list.html", title=f"{ent.label} ({ent.name})",
                    crumbs=self.admin_crumbs((t("admin.entities"), "/admin/entities"), (ent.label, f"/admin/entities/{ent.name}")),
                    columns=columns, rows=rows, search=False, q="", page=1, pages=1, total=len(rows), actions=actions,
                    empty=t("fields.none"), notice=None, description=ent.description)


class EntityFormHandler(AdminHandler):
    async def context(self, name: str | None):
        def load(conn):
            ent = entities_repo.get_entity(conn, name) if name else None
            return ent, menus_repo.list_menus(conn)

        ent, menus = await self.db(load)
        if name and ent is None:
            raise tornado.web.HTTPError(404)
        return ent, menus

    def fields(self, ent, menus, values: dict, errors: dict) -> list[FormField]:
        t = self.t
        is_new = ent is None
        v = lambda k, d="": values.get(k, d)  # noqa: E731
        menu_options = [("", "— " + t("menu.main") + " —")] + [
            (str(m["id"]), " › ".join(x["title"] for x in menus_repo.menu_path(menus, m["id"]))) for m in menus]
        out = []
        if is_new:
            out.append(FormField("name", t("entities.name"), "text", v("name"), required=True, help=t("entities.name_help"),
                                 error=self.err(errors, "name"), attrs={"pattern": "[a-z][a-z0-9_]{0,49}", "maxlength": "50"}))
        else:
            out.append(FormField("name", t("entities.name"), "static", ent.name))
        out += [
            FormField("label", t("entities.label"), "text", v("label"), required=True, error=self.err(errors, "label")),
            FormField("description", t("entities.description"), "textarea", v("description")),
            FormField("menu_id", t("entities.menu"), "select", v("menu_id"), options=menu_options),
            FormField("sort_order", t("entities.sort_order"), "number", v("sort_order", "0")),
            FormField("perm_user", t("entities.perm_user"), "select", v("perm_user", "write"),
                      options=[(p, t(f"perm.{p}")) for p in entities_repo.PERM_USER]),
            FormField("perm_dealer", t("entities.perm_dealer"), "select", v("perm_dealer", "none"),
                      options=[(p, t(f"perm.{p}")) for p in entities_repo.PERM_DEALER], help=t("entities.perm_dealer_help")),
        ]
        if not is_new:
            out.append(FormField("title_field", t("entities.title_field"), "select", v("title_field"),
                                 options=[("", "—")] + [(f.name, f.label) for f in ent.fields], help=t("entities.title_field_help")))
        out += [
            FormField("is_sensor", t("entities.is_sensor"), "checkbox", v("is_sensor", False), help=t("entities.is_sensor_help")),
            FormField("read_interval_ms", t("entities.read_interval_ms"), "number", v("read_interval_ms", "5000"),
                      help=t("entities.read_interval_help"), error=self.err(errors, "read_interval_ms"),
                      attrs={"min": "100", "max": "86400000"}),
            FormField("page_size", t("entities.page_size"), "number", v("page_size"), help=t("entities.page_size_help"),
                      error=self.err(errors, "page_size"), attrs={"min": "5", "max": "500"}),
        ]
        return out

    def show(self, ent, menus, values, errors, error=None) -> None:
        t = self.t
        if ent is None:
            crumbs = self.admin_crumbs((t("admin.entities"), "/admin/entities"), (t("entities.new"), "/admin/entities/new"))
            title = t("entities.new")
        else:
            crumbs = self.admin_crumbs((t("admin.entities"), "/admin/entities"), (ent.label, f"/admin/entities/{ent.name}"),
                                       (t("entities.edit"), f"/admin/entities/{ent.name}/edit"))
            title = t("entities.edit")
        self.form_page(title, self.fields(ent, menus, values, errors), crumbs, error=error)

    async def get(self, name: str | None = None) -> None:
        ent, menus = await self.context(name)
        values = {}
        if ent is not None:
            values = {k: ("" if v is None else str(v)) for k, v in ent.as_dict(with_fields=False).items()}
            values["is_sensor"] = ent.is_sensor
        self.show(ent, menus, values, {})

    async def post(self, name: str | None = None) -> None:
        ent, menus = await self.context(name)
        keys = ("name", "label", "description", "menu_id", "sort_order", "perm_user", "perm_dealer", "title_field",
                "read_interval_ms", "page_size")
        values = {k: self.get_argument(k, "").strip() for k in keys}
        values["is_sensor"] = self.bool_arg("is_sensor")
        menu_ids = {m["id"] for m in menus}

        def to_int(text, default=None):
            try:
                return int(text)
            except (TypeError, ValueError):
                return default

        target = entities_repo.Entity(
            id=ent.id if ent else None,
            name=ent.name if ent else values["name"].lower(),
            label=values["label"],
            description=values["description"],
            menu_id=to_int(values["menu_id"]) if to_int(values["menu_id"]) in menu_ids else None,
            sort_order=to_int(values["sort_order"], 0),
            perm_user=values["perm_user"],
            perm_dealer=values["perm_dealer"],
            title_field=values["title_field"] or None if ent else None,
            is_sensor=values["is_sensor"],
            read_interval_ms=to_int(values["read_interval_ms"], 0),
            page_size=to_int(values["page_size"]),
        )
        errors = entities_repo.validate_entity(target, is_new=ent is None)
        if errors:
            return self.show(ent, menus, values, errors, self.t("error.form"))
        try:
            if ent is None:
                await self.db(entities_repo.create_entity, target)
                await self.audit("entity_create", target.name)
            else:
                target.fields = ent.fields
                await self.db(entities_repo.update_entity, target)
                await self.audit("entity_update", target.name)
        except ValidationError as exc:
            return self.show(ent, menus, values, {"name": exc}, self.t(exc.key, **exc.params))
        self.flash(self.t("common.saved"))
        self.redirect(f"/admin/entities/{target.name}")


class EntityDeleteHandler(AdminHandler):
    async def get(self, name: str) -> None:
        ent = await self.db(entities_repo.get_entity, name)
        if ent is None:
            raise tornado.web.HTTPError(404)
        t = self.t
        self.render("confirm.html", title=t("entities.delete"), message=t("entities.delete_confirm", name=ent.name),
                    action=self.request.path, button=t("common.delete"), danger=True, confirm_input=ent.name,
                    crumbs=self.admin_crumbs((t("admin.entities"), "/admin/entities"), (ent.label, f"/admin/entities/{ent.name}"),
                                             (t("common.delete"), self.request.path)))

    async def post(self, name: str) -> None:
        ent = await self.db(entities_repo.get_entity, name)
        if ent is None:
            raise tornado.web.HTTPError(404)
        if self.get_argument("confirm", "") != ent.name:
            self.flash(self.t("error.confirm_mismatch"), "error")
            self.redirect(self.request.path)
            return
        removed = await self.db(entities_repo.delete_entity, ent)
        files_repo.remove_from_disk(self.state.config.upload_dir, removed)
        await self.audit("entity_delete", ent.name)
        self.flash(self.t("entities.deleted"))
        self.redirect("/admin/entities")


# ====================================================================== fields
class FieldFormHandler(AdminHandler):
    async def context(self, name: str, fname: str | None):
        def load(conn):
            return entities_repo.get_entity(conn, name), entities_repo.list_entities(conn)

        ent, all_entities = await self.db(load)
        if ent is None:
            raise tornado.web.HTTPError(404)
        f = ent.field(fname) if fname else None
        if fname and f is None:
            raise tornado.web.HTTPError(404)
        return ent, f, all_entities

    def fields(self, ent, f, all_entities, values, errors) -> list[FormField]:
        t = self.t
        is_new = f is None
        v = lambda k, d="": values.get(k, d)  # noqa: E731
        out = []
        if is_new:
            out += [
                FormField("name", t("fields.name"), "text", v("name"), required=True, help=t("fields.name_help"),
                          error=self.err(errors, "name"), attrs={"pattern": "[a-z][a-z0-9_]{0,49}", "maxlength": "50"}),
                FormField("label", t("fields.label"), "text", v("label"), required=True, error=self.err(errors, "label")),
                FormField("field_type", t("fields.type"), "select", v("field_type", "text"),
                          options=[(k, t(f"type.{k}")) for k in FIELD_TYPES], help=t("fields.type_help")),
                FormField("max_length", t("fields.max_length"), "number", v("max_length", "255"),
                          help=t("fields.max_length_help"), attrs={"min": "1", "max": "4000"}),
                FormField("decimal_places", t("fields.decimal_places"), "number", v("decimal_places"),
                          help=t("fields.decimal_places_help"), attrs={"min": "0", "max": "8"}),
                FormField("ref_entity", t("fields.ref_entity"), "select", v("ref_entity"),
                          options=[("", "—")] + [(e.name, e.label) for e in all_entities], help=t("fields.ref_entity_help")),
            ]
        else:
            out += [
                FormField("name", t("fields.name"), "static", f.name),
                FormField("label", t("fields.label"), "text", v("label"), required=True, error=self.err(errors, "label")),
                FormField("field_type", t("fields.type"), "static", t(f"type.{f.field_type}")),
            ]
            if f.field_type == "text":
                out.append(FormField("max_length", t("fields.max_length"), "static", str(f.max_length or 255)))
            if f.field_type in ("decimal", "currency"):
                out.append(FormField("decimal_places", t("fields.decimal_places"), "static", str(f.scale)))
            if f.field_type == "reference":
                out.append(FormField("ref_entity", t("fields.ref_entity"), "static", f.ref_entity or ""))
        if is_new or f.field_type == "currency":
            out.append(FormField("currency", t("fields.currency"), "select",
                                 v("currency", self.cfg.get("default_currency", "TRY")),
                                 options=[(c, c) for c in CURRENCIES], help=t("fields.currency_help")))
        if is_new or f.field_type == "choice":
            out.append(FormField("options", t("fields.options"), "textarea", v("options"), help=t("fields.options_help"),
                                 error=self.err(errors, "options")))
        out += [
            FormField("required", t("fields.required"), "checkbox", v("required", False)),
            FormField("is_unique", t("fields.is_unique"), "checkbox", v("is_unique", False)),
            FormField("show_in_list", t("fields.show_in_list"), "checkbox", v("show_in_list", True)),
            FormField("default_value", t("fields.default_value"), "text", v("default_value"),
                      help=t("fields.default_value_help"), error=self.err(errors, "default_value")),
            FormField("help_text", t("fields.help_text"), "text", v("help_text"), attrs={"maxlength": "500"}),
            FormField("sort_order", t("fields.sort_order"), "number", v("sort_order", "")),
        ]
        return out

    def show(self, ent, f, all_entities, values, errors, error=None) -> None:
        t = self.t
        base = self.admin_crumbs((t("admin.entities"), "/admin/entities"), (ent.label, f"/admin/entities/{ent.name}"))
        if f is None:
            crumbs = base + [(t("fields.new"), f"/admin/entities/{ent.name}/fields/new")]
            title = t("fields.new")
        else:
            crumbs = base + [(f.label, f"/admin/entities/{ent.name}/fields/{f.name}")]
            title = t("fields.edit")
        extra = ""
        if f is not None:
            extra = f'<p><a href="/admin/entities/{ent.name}/fields/{f.name}/delete" data-delete>{tornado.escape.xhtml_escape(t("fields.delete"))}</a></p>'
        self.form_page(title, self.fields(ent, f, all_entities, values, errors), crumbs, error=error, extra=extra)

    async def get(self, name: str, fname: str | None = None) -> None:
        ent, f, all_entities = await self.context(name, fname)
        values = {}
        if f is not None:
            values = {k: ("" if val is None else val) for k, val in f.as_dict().items()}
        self.show(ent, f, all_entities, values, {})

    async def post(self, name: str, fname: str | None = None) -> None:
        ent, f, all_entities = await self.context(name, fname)
        keys = ("name", "label", "field_type", "max_length", "decimal_places", "ref_entity", "currency", "options",
                "default_value", "help_text", "sort_order")
        values = {k: self.get_argument(k, "").strip() for k in keys}
        for k in ("required", "is_unique", "show_in_list"):
            values[k] = self.bool_arg(k)

        def to_int(text):
            try:
                return int(text)
            except (TypeError, ValueError):
                return None

        if f is None:
            ftype = values["field_type"] if values["field_type"] in FIELD_TYPES else "text"
            target = Field(None, ent.id, values["name"].lower(), values["label"], ftype,
                           max_length=to_int(values["max_length"]) if ftype == "text" else None,
                           decimal_places=to_int(values["decimal_places"]) if ftype in ("decimal", "currency") else None,
                           ref_entity=values["ref_entity"] or None if ftype == "reference" else None)
        else:
            target = Field(f.id, ent.id, f.name, values["label"], f.field_type, max_length=f.max_length,
                           decimal_places=f.decimal_places, ref_entity=f.ref_entity)
        target.label = values["label"]
        target.currency = values["currency"] or None
        target.options = "\n".join(line.strip() for line in values["options"].splitlines() if line.strip()) or (
            f.options if f is not None and target.field_type != "choice" else None)
        target.required = values["required"]
        target.is_unique = values["is_unique"]
        target.show_in_list = values["show_in_list"]
        target.default_value = values["default_value"] or None
        target.help_text = values["help_text"] or None
        target.sort_order = to_int(values["sort_order"]) or (f.sort_order if f else 0)
        try:
            if f is None:
                await self.db(entities_repo.add_field, ent, target)
                await self.audit("field_create", f"{ent.name}.{target.name}", target.field_type)
            else:
                await self.db(entities_repo.update_field, ent, target)
                await self.audit("field_update", f"{ent.name}.{target.name}")
        except ValidationError as exc:
            key = {"error.invalid_identifier": "name", "error.duplicate_name": "name", "error.required": "label",
                   "error.options_required": "options", "error.reference_required": "ref_entity",
                   "error.invalid_length": "max_length", "error.invalid_value": "name"}.get(exc.key, "default_value")
            return self.show(ent, f, all_entities, values, {key: exc}, self.t(exc.key, **exc.params))
        self.flash(self.t("common.saved"))
        self.redirect(f"/admin/entities/{ent.name}")


class FieldDeleteHandler(AdminHandler):
    async def context(self, name, fname):
        ent = await self.db(entities_repo.get_entity, name)
        f = ent.field(fname) if ent else None
        if f is None:
            raise tornado.web.HTTPError(404)
        return ent, f

    async def get(self, name: str, fname: str) -> None:
        ent, f = await self.context(name, fname)
        t = self.t
        self.render("confirm.html", title=t("fields.delete"), message=t("fields.delete_confirm", name=f.name, entity=ent.label),
                    action=self.request.path, button=t("common.delete"), danger=True, confirm_input=f.name,
                    crumbs=self.admin_crumbs((t("admin.entities"), "/admin/entities"), (ent.label, f"/admin/entities/{ent.name}"),
                                             (f.label, f"/admin/entities/{ent.name}/fields/{f.name}"), (t("common.delete"), self.request.path)))

    async def post(self, name: str, fname: str) -> None:
        ent, f = await self.context(name, fname)
        if self.get_argument("confirm", "") != f.name:
            self.flash(self.t("error.confirm_mismatch"), "error")
            self.redirect(self.request.path)
            return
        removed = await self.db(entities_repo.delete_field, ent, f)
        files_repo.remove_from_disk(self.state.config.upload_dir, removed)
        await self.audit("field_delete", f"{ent.name}.{f.name}")
        self.flash(self.t("fields.deleted"))
        self.redirect(f"/admin/entities/{ent.name}")


# ====================================================================== menus
class MenuListHandler(AdminHandler):
    async def get(self) -> None:
        menus = await self.db(menus_repo.list_menus)
        rows = []
        for m in sorted(menus, key=lambda m: [(x["sort_order"] or 0, x["title"]) for x in menus_repo.menu_path(menus, m["id"])]):
            path = menus_repo.menu_path(menus, m["id"])
            rows.append({"url": f"/admin/menus/{m['id']}", "cells": [
                {"text": " › ".join(x["title"] for x in path)}, {"text": str(m["sort_order"] or 0)}]})
        t = self.t
        self.render("list.html", title=t("admin.menus"), crumbs=self.admin_crumbs((t("admin.menus"), "/admin/menus")),
                    columns=[{"label": t("menus.title")}, {"label": t("menus.sort_order"), "num": True}], rows=rows,
                    search=False, q="", page=1, pages=1, total=len(rows), empty=t("menus.none"), notice=None,
                    actions=[{"label": t("menus.new"), "url": "/admin/menus/new", "key": "n", "attr": "data-new"}],
                    description=t("menus.intro"))


class MenuFormHandler(AdminHandler):
    async def context(self, menu_id):
        menus = await self.db(menus_repo.list_menus)
        menu = None
        if menu_id:
            menu = next((m for m in menus if m["id"] == int(menu_id)), None)
            if menu is None:
                raise tornado.web.HTTPError(404)
        return menu, menus

    def show(self, menu, menus, values, error=None):
        t = self.t
        excluded = set()
        if menu:
            excluded = menus_repo.descendants(menus, menu["id"]) | {menu["id"]}
        options = [("", "— " + t("menu.main") + " —")] + [
            (str(m["id"]), " › ".join(x["title"] for x in menus_repo.menu_path(menus, m["id"])))
            for m in menus if m["id"] not in excluded]
        fields = [
            FormField("title", t("menus.title"), "text", values.get("title", ""), required=True,
                      error=t("error.required") if error else ""),
            FormField("parent_id", t("menus.parent"), "select", values.get("parent_id", ""), options=options),
            FormField("sort_order", t("menus.sort_order"), "number", values.get("sort_order", "0")),
        ]
        url = f"/admin/menus/{menu['id']}" if menu else "/admin/menus/new"
        extra = ""
        if menu:
            extra = f'<p><a href="/admin/menus/{menu["id"]}/delete" data-delete>{tornado.escape.xhtml_escape(t("menus.delete"))}</a></p>'
        self.form_page(t("menus.edit") if menu else t("menus.new"), fields,
                       self.admin_crumbs((t("admin.menus"), "/admin/menus"), (menu["title"] if menu else t("menus.new"), url)),
                       error=error, extra=extra)

    async def get(self, menu_id: str | None = None) -> None:
        menu, menus = await self.context(menu_id)
        values = {"title": menu["title"], "parent_id": str(menu["parent_id"] or ""),
                  "sort_order": str(menu["sort_order"] or 0)} if menu else {}
        self.show(menu, menus, values)

    async def post(self, menu_id: str | None = None) -> None:
        menu, menus = await self.context(menu_id)
        values = {k: self.get_argument(k, "").strip() for k in ("title", "parent_id", "sort_order")}
        if not values["title"]:
            return self.show(menu, menus, values, self.t("error.form"))
        allowed = {m["id"] for m in menus}
        if menu:
            allowed -= menus_repo.descendants(menus, menu["id"]) | {menu["id"]}
        parent = int(values["parent_id"]) if values["parent_id"].isdigit() and int(values["parent_id"]) in allowed else None
        try:
            order = int(values["sort_order"] or 0)
        except ValueError:
            order = 0
        new_id = await self.db(menus_repo.save_menu, menu["id"] if menu else None, values["title"][:200], parent, order)
        await self.audit("menu_save", values["title"], str(new_id))
        self.flash(self.t("common.saved"))
        self.redirect("/admin/menus")


class MenuDeleteHandler(AdminHandler):
    async def get(self, menu_id: str) -> None:
        menu = await self.db(menus_repo.get_menu, int(menu_id))
        if menu is None:
            raise tornado.web.HTTPError(404)
        t = self.t
        self.render("confirm.html", title=t("menus.delete"), message=t("menus.delete_confirm", title=menu["title"]),
                    action=self.request.path, button=t("common.delete"), danger=True,
                    crumbs=self.admin_crumbs((t("admin.menus"), "/admin/menus"), (menu["title"], f"/admin/menus/{menu['id']}"),
                                             (t("common.delete"), self.request.path)))

    async def post(self, menu_id: str) -> None:
        await self.db(menus_repo.delete_menu, int(menu_id))
        await self.audit("menu_delete", menu_id)
        self.flash(self.t("menus.deleted"))
        self.redirect("/admin/menus")


# ====================================================================== users
class UserListHandler(AdminHandler):
    async def get(self) -> None:
        users = await self.db(users_repo.list_users)
        t = self.t
        rows = [{"url": f"/admin/users/{u['id']}", "cells": [
            {"text": u["username"]}, {"text": u.get("full_name") or ""}, {"text": t(f"role.{u['role']}")},
            {"text": self.yes_no(u["active"])}, {"text": self.loc.datetime(u.get("last_login_at"))}]} for u in users]
        columns = [{"label": t("users.username")}, {"label": t("users.full_name")}, {"label": t("users.role")},
                   {"label": t("users.active")}, {"label": t("users.last_login")}]
        self.render("list.html", title=t("admin.users"), crumbs=self.admin_crumbs((t("admin.users"), "/admin/users")),
                    columns=columns, rows=rows, search=False, q="", page=1, pages=1, total=len(rows), empty=t("common.no_rows"),
                    notice=None, description=t("users.intro"),
                    actions=[{"label": t("users.new"), "url": "/admin/users/new", "key": "n", "attr": "data-new"}])


class UserFormHandler(AdminHandler):
    async def context(self, user_id):
        if not user_id:
            return None
        u = await self.db(users_repo.get_user, int(user_id))
        if u is None:
            raise tornado.web.HTTPError(404)
        return u

    def show(self, target, values, errors, error=None):
        t = self.t
        v = lambda k, d="": values.get(k, d)  # noqa: E731
        e = lambda k: t(errors[k]) if k in errors else ""  # noqa: E731
        fields = []
        if target is None:
            fields.append(FormField("username", t("users.username"), "text", v("username"), required=True,
                                    error=e("username"), help=t("users.username_help")))
        else:
            fields.append(FormField("username", t("users.username"), "static", target["username"]))
        fields += [
            FormField("full_name", t("users.full_name"), "text", v("full_name")),
            FormField("email", t("users.email"), "email", v("email")),
            FormField("role", t("users.role"), "select", v("role", "user"), error=e("role"),
                      options=[(r, t(f"role.{r}")) for r in users_repo.ROLES], help=t("users.role_help")),
            FormField("language", t("account.language"), "select", v("language"),
                      options=[("", "—")] + list(LANGUAGES.items())),
            FormField("active", t("users.active"), "checkbox", v("active", True), error=e("active")),
            FormField("password", t("users.password") if target is None else t("users.new_password"), "password", "",
                      required=target is None, error=e("password"),
                      help=t("users.password_help") if target is None else t("users.reset_password_help"),
                      attrs={"autocomplete": "new-password"}),
        ]
        url = f"/admin/users/{target['id']}" if target else "/admin/users/new"
        extra = ""
        if target and target["id"] != self.user["id"]:
            extra = f'<p><a href="/admin/users/{target["id"]}/delete" data-delete>{tornado.escape.xhtml_escape(t("users.delete"))}</a></p>'
        self.form_page(t("users.edit") if target else t("users.new"), fields,
                       self.admin_crumbs((t("admin.users"), "/admin/users"), (target["username"] if target else t("users.new"), url)),
                       error=error, extra=extra)

    async def get(self, user_id: str | None = None) -> None:
        target = await self.context(user_id)
        values = {}
        if target:
            values = {k: target.get(k) or "" for k in ("full_name", "email", "role", "language")}
            values["active"] = target["active"]
        self.show(target, values, {})

    async def post(self, user_id: str | None = None) -> None:
        target = await self.context(user_id)
        values = {k: self.get_argument(k, "").strip() for k in ("username", "full_name", "email", "role", "language")}
        values["active"] = self.bool_arg("active")
        password = self.get_argument("password", "")
        errors = {}
        if values["role"] not in users_repo.ROLES:
            errors["role"] = "error.invalid_value"
        if target is None:
            username = users_repo.normalize_username(values["username"])
            if not users_repo.valid_username(username):
                errors["username"] = "error.invalid_username"
            elif await self.db(users_repo.get_user_by_name, username):
                errors["username"] = "error.duplicate_name"
        if (target is None or password) and len(password) < users_repo.MIN_PASSWORD_LENGTH:
            errors["password"] = "error.password_too_short"
        if target is not None and target["role"] == "admin" and target["active"] and (
                values["role"] != "admin" or not values["active"]):
            if await self.db(users_repo.count_active_admins) <= 1:
                errors["role"] = "error.last_admin"
        if errors:
            return self.show(target, values, errors, self.t("error.form"))
        lang = values["language"] if values["language"] in LANGUAGES else ""
        if target is None:
            new_id = await self.db(users_repo.create_user, values["username"], password, values["role"],
                                   values["full_name"][:200], values["email"][:200], lang, values["active"])
            await self.audit("user_create", values["username"], values["role"])
        else:
            new_id = target["id"]
            await self.db(users_repo.update_user, target["id"], {
                "full_name": values["full_name"][:200], "email": values["email"][:200], "role": values["role"],
                "language": lang, "active": values["active"]})
            if not values["active"]:
                await self.db(lambda conn: conn.delete("erp_sessions", {"user_id": target["id"]}))
            if password:
                await self.db(users_repo.set_password, target["id"], password)
            await self.audit("user_update", target["username"], values["role"])
        self.flash(self.t("common.saved"))
        self.redirect(f"/admin/users/{new_id}")


class UserDeleteHandler(AdminHandler):
    async def context(self, user_id):
        u = await self.db(users_repo.get_user, int(user_id))
        if u is None:
            raise tornado.web.HTTPError(404)
        if u["id"] == self.user["id"]:
            raise tornado.web.HTTPError(403)
        return u

    async def get(self, user_id: str) -> None:
        u = await self.context(user_id)
        t = self.t
        self.render("confirm.html", title=t("users.delete"), message=t("users.delete_confirm", username=u["username"]),
                    action=self.request.path, button=t("common.delete"), danger=True,
                    crumbs=self.admin_crumbs((t("admin.users"), "/admin/users"), (u["username"], f"/admin/users/{u['id']}"),
                                             (t("common.delete"), self.request.path)))

    async def post(self, user_id: str) -> None:
        u = await self.context(user_id)
        if u["role"] == "admin" and u["active"] and await self.db(users_repo.count_active_admins) <= 1:
            self.flash(self.t("error.last_admin"), "error")
            self.redirect("/admin/users")
            return
        await self.db(users_repo.delete_user, u["id"])
        await self.audit("user_delete", u["username"])
        self.flash(self.t("users.deleted"))
        self.redirect("/admin/users")


# ====================================================================== API keys
class ApiKeyListHandler(AdminHandler):
    async def get(self) -> None:
        keys = await self.db(apikeys_repo.list_keys)
        t = self.t
        rows = [{"url": f"/admin/apikeys/{k['id']}", "cells": [
            {"text": k["name"]}, {"text": f"erp_{k['token_prefix']}_…"},
            {"text": ", ".join(p for p, ok in ((t("apikeys.read"), k["can_read"]), (t("apikeys.write"), k["can_write"])) if ok)},
            {"text": ", ".join(k["entity_list"]) or t("apikeys.all_entities")},
            {"text": self.yes_no(k["active"])}, {"text": self.loc.datetime(k.get("last_used_at"))}]} for k in keys]
        columns = [{"label": t("apikeys.name")}, {"label": t("apikeys.prefix")}, {"label": t("apikeys.permissions")},
                   {"label": t("apikeys.entities")}, {"label": t("users.active")}, {"label": t("apikeys.last_used")}]
        self.render("list.html", title=t("admin.apikeys"), crumbs=self.admin_crumbs((t("admin.apikeys"), "/admin/apikeys")),
                    columns=columns, rows=rows, search=False, q="", page=1, pages=1, total=len(rows), empty=t("common.no_rows"),
                    notice=None if self.cfg.get("api_enabled", "1") == "1" else t("apikeys.api_disabled"),
                    description=t("apikeys.intro"),
                    actions=[{"label": t("apikeys.new"), "url": "/admin/apikeys/new", "key": "n", "attr": "data-new"},
                             {"label": t("apikeys.docs"), "url": "/help/API", "key": "h"}])


class ApiKeyFormHandler(AdminHandler):
    async def context(self, key_id):
        entities = await self.db(entities_repo.list_entities)
        key = None
        if key_id:
            key = await self.db(apikeys_repo.get_key, int(key_id))
            if key is None:
                raise tornado.web.HTTPError(404)
        return key, entities

    def show(self, key, entities, values, errors, error=None):
        t = self.t
        v = lambda k, d="": values.get(k, d)  # noqa: E731
        e = lambda k: t(errors[k]) if k in errors else ""  # noqa: E731
        fields = [
            FormField("name", t("apikeys.name"), "text", v("name"), required=True, error=e("name"), help=t("apikeys.name_help")),
            FormField("entities", t("apikeys.entities"), "checkboxes", v("entities", []),
                      options=[(x.name, f"{x.label} ({x.name})") for x in entities], help=t("apikeys.entities_help")),
            FormField("can_read", t("apikeys.can_read"), "checkbox", v("can_read", True)),
            FormField("can_write", t("apikeys.can_write"), "checkbox", v("can_write", True)),
            FormField("allowed_ips", t("apikeys.allowed_ips"), "textarea", v("allowed_ips"), help=t("apikeys.allowed_ips_help"),
                      error=e("allowed_ips")),
            FormField("min_interval_ms", t("apikeys.min_interval_ms"), "number", v("min_interval_ms", "0"),
                      help=t("apikeys.min_interval_help"), attrs={"min": "0", "max": "86400000"}),
            FormField("expires_at", t("apikeys.expires_at"), "date", v("expires_at"), help=t("apikeys.expires_help")),
            FormField("active", t("users.active"), "checkbox", v("active", True)),
        ]
        url = f"/admin/apikeys/{key['id']}" if key else "/admin/apikeys/new"
        extra = ""
        if key:
            extra = f'<p><a href="/admin/apikeys/{key["id"]}/delete" data-delete>{tornado.escape.xhtml_escape(t("apikeys.delete"))}</a></p>'
        self.form_page(t("apikeys.edit") if key else t("apikeys.new"), fields,
                       self.admin_crumbs((t("admin.apikeys"), "/admin/apikeys"), (key["name"] if key else t("apikeys.new"), url)),
                       error=error, extra=extra)

    async def get(self, key_id: str | None = None) -> None:
        key, entities = await self.context(key_id)
        values = {}
        if key:
            values = {"name": key["name"], "entities": key["entity_list"], "can_read": key["can_read"],
                      "can_write": key["can_write"], "allowed_ips": key.get("allowed_ips") or "",
                      "min_interval_ms": str(key["min_interval_ms"]), "active": key["active"],
                      "expires_at": key["expires_at"].date().isoformat() if key.get("expires_at") else ""}
        self.show(key, entities, values, {})

    async def post(self, key_id: str | None = None) -> None:
        key, entities = await self.context(key_id)
        known = {e.name for e in entities}
        values = {
            "name": self.get_argument("name", "").strip()[:100],
            "entities": [x for x in self.get_arguments("entities") if x in known],
            "can_read": self.bool_arg("can_read"),
            "can_write": self.bool_arg("can_write"),
            "allowed_ips": self.get_argument("allowed_ips", "").strip(),
            "min_interval_ms": self.get_argument("min_interval_ms", "0").strip(),
            "expires_at": self.get_argument("expires_at", "").strip(),
            "active": self.bool_arg("active"),
        }
        errors = {}
        if not values["name"]:
            errors["name"] = "error.required"
        import ipaddress

        for net in values["allowed_ips"].replace(",", "\n").splitlines():
            if net.strip():
                try:
                    ipaddress.ip_network(net.strip(), strict=False)
                except ValueError:
                    errors["allowed_ips"] = "error.invalid_network"
        try:
            interval = max(0, min(86_400_000, int(values["min_interval_ms"] or 0)))
        except ValueError:
            interval = 0
        expires = None
        if values["expires_at"]:
            try:
                expires = dt.datetime.combine(dt.date.fromisoformat(values["expires_at"]), dt.time(23, 59, 59))
            except ValueError:
                expires = None
        if errors:
            return self.show(key, entities, values, errors, self.t("error.form"))
        if key is None:
            new_id, token = await self.db(apikeys_repo.create_key, values["name"], values["entities"], values["can_read"],
                                          values["can_write"], values["allowed_ips"], interval, expires, self.user["id"])
            await self.audit("apikey_create", values["name"])
            t = self.t
            self.message_page(t("apikeys.created"), t("apikeys.token_once"),
                              self.admin_crumbs((t("admin.apikeys"), "/admin/apikeys"), (values["name"], f"/admin/apikeys/{new_id}")),
                              code=token, links=[(t("admin.apikeys"), "/admin/apikeys"), (t("apikeys.docs"), "/help/API")])
            return
        await self.db(apikeys_repo.update_key, key["id"], {
            "name": values["name"], "entities": values["entities"], "can_read": values["can_read"],
            "can_write": values["can_write"], "allowed_ips": values["allowed_ips"], "min_interval_ms": interval,
            "expires_at": expires, "active": values["active"]})
        await self.audit("apikey_update", values["name"])
        self.flash(self.t("common.saved"))
        self.redirect("/admin/apikeys")


class ApiKeyDeleteHandler(AdminHandler):
    async def get(self, key_id: str) -> None:
        key = await self.db(apikeys_repo.get_key, int(key_id))
        if key is None:
            raise tornado.web.HTTPError(404)
        t = self.t
        self.render("confirm.html", title=t("apikeys.delete"), message=t("apikeys.delete_confirm", name=key["name"]),
                    action=self.request.path, button=t("common.delete"), danger=True,
                    crumbs=self.admin_crumbs((t("admin.apikeys"), "/admin/apikeys"), (key["name"], f"/admin/apikeys/{key['id']}"),
                                             (t("common.delete"), self.request.path)))

    async def post(self, key_id: str) -> None:
        await self.db(apikeys_repo.delete_key, int(key_id))
        await self.audit("apikey_delete", key_id)
        self.flash(self.t("apikeys.deleted"))
        self.redirect("/admin/apikeys")


# ====================================================================== settings
class SettingsHandler(AdminHandler):
    KEYS = ("company_name", "default_language", "default_charset", "timezone", "default_currency", "page_size",
            "session_hours", "api_enabled")

    def show(self, values, errors=None, error=None):
        t = self.t
        v = lambda k: values.get(k, self.cfg.get(k, ""))  # noqa: E731
        e = lambda k: t((errors or {})[k]) if k in (errors or {}) else ""  # noqa: E731
        fields = [
            FormField("company_name", t("settings.company_name"), "text", v("company_name"), required=True, error=e("company_name")),
            FormField("default_language", t("settings.default_language"), "select", v("default_language"),
                      options=list(LANGUAGES.items())),
            FormField("default_charset", t("settings.default_charset"), "select", v("default_charset"),
                      options=list(charsets.CHARSETS.items()), help=t("settings.default_charset_help")),
            FormField("timezone", t("settings.timezone"), "select", v("timezone"), options=[(z, z) for z in common_timezones()]),
            FormField("default_currency", t("settings.default_currency"), "select", v("default_currency"),
                      options=[(c, c) for c in CURRENCIES]),
            FormField("page_size", t("settings.page_size"), "number", v("page_size"), attrs={"min": "5", "max": "500"},
                      error=e("page_size")),
            FormField("session_hours", t("settings.session_hours"), "number", v("session_hours"),
                      attrs={"min": "1", "max": "720"}, error=e("session_hours")),
            FormField("api_enabled", t("settings.api_enabled"), "checkbox", v("api_enabled") in ("1", True),
                      help=t("settings.api_enabled_help")),
        ]
        extra = (f'<p><a href="/admin/backup/config">{tornado.escape.xhtml_escape(t("settings.download_config"))}</a></p>')
        self.form_page(t("admin.settings"), fields, self.admin_crumbs((t("admin.settings"), "/admin/settings")),
                       error=error, extra=extra, intro=t("settings.intro"))

    def get(self) -> None:
        self.show({})

    async def post(self) -> None:
        values = {k: self.get_argument(k, "").strip() for k in self.KEYS}
        values["api_enabled"] = "1" if self.bool_arg("api_enabled") else "0"
        errors = {}
        if not values["company_name"]:
            errors["company_name"] = "error.required"
        if values["default_language"] not in LANGUAGES:
            values["default_language"] = "tr-TR"
        values["default_charset"] = charsets.normalize(values["default_charset"])
        if values["timezone"] not in common_timezones():
            values["timezone"] = "UTC"
        if values["default_currency"] not in CURRENCIES:
            values["default_currency"] = "TRY"
        for key, lo, hi in (("page_size", 5, 500), ("session_hours", 1, 720)):
            if not values[key].isdigit() or not lo <= int(values[key]) <= hi:
                errors[key] = "error.invalid_value"
        if errors:
            return self.show(values, errors, self.t("error.form"))
        await self.db(settings_repo.save_settings, values)
        await self.audit("settings_save", "", ", ".join(f"{k}={v}" for k, v in values.items()))
        self.flash(self.t("common.saved"))
        self.redirect("/admin/settings")


# ====================================================================== backup
class BackupHandler(AdminHandler):
    async def get(self, kind: str) -> None:
        await self.show(kind)

    async def show(self, kind: str) -> None:
        t = self.t
        entities = await self.db(entities_repo.list_entities) if kind == "data" else []
        fields = [
            FormField("format", t("backup.format"), "select", "toml", options=[("toml", "TOML"), ("sql", "SQL")]),
            FormField("dialect", t("backup.dialect"), "select", self.state.db.dialect.name,
                      options=[(d.name, d.title) for d in DIALECTS.values()], help=t("backup.dialect_help")),
            FormField("charset", t("backup.charset"), "select", self.cfg.get("default_charset", "utf-8"),
                      options=list(charsets.CHARSETS.items()), help=t("backup.charset_help")),
        ]
        if kind == "data":
            fields.append(FormField("entities", t("backup.entities"), "checkboxes", [e.name for e in entities],
                                    options=[(e.name, f"{e.label} ({e.name})") for e in entities]))
        if kind in ("data", "full"):
            fields.append(FormField("include_files", t("backup.include_files"), "checkbox", False,
                                    help=t("backup.include_files_help")))
        title = t(f"backup.kind_{kind}")
        self.form_page(title, fields, self.admin_crumbs((t("admin.backup"), "/admin/backup"), (title, self.request.path)),
                       submit=t("common.download"), intro=t(f"backup.kind_{kind}_hint"))

    async def post(self, kind: str) -> None:
        fmt = self.get_argument("format", "toml")
        charset = charsets.normalize(self.get_argument("charset", "utf-8"))
        dialect = self.get_argument("dialect", self.state.db.dialect.name)
        if dialect not in DIALECTS:
            dialect = self.state.db.dialect.name
        names = self.get_arguments("entities") if kind == "data" else None
        if fmt == "sql":
            data = await self.db(backup.to_sql, kind, dialect, charset, names)
            ctype = "application/sql"
        else:
            fmt = "toml"
            data = await self.db(backup.to_toml, kind, charset, names, self.bool_arg("include_files"),
                                 self.state.config.upload_dir)
            ctype = "application/toml"
        await self.audit("export", kind, f"{fmt}, {charset}" + (f", {dialect}" if fmt == "sql" else ""))
        send_download(self, data, backup.file_name(kind, fmt, self.cfg.get("company_name", "erp")), ctype, charset)


class RestoreHandler(AdminHandler):
    def fields(self) -> list[FormField]:
        t = self.t
        return [
            FormField("file", t("backup.toml_file"), "file", required=True, attrs={"accept": ".toml,text/plain"}),
            FormField("charset", t("backup.charset"), "select", "",
                      options=[("", t("backup.charset_auto"))] + list(charsets.CHARSETS.items())),
            FormField("mode", t("backup.mode"), "select", "append",
                      options=[("append", t("backup.mode_append")), ("replace", t("backup.mode_replace"))],
                      help=t("backup.mode_help")),
            FormField("confirm_full", t("backup.confirm_full"), "checkbox", False, help=t("backup.confirm_full_help")),
        ]

    def crumbs_(self):
        t = self.t
        return self.admin_crumbs((t("admin.backup"), "/admin/backup"), (t("backup.restore"), "/admin/restore"))

    def get(self) -> None:
        self.form_page(self.t("backup.restore"), self.fields(), self.crumbs_(), multipart=True,
                       submit=self.t("backup.restore_button"), intro=self.t("backup.restore_intro"))

    async def post(self) -> None:
        t = self.t
        upload = (self.request.files.get("file") or [None])[0]

        def fail(message):
            self.form_page(t("backup.restore"), self.fields(), self.crumbs_(), multipart=True,
                           submit=t("backup.restore_button"), error=message, intro=t("backup.restore_intro"))

        if not upload or not upload["body"]:
            return fail(t("error.no_file"))
        try:
            doc = backup.load_toml(upload["body"], self.get_argument("charset", "") or None)
        except backup.BackupError as exc:
            return fail(t(exc.key, **exc.params))
        kind = doc["backup"]["kind"]
        if kind == "full" and not self.bool_arg("confirm_full"):
            return fail(t("backup.confirm_full_required"))
        mode = "replace" if self.get_argument("mode", "append") == "replace" else "append"
        try:
            stats = await self.db(backup.import_toml, doc, mode, self.state.config.upload_dir)
        except (backup.BackupError, ValidationError) as exc:
            return fail(t(exc.key, **exc.params))
        except Exception as exc:  # noqa: BLE001 - report database errors to the administrator
            return fail(t("backup.restore_failed", error=str(exc)))
        summary = ", ".join(f"{k}: {v}" for k, v in stats.items())
        if kind == "full":
            # Sessions were replaced too; the administrator must log in again.
            self.clear_cookie("erp_session")
            self.message_page(t("backup.restore"), t("backup.restore_done", summary=summary), [],
                              links=[(t("login.title"), "/login")])
            return
        await self.audit("restore", kind, summary)
        self.message_page(t("backup.restore"), t("backup.restore_done", summary=summary), self.crumbs_(),
                          links=[(t("menu.main"), "/")])


# ====================================================================== audit & system
class AuditHandler(AdminHandler):
    async def get(self) -> None:
        total = await self.db(audit_repo.count_entries)
        pages, page, offset = page_window(total, self.int_arg("page", 1), 50)
        entries = await self.db(audit_repo.list_entries, 50, offset)
        t = self.t
        rows = [{"cells": [{"text": self.loc.datetime(e["created_at"])}, {"text": e.get("username") or "—"},
                           {"text": e["action"]}, {"text": e.get("target") or ""}, {"text": (e.get("detail") or "")[:200]}]}
                for e in entries]
        columns = [{"label": t("audit.time")}, {"label": t("users.username")}, {"label": t("audit.action")},
                   {"label": t("audit.target")}, {"label": t("audit.detail")}]
        self.render("list.html", title=t("admin.audit"), crumbs=self.admin_crumbs((t("admin.audit"), "/admin/audit")),
                    columns=columns, rows=rows, search=False, q="", page=page, pages=pages, total=total,
                    base_url="/admin/audit?", actions=[], empty=t("common.no_rows"), notice=None, description="")


class SystemHandler(AdminHandler):
    async def get(self) -> None:
        def info(conn):
            counts = {}
            for ent in entities_repo.list_entities(conn):
                counts[ent.label] = conn.scalar(f"SELECT COUNT(*) FROM {conn.q(ent.table)}")
            return counts, len(files_repo.list_files(conn))

        counts, files = await self.db(info)
        version = await self.db(server_version)
        t = self.t
        cfg = self.state.config
        items = [
            {"label": t("system.app_version"), "text": __version__},
            {"label": "Python", "text": f"{platform.python_version()} ({sys.platform})"},
            {"label": "Tornado", "text": tornado.version},
            {"label": t("system.database"), "text": f"{self.state.db.dialect.title} — {version}"},
            {"label": t("system.config_file"), "text": str(cfg.path.resolve())},
            {"label": t("system.upload_dir"), "text": cfg.upload_dir},
            {"label": t("system.files"), "text": str(files)},
        ] + [{"label": f"{t('system.records')}: {k}", "text": self.loc.number(v)} for k, v in counts.items()]
        actions = [{"label": t("system.cleanup"), "url": "/admin/system/cleanup", "key": "c"}]
        self.render("view.html", title=t("admin.system"), items=items, meta=[], actions=actions,
                    crumbs=self.admin_crumbs((t("admin.system"), "/admin/system")))


class CleanupHandler(AdminHandler):
    def get(self) -> None:
        t = self.t
        self.render("confirm.html", title=t("system.cleanup"), message=t("system.cleanup_confirm"), action=self.request.path,
                    button=t("system.cleanup"), danger=False,
                    crumbs=self.admin_crumbs((t("admin.system"), "/admin/system"), (t("system.cleanup"), self.request.path)))

    async def post(self) -> None:
        n = await self.db(files_repo.delete_orphans, self.state.config.upload_dir, 24)
        await self.audit("cleanup", "", f"{n} files")
        self.flash(self.t("system.cleanup_done", count=n))
        self.redirect("/admin/system")
