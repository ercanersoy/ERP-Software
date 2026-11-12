"""Screens for the records of user defined entities."""

from __future__ import annotations

import datetime as dt
import decimal

import tornado.httputil
import tornado.web

from .. import backup, charsets
from ..db import DIALECTS
from ..db.database import utcnow
from ..fieldtypes import Field, ValidationError
from ..repo import entities as entities_repo
from ..repo import files as files_repo
from ..repo import menus as menus_repo
from ..repo import records as records_repo
from .base import BaseHandler, FormField, page_window
from .files import content_disposition


class EntityHandler(BaseHandler):
    """Base class: loads the entity named in the URL and checks access."""

    write_access = False
    ent: entities_repo.Entity

    async def load_entity(self, name: str):
        def load(conn):
            ent = entities_repo.get_entity(conn, name)
            menus = menus_repo.list_menus(conn) if ent else []
            return ent, menus

        ent, menus = await self.db(load)
        if ent is None:
            raise tornado.web.HTTPError(404)
        if not ent.can_read(self.user) or (self.write_access and not ent.can_write(self.user)):
            raise tornado.web.HTTPError(403)
        self.ent = ent
        self.menus = menus
        return ent

    def entity_crumbs(self, *extra: tuple[str, str]) -> list[tuple[str, str]]:
        path = [(m["title"], f"/menu/{m['id']}") for m in menus_repo.menu_path(self.menus, self.ent.menu_id)]
        return self.crumbs(*path, (self.ent.label, f"/data/{self.ent.name}"), *extra)

    async def load_record(self, record_id: int) -> dict:
        record = await self.db(records_repo.get_record, self.ent, record_id)
        if record is None:
            raise tornado.web.HTTPError(404)
        owner = self.ent.owner_filter(self.user)
        if owner is not None and record["created_by"] != owner:
            raise tornado.web.HTTPError(404)
        return record

    # ------------------------------------------------------------------ display
    async def related(self, rows: list[dict]) -> tuple[dict, dict]:
        """Load reference titles and file rows needed to display ``rows``."""
        ent = self.ent

        def load(conn):
            refs: dict[str, dict[int, str]] = {}
            file_ids: set[int] = set()
            for f in ent.fields:
                ids = {r[f.name] for r in rows if r.get(f.name)}
                if f.field_type == "reference" and ids:
                    target = entities_repo.get_entity(conn, f.ref_entity or "")
                    refs[f.name] = records_repo.reference_titles(conn, target, ids) if target else {}
                elif f.is_file:
                    file_ids |= ids
            return refs, files_repo.get_files(conn, file_ids)

        return await self.db(load)

    def display(self, f: Field, value, refs: dict, files: dict) -> dict:
        """Return ``{"text", "url", "media"}`` describing how to show a value."""
        loc = self.loc
        if value is None:
            return {"text": ""}
        match f.field_type:
            case "boolean":
                return {"text": loc.boolean(value)}
            case "integer":
                return {"text": loc.number(value)}
            case "decimal":
                return {"text": loc.number(value, f.scale)}
            case "float":
                return {"text": loc.number(value)}
            case "currency":
                code = f.currency or self.cfg.get("default_currency", "TRY")
                places = 2 if f.scale >= 2 else f.scale
                if isinstance(value, decimal.Decimal) and value != value.quantize(decimal.Decimal("0.01")):
                    places = f.scale
                return {"text": loc.currency(value, code, places)}
            case "date":
                return {"text": loc.date(value)}
            case "datetime":
                return {"text": loc.datetime(value)}
            case "reference":
                title = refs.get(f.name, {}).get(value, f"#{value}")
                return {"text": title, "url": f"/data/{f.ref_entity}/{value}"}
            case "document" | "image" | "video":
                row = files.get(value)
                if row is None:
                    return {"text": f"#{value}"}
                return {"text": row["original_name"], "url": f"/files/{value}", "media": f.field_type,
                        "size": row["size_bytes"]}
            case "longtext":
                return {"text": str(value), "multiline": True}
        return {"text": str(value)}


class RecordListHandler(EntityHandler):
    async def get(self, name: str) -> None:
        ent = await self.load_entity(name)
        q = self.get_argument("q", "").strip()[:100]
        sort = self.get_argument("sort", "id")
        if sort not in ("id", "created_at", "updated_at") and ent.field(sort) is None:
            sort = "id"
        desc = self.get_argument("dir", "desc") != "asc"
        size = int(ent.page_size or self.cfg.get("page_size") or 25)
        owner = ent.owner_filter(self.user)
        total = await self.db(records_repo.count_records, ent, search=q or None, owner_id=owner)
        pages, page, offset = page_window(total, self.int_arg("page", 1), size)
        rows = await self.db(records_repo.list_records, ent, search=q or None, order=sort, desc=desc,
                             limit=size, offset=offset, owner_id=owner)
        refs, files = await self.related(rows)
        fields = ent.list_fields
        table_rows = []
        for r in rows:
            cells = [{"text": str(r["id"])}] + [self.display(f, r.get(f.name), refs, files) for f in fields]
            table_rows.append({"url": f"/data/{ent.name}/{r['id']}", "cells": cells})
        columns = [{"key": "id", "label": "#", "num": True}] + [
            {"key": f.name, "label": f.label,
             "num": f.field_type in ("integer", "decimal", "float", "currency")} for f in fields
        ]
        actions = []
        if ent.can_write(self.user):
            actions.append({"label": self.t("common.new"), "url": f"/data/{ent.name}/new", "key": "n", "attr": "data-new"})
        if ent.is_sensor:
            actions.append({"label": self.t("data.monitor"), "url": f"/data/{ent.name}/monitor", "key": "m"})
        actions.append({"label": self.t("data.export"), "url": f"/data/{ent.name}/export", "key": "x"})
        if ent.can_write(self.user):
            actions.append({"label": self.t("data.import_csv"), "url": f"/data/{ent.name}/import", "key": "i"})
        base = f"/data/{ent.name}?" + tornado.httputil.urlencode({"q": q, "sort": sort, "dir": "desc" if desc else "asc"})
        self.render(
            "list.html", title=ent.label, crumbs=self.entity_crumbs(), columns=columns, rows=table_rows,
            actions=actions, search=True, q=q, sort=sort, desc=desc, page=page, pages=pages, total=total,
            base_url=base, sort_base=f"/data/{ent.name}?" + tornado.httputil.urlencode({"q": q}),
            description=ent.description,
            empty=self.t("data.no_records") if not ent.fields else self.t("common.no_rows"),
            notice=None if ent.fields else (self.t("data.no_fields_admin") if self.is_admin() else self.t("data.no_fields")),
        )


class RecordViewHandler(EntityHandler):
    async def get(self, name: str, record_id: str) -> None:
        ent = await self.load_entity(name)
        record = await self.load_record(int(record_id))
        refs, files = await self.related([record])
        items = [{"label": f.label, **self.display(f, record.get(f.name), refs, files)} for f in ent.fields]
        meta = [
            (self.t("data.created_at"), self.loc.datetime(record["created_at"])),
            (self.t("data.updated_at"), self.loc.datetime(record["updated_at"])),
        ]
        actions = []
        if ent.can_write(self.user):
            actions.append({"label": self.t("common.edit"), "url": f"/data/{ent.name}/{record['id']}/edit", "key": "e", "attr": "data-edit"})
            actions.append({"label": self.t("common.delete"), "url": f"/data/{ent.name}/{record['id']}/delete", "key": "Del", "attr": "data-delete"})
        title = ent.record_title(record)
        self.render("view.html", title=f"{ent.label}: {title}", items=items, meta=meta, actions=actions,
                    crumbs=self.entity_crumbs((title, f"/data/{ent.name}/{record['id']}")))


class RecordFormHandler(EntityHandler):
    write_access = True

    async def form_fields(self, record: dict | None, raw: dict, errors: dict) -> list[FormField]:
        ent = self.ent

        def load(conn):
            options = {}
            for f in ent.fields:
                if f.field_type == "reference":
                    target = entities_repo.get_entity(conn, f.ref_entity or "")
                    if target is not None:
                        owner = target.owner_filter(self.user)
                        rows = records_repo.list_records(conn, target, limit=1000, desc=False, owner_id=owner) \
                            if target.can_read(self.user) else []
                        options[f.name] = [(r["id"], target.record_title(r)) for r in rows]
            file_ids = {record[f.name] for f in ent.fields if f.is_file and record and record.get(f.name)}
            return options, files_repo.get_files(conn, file_ids)

        options, files = await self.db(load)
        out = []
        for f in ent.fields:
            value = raw.get(f.name) if f.name in raw else self.input_value(f, record)
            if isinstance(value, dt.datetime):
                value = self.loc.to_local_input(value)
            err = errors.get(f.name)
            ff = FormField(f.name, f.label, required=f.required, help=f.help_text or "",
                           error=self.t(err.key, **err.params) if err else "", value=value)
            match f.field_type:
                case "text":
                    ff.attrs = {"maxlength": str(f.max_length or 255)}
                case "longtext":
                    ff.type = "textarea"
                case "integer":
                    ff.type, ff.attrs = "number", {"step": "1"}
                case "decimal" | "currency":
                    ff.type = "number"
                    ff.attrs = {"step": "0." + "0" * (f.scale - 1) + "1" if f.scale else "1"}
                    if f.field_type == "currency":
                        ff.suffix = f.currency or self.cfg.get("default_currency", "TRY")
                case "float":
                    ff.type, ff.attrs = "number", {"step": "any"}
                case "boolean":
                    ff.type = "checkbox"
                case "date":
                    ff.type = "date"
                case "datetime":
                    ff.type, ff.attrs = "datetime-local", {"step": "1"}
                case "email":
                    ff.type = "email"
                case "choice":
                    ff.type = "select"
                    ff.options = [("", "—")] + [(c, c) for c in f.choices]
                case "reference":
                    ff.type = "select"
                    ff.options = [("", "—")] + [(str(i), lbl) for i, lbl in options.get(f.name, [])]
                case "document" | "image" | "video":
                    ff.type = "file"
                    ff.attrs = {"accept": f.type.accept}
                    current = files.get(record.get(f.name)) if record else None
                    ff.current = current
                    ff.help = (ff.help + " " if ff.help else "") + self.t(f"data.accept_{f.field_type}")
            out.append(ff)
        return out

    def input_value(self, f: Field, record: dict | None):
        if record is None:
            if f.default_value not in (None, ""):
                if f.field_type == "boolean":
                    return f.parse(f.default_value)
                return f.default_value
            return False if f.field_type == "boolean" else ""
        value = record.get(f.name)
        if value is None:
            return "" if f.field_type != "boolean" else False
        match f.field_type:
            case "datetime":
                return self.loc.to_local_input(value)
            case "date":
                return value.isoformat()
            case "decimal" | "currency":
                return format(value, "f")
            case "boolean":
                return bool(value)
        return str(value)

    async def show(self, record, raw, errors, error=None) -> None:
        ent = self.ent
        title = self.t("data.new_record") if record is None else self.t("data.edit_record")
        url = f"/data/{ent.name}/new" if record is None else f"/data/{ent.name}/{record['id']}/edit"
        extra_crumbs = [(title, url)] if record is None else [
            (ent.record_title(record), f"/data/{ent.name}/{record['id']}"), (title, url)]
        fields = await self.form_fields(record, raw, errors)
        if not fields:
            error = self.t("data.no_fields_admin") if self.is_admin() else self.t("data.no_fields")
        buttons = [("__again", "1", self.t("data.save_and_new"))] if record is None and fields else []
        self.form_page(f"{ent.label}: {title}", fields, self.entity_crumbs(*extra_crumbs), action=url,
                       multipart=any(f.is_file for f in ent.fields), error=error, buttons=buttons)

    async def get(self, name: str, record_id: str | None = None) -> None:
        await self.load_entity(name)
        record = await self.load_record(int(record_id)) if record_id else None
        await self.show(record, {}, {})

    async def post(self, name: str, record_id: str | None = None) -> None:
        ent = await self.load_entity(name)
        record = await self.load_record(int(record_id)) if record_id else None
        raw: dict = {}
        for f in ent.fields:
            if f.is_file:
                continue
            if f.field_type == "boolean":
                raw[f.name] = self.get_argument(f.name, "") in ("1", "on", "true")
            elif f.field_type == "datetime":
                text = self.get_argument(f.name, "").strip()
                try:
                    raw[f.name] = self.loc.from_local_input(text) if text else ""
                except ValueError:
                    raw[f.name] = text
            else:
                raw[f.name] = self.get_argument(f.name, "")
        values, errors = records_repo.validate(ent, raw, partial=False)
        # Files: keep, replace or remove.
        uploads: dict[str, dict] = {}
        for f in ent.fields:
            if not f.is_file:
                continue
            values.pop(f.name, None)
            errors.pop(f.name, None)
            current = record.get(f.name) if record else None
            upload = (self.request.files.get(f.name) or [None])[0]
            if upload and upload["body"]:
                uploads[f.name] = upload
            elif self.get_argument(f"__remove_{f.name}", "") and current:
                values[f.name] = None
                current = None
            if f.required and not current and f.name not in uploads:
                errors[f.name] = ValidationError("error.required")
            elif current and f.name not in uploads:
                values[f.name] = current
        if errors:
            return await self.show(record, raw, errors, self.t("error.form"))

        upload_dir = self.state.config.upload_dir
        saved: list[dict] = []
        try:
            for fname, upload in uploads.items():
                f = ent.field(fname)
                row = await self.db(files_repo.save_file, upload_dir, f.field_type, upload["filename"],
                                    upload["body"], upload.get("content_type"), ent.name, self.user["id"])
                saved.append(row)
                values[fname] = row["id"]
            if record is None:
                new_id = await self.db(records_repo.create_record, ent, values, self.user)
                await self.audit("record_create", f"{ent.name}#{new_id}")
                self.flash(self.t("data.created"))
                target = f"/data/{ent.name}/{new_id}"
            else:
                removed = await self.db(records_repo.update_record, ent, record["id"], values, self.user)
                files_repo.remove_from_disk(upload_dir, removed)
                await self.audit("record_update", f"{ent.name}#{record['id']}")
                self.flash(self.t("common.saved"))
                target = f"/data/{ent.name}/{record['id']}"
        except ValidationError as exc:
            await self._discard(saved)
            errors = {next(iter(uploads)): exc} if uploads else {}
            return await self.show(record, raw, errors, self.t(exc.key, **exc.params))
        except records_repo.RecordError as exc:
            await self._discard(saved)
            return await self.show(record, raw, exc.errors, self.t("error.form"))
        if self.get_argument("__again", ""):
            target = f"/data/{ent.name}/new"
        self.redirect(target)

    async def _discard(self, rows: list[dict]) -> None:
        if not rows:
            return

        def drop(conn):
            for r in rows:
                conn.delete("erp_files", {"id": r["id"]})

        await self.db(drop)
        files_repo.remove_from_disk(self.state.config.upload_dir, rows)


class RecordDeleteHandler(EntityHandler):
    write_access = True

    async def get(self, name: str, record_id: str) -> None:
        ent = await self.load_entity(name)
        record = await self.load_record(int(record_id))
        title = ent.record_title(record)
        self.render("confirm.html", title=self.t("common.delete"),
                    message=self.t("data.delete_confirm", title=title), action=self.request.path,
                    button=self.t("common.delete"), danger=True,
                    crumbs=self.entity_crumbs((title, f"/data/{ent.name}/{record['id']}"),
                                              (self.t("common.delete"), self.request.path)))

    async def post(self, name: str, record_id: str) -> None:
        ent = await self.load_entity(name)
        record = await self.load_record(int(record_id))
        removed = await self.db(records_repo.delete_record, ent, record["id"])
        files_repo.remove_from_disk(self.state.config.upload_dir, removed)
        await self.audit("record_delete", f"{ent.name}#{record['id']}")
        self.flash(self.t("data.deleted"))
        self.redirect(f"/data/{ent.name}")


class MonitorHandler(EntityHandler):
    """Live view of the newest records, refreshed at the entity's reading interval."""

    async def get(self, name: str) -> None:
        ent = await self.load_entity(name)
        interval = self.int_arg("interval", ent.read_interval_ms, 100, 86_400_000)
        self.render("monitor.html", title=f"{ent.label}: {self.t('data.monitor')}", ent=ent, interval=interval,
                    columns=["#"] + [f.label for f in ent.list_fields] + [self.t("data.created_at")],
                    crumbs=self.entity_crumbs((self.t("data.monitor"), f"/data/{ent.name}/monitor")))


class LatestJsonHandler(EntityHandler):
    async def get(self, name: str) -> None:
        ent = await self.load_entity(name)
        n = self.int_arg("n", 20, 1, 200)
        rows = await self.db(records_repo.list_records, ent, limit=n, owner_id=ent.owner_filter(self.user))
        refs, files = await self.related(rows)
        out = []
        for r in rows:
            cells = [str(r["id"])] + [self.display(f, r.get(f.name), refs, files)["text"] for f in ent.list_fields]
            cells.append(self.loc.datetime(r["created_at"]))
            out.append(cells)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.finish(backup.dumps_json({"interval_ms": ent.read_interval_ms, "rows": out,
                                       "updated": self.loc.datetime(utcnow())}))


class EntityExportHandler(EntityHandler):
    def fields(self, values: dict) -> list[FormField]:
        t = self.t
        formats = [("csv", "CSV")]
        if self.ent.owner_filter(self.user) is None:
            formats += [("toml", "TOML"), ("sql", "SQL")]
        return [
            FormField("format", t("backup.format"), "select", values.get("format", "csv"), options=formats),
            FormField("charset", t("backup.charset"), "select",
                      values.get("charset", self.cfg.get("default_charset", "utf-8")),
                      options=list(charsets.CHARSETS.items())),
            FormField("dialect", t("backup.dialect"), "select", values.get("dialect", self.state.db.dialect.name),
                      options=[(d.name, d.title) for d in DIALECTS.values()], help=t("backup.dialect_help")),
            FormField("delimiter", t("data.delimiter"), "select", values.get("delimiter", ";"),
                      options=[(";", t("data.delim_semicolon")), (",", t("data.delim_comma")),
                               ("tab", t("data.delim_tab"))], help=t("data.delimiter_help")),
        ]

    async def get(self, name: str) -> None:
        await self.load_entity(name)
        self.form_page(f"{self.ent.label}: {self.t('data.export')}", self.fields({}),
                       self.entity_crumbs((self.t("data.export"), self.request.path)),
                       submit=self.t("common.download"))

    async def post(self, name: str) -> None:
        ent = await self.load_entity(name)
        fmt = self.get_argument("format", "csv")
        charset = charsets.normalize(self.get_argument("charset", "utf-8"))
        owner = ent.owner_filter(self.user)
        if fmt == "csv" or owner is not None:
            delim = {"tab": "\t", ",": ","}.get(self.get_argument("delimiter", ";"), ";")
            rows = await self.db(records_repo.list_records, ent, limit=None, desc=False, owner_id=owner)
            data = await self.db(backup.to_csv, ent, charset, delim, rows)
            fmt, ctype = "csv", "text/csv"
        elif fmt == "sql":
            dialect = self.get_argument("dialect", self.state.db.dialect.name)
            if dialect not in DIALECTS:
                dialect = self.state.db.dialect.name
            data = await self.db(backup.to_sql, "data", dialect, charset, [ent.name])
            ctype = "application/sql"
        else:
            fmt = "toml"
            data = await self.db(backup.to_toml, "data", charset, [ent.name])
            ctype = "application/toml"
        await self.audit("export", f"{ent.name} ({fmt}, {charset})")
        send_download(self, data, backup.file_name("data", fmt, self.cfg.get("company_name", "erp"), ent.name),
                      ctype, charset)


class EntityImportHandler(EntityHandler):
    write_access = True

    def fields(self) -> list[FormField]:
        t = self.t
        return [
            FormField("file", t("data.csv_file"), "file", attrs={"accept": ".csv,.txt,text/csv"}, required=True),
            FormField("charset", t("backup.charset"), "select", self.cfg.get("default_charset", "utf-8"),
                      options=list(charsets.CHARSETS.items())),
            FormField("delimiter", t("data.delimiter"), "select", ";",
                      options=[(";", t("data.delim_semicolon")), (",", t("data.delim_comma")),
                               ("tab", t("data.delim_tab"))]),
        ]

    async def get(self, name: str) -> None:
        ent = await self.load_entity(name)
        columns = ", ".join(f.name for f in ent.fields if not f.is_file)
        self.form_page(f"{ent.label}: {self.t('data.import_csv')}", self.fields(),
                       self.entity_crumbs((self.t("data.import_csv"), self.request.path)),
                       multipart=True, submit=self.t("data.import"),
                       intro=self.t("data.import_intro", columns=columns or "—"))

    async def post(self, name: str) -> None:
        ent = await self.load_entity(name)
        upload = (self.request.files.get("file") or [None])[0]
        crumbs = self.entity_crumbs((self.t("data.import_csv"), self.request.path))
        if not upload or not upload["body"]:
            return self.form_page(f"{ent.label}: {self.t('data.import_csv')}", self.fields(), crumbs,
                                  multipart=True, submit=self.t("data.import"), error=self.t("error.no_file"))
        delim = {"tab": "\t", ",": ","}.get(self.get_argument("delimiter", ";"), ";")
        rows, errors = backup.parse_csv(ent, upload["body"], self.get_argument("charset", "utf-8"), delim)

        def insert(conn):
            created, failed = 0, []
            for i, values in enumerate(rows):
                try:
                    records_repo.create_record(conn, ent, values, self.user)
                    created += 1
                except records_repo.RecordError as exc:
                    failed.extend((i + 2, k, v) for k, v in exc.errors.items())
            return created, failed

        created, failed = await self.db(insert)
        errors += failed
        await self.audit("import_csv", ent.name, f"{created} records")
        lines = [self.t("data.import_done", count=created)]
        for lineno, fname, err in errors[:50]:
            lines.append(self.t("data.import_line_error", line=lineno, field=fname,
                                error=self.t(err.key, **err.params)))
        self.message_page(self.t("data.import_csv"), "\n".join(lines), crumbs,
                          links=[(ent.label, f"/data/{ent.name}")])


def send_download(handler: BaseHandler, data: bytes, filename: str, content_type: str, charset: str) -> None:
    handler.set_header("Content-Type", f"{content_type}; charset={charsets.http_name(charset)}")
    handler.set_header("Content-Disposition", content_disposition("attachment", filename))
    handler.set_header("Content-Length", str(len(data)))
    handler.finish(data)
