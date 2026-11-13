"""REST API (``/api/v1``) and WebSocket stream for external systems and sensors.

Authentication: ``Authorization: Bearer <token>`` or ``X-API-Key: <token>``.
Tokens are created by administrators; every key can be limited to entities,
read/write access, source IP networks and a minimum interval between writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import tornado.web
import tornado.websocket

from .. import __version__, charsets
from ..backup import json_default
from ..db.database import utcnow
from ..fieldtypes import FILE_KINDS, ValidationError
from ..repo import apikeys as apikeys_repo
from ..repo import entities as entities_repo
from ..repo import files as files_repo
from ..repo import records as records_repo
from ..repo import settings as settings_repo

log = logging.getLogger("erp.api")
MAX_BATCH = 1000


class ApiError(tornado.web.HTTPError):
    def __init__(self, status: int, code: str, message: str = "", details: dict | None = None):
        super().__init__(status, code.replace("%", ""))
        self.status = status
        self.code = code
        self.message = message or code
        self.details = details or {}


def record_json(ent, record: dict) -> dict:
    out = {"id": record["id"]}
    for f in ent.fields:
        out[f.name] = f.to_json(record.get(f.name))
    for key in ("created_at", "updated_at"):
        out[key] = record[key].isoformat() + "Z" if record.get(key) else None
    out["created_by"] = record.get("created_by")
    out["api_key_id"] = record.get("api_key_id")
    return out


def entity_json(ent) -> dict:
    return {
        "name": ent.name,
        "label": ent.label,
        "description": ent.description,
        "is_sensor": ent.is_sensor,
        "read_interval_ms": ent.read_interval_ms,
        "fields": [
            {k: v for k, v in f.as_dict().items() if v is not None and k != "sort_order"} for f in ent.fields
        ],
    }


def errors_json(errors: dict[str, ValidationError]) -> dict[str, str]:
    return {name: err.key.removeprefix("error.") for name, err in errors.items()}


class ApiAuth:
    """Authentication and rate limiting shared by REST and WebSocket handlers."""

    key: dict

    async def authenticate_token(self, token: str) -> dict:
        state = self.application.settings["erp_state"]
        if not state.installed:
            raise ApiError(503, "not_installed")

        def load(conn):
            settings = settings_repo.get_settings(conn)
            key = apikeys_repo.authenticate(conn, token, self.request.remote_ip) if token else None
            return settings, key

        settings, key = await state.db.run(load)
        if settings.get("api_enabled", "1") != "1":
            raise ApiError(503, "api_disabled")
        if key is None:
            raise ApiError(401, "unauthorized", "missing, invalid, expired or not allowed API key")
        self.key = key
        return key

    def check_rate(self) -> None:
        interval = self.key["min_interval_ms"]
        if not interval:
            return
        state = self.application.settings["erp_state"]
        now = time.monotonic()
        last = state.api_last_write.get(self.key["id"])
        # A key that has not written yet is never limited.  (Using 0.0 as the
        # default was wrong: time.monotonic() starts near zero after a reboot.)
        wait = interval / 1000 - (now - last) if last is not None else 0
        if wait > 0:
            raise ApiError(429, "too_many_requests", f"minimum interval is {interval} ms",
                           {"retry_after_ms": int(wait * 1000) + 1})
        state.api_last_write[self.key["id"]] = now

    async def entity(self, name: str, write: bool):
        state = self.application.settings["erp_state"]
        ent = await state.db.run(entities_repo.get_entity, name)
        if ent is None or not apikeys_repo.key_allows(self.key, name, False if not write else True):
            if ent is not None and apikeys_repo.key_allows(self.key, name, not write):
                raise ApiError(403, "forbidden", "this API key may not " + ("write" if write else "read"))
            raise ApiError(404, "not_found", f"unknown entity {name!r}")
        return ent


class ApiHandler(ApiAuth, tornado.web.RequestHandler):
    def check_xsrf_cookie(self) -> None:  # token based authentication, no cookies
        pass

    def set_default_headers(self) -> None:
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_header("Cache-Control", "no-store")
        self.set_header("X-Content-Type-Options", "nosniff")

    @property
    def state(self):
        return self.application.settings["erp_state"]

    async def prepare(self) -> None:
        auth = self.request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else self.request.headers.get("X-API-Key", "").strip()
        await self.authenticate_token(token)

    def send_json(self, data, status: int = 200) -> None:
        self.set_status(status)
        self.finish(json.dumps(data, default=json_default, ensure_ascii=False))

    def send_error_json(self, exc: ApiError) -> None:
        if exc.status == 401:
            self.set_header("WWW-Authenticate", 'Bearer realm="erp"')
        if exc.status == 429:
            self.set_header("Retry-After", str(max(1, exc.details.get("retry_after_ms", 1000) // 1000)))
        body = {"error": exc.code, "message": exc.message}
        if exc.details:
            body["details"] = exc.details
        self.send_json(body, exc.status)

    def int_arg(self, name: str, default: int) -> int:
        try:
            return int(self.get_argument(name, str(default)) or default)
        except ValueError:
            raise ApiError(400, "invalid_parameter", f"{name} must be an integer") from None

    def body_json(self):
        ctype = self.request.headers.get("Content-Type", "application/json")
        charset = "utf-8"
        if "charset=" in ctype:
            charset = charsets.normalize(ctype.split("charset=", 1)[1].split(";")[0].strip().strip('"'))
        try:
            return json.loads(charsets.decode(self.request.body, charset) or "null")
        except ValueError:
            raise ApiError(400, "invalid_json") from None

    def write_error(self, status_code: int, **kwargs) -> None:
        exc = kwargs.get("exc_info", (None, None, None))[1]
        if isinstance(exc, ApiError):
            return self.send_error_json(exc)
        if isinstance(exc, tornado.web.HTTPError):
            return self.send_json({"error": exc.reason or "error", "message": exc.log_message or ""}, status_code)
        self.send_json({"error": "internal_error"}, status_code)


class PingHandler(ApiHandler):
    def get(self) -> None:
        self.send_json({"ok": True, "version": __version__, "key": self.key["name"], "time": utcnow().isoformat() + "Z",
                        "can_read": self.key["can_read"], "can_write": self.key["can_write"]})


class EntitiesHandler(ApiHandler):
    async def get(self) -> None:
        ents = await self.state.db.run(entities_repo.list_entities)
        allowed = [e for e in ents if apikeys_repo.key_allows(self.key, e.name, False)
                   or apikeys_repo.key_allows(self.key, e.name, True)]
        self.send_json({"entities": [entity_json(e) for e in allowed]})


class EntitySchemaHandler(ApiHandler):
    async def get(self, name: str) -> None:
        ent = await self.state.db.run(entities_repo.get_entity, name)
        if ent is None or not (apikeys_repo.key_allows(self.key, name, False) or apikeys_repo.key_allows(self.key, name, True)):
            raise ApiError(404, "not_found")
        self.send_json(entity_json(ent))


class EntityConfigHandler(ApiHandler):
    """Lets a sensor ask how often it should read and send values."""

    async def get(self, name: str) -> None:
        ent = await self.state.db.run(entities_repo.get_entity, name)
        if ent is None or not (apikeys_repo.key_allows(self.key, name, False) or apikeys_repo.key_allows(self.key, name, True)):
            raise ApiError(404, "not_found")
        self.send_json({"entity": ent.name, "read_interval_ms": ent.read_interval_ms,
                        "min_interval_ms": self.key["min_interval_ms"], "server_time": utcnow().isoformat() + "Z"})


class RecordsHandler(ApiHandler):
    async def get(self, name: str) -> None:
        ent = await self.entity(name, write=False)
        limit = min(max(self.int_arg("limit", 100), 1), 1000)
        offset = max(self.int_arg("offset", 0), 0)
        since_id = self.get_argument("since_id", "")
        order = self.get_argument("order", "id")
        desc = self.get_argument("dir", "asc" if since_id else "desc") == "desc"
        filters = {}
        for f in ent.fields:
            raw = self.get_argument(f.name, None)
            if raw is not None and not f.is_file:
                try:
                    filters[f.name] = f.parse(raw)
                except ValidationError as exc:
                    raise ApiError(400, "invalid_filter", details={f.name: exc.key.removeprefix("error.")}) from None
        q = self.get_argument("q", "") or None

        def load(conn):
            rows = records_repo.list_records(conn, ent, search=q, order=order, desc=desc, limit=limit, offset=offset,
                                             since_id=int(since_id) if since_id.isdigit() else None, filters=filters)
            total = records_repo.count_records(conn, ent, search=q) if not filters and not since_id else None
            return rows, total

        rows, total = await self.state.db.run(load)
        out = {"entity": ent.name, "count": len(rows), "records": [record_json(ent, r) for r in rows]}
        if total is not None:
            out["total"] = total
        self.send_json(out)

    async def post(self, name: str) -> None:
        ent = await self.entity(name, write=True)
        payload = self.body_json()
        batch = isinstance(payload, list)
        items = payload if batch else [payload]
        if not items or len(items) > MAX_BATCH or not all(isinstance(i, dict) for i in items):
            raise ApiError(400, "invalid_body", f"send a JSON object or an array of 1..{MAX_BATCH} objects")
        self.check_rate()
        prepared = []
        for index, item in enumerate(items):
            unknown = [k for k in item if ent.field(k) is None and k not in ("id",)]
            values, errors = records_repo.validate(ent, records_repo.apply_defaults(ent, item))
            if errors or unknown:
                details = errors_json(errors) | {k: "unknown_field" for k in unknown}
                raise ApiError(422, "validation_failed", details={"index": index, "fields": details} if batch else details)
            prepared.append(values)

        def insert(conn):
            return [records_repo.create_record(conn, ent, v, None, self.key["id"]) for v in prepared]

        try:
            ids = await self.state.db.run(insert)
        except records_repo.RecordError as exc:
            raise ApiError(422, "validation_failed", details=errors_json(exc.errors)) from None
        self.state.publish(ent.name, ids)
        if batch:
            self.send_json({"ids": ids, "count": len(ids)}, 201)
        else:
            self.set_header("Location", f"/api/v1/entities/{ent.name}/records/{ids[0]}")
            self.send_json({"id": ids[0]}, 201)


class RecordHandler(ApiHandler):
    async def get(self, name: str, record_id: str) -> None:
        ent = await self.entity(name, write=False)
        record = await self.state.db.run(records_repo.get_record, ent, int(record_id))
        if record is None:
            raise ApiError(404, "not_found")
        self.send_json(record_json(ent, record))

    async def _update(self, name: str, record_id: str, partial: bool) -> None:
        ent = await self.entity(name, write=True)
        payload = self.body_json()
        if not isinstance(payload, dict):
            raise ApiError(400, "invalid_body")
        self.check_rate()
        unknown = [k for k in payload if ent.field(k) is None and k != "id"]
        values, errors = records_repo.validate(ent, payload, partial=partial)
        if errors or unknown:
            raise ApiError(422, "validation_failed", details=errors_json(errors) | {k: "unknown_field" for k in unknown})
        try:
            removed = await self.state.db.run(records_repo.update_record, ent, int(record_id), values, None, self.key["id"])
        except KeyError:
            raise ApiError(404, "not_found") from None
        except records_repo.RecordError as exc:
            raise ApiError(422, "validation_failed", details=errors_json(exc.errors)) from None
        files_repo.remove_from_disk(self.state.config.upload_dir, removed)
        record = await self.state.db.run(records_repo.get_record, ent, int(record_id))
        self.send_json(record_json(ent, record))

    async def put(self, name: str, record_id: str) -> None:
        await self._update(name, record_id, partial=False)

    async def patch(self, name: str, record_id: str) -> None:
        await self._update(name, record_id, partial=True)

    async def delete(self, name: str, record_id: str) -> None:
        ent = await self.entity(name, write=True)

        def remove(conn):
            if records_repo.get_record(conn, ent, int(record_id)) is None:
                return None
            return records_repo.delete_record(conn, ent, int(record_id))

        removed = await self.state.db.run(remove)
        if removed is None:
            raise ApiError(404, "not_found")
        files_repo.remove_from_disk(self.state.config.upload_dir, removed)
        self.set_status(204)
        self.finish()


class LatestHandler(ApiHandler):
    async def get(self, name: str) -> None:
        ent = await self.entity(name, write=False)
        n = min(max(self.int_arg("n", 1), 1), 1000)
        rows = await self.state.db.run(records_repo.list_records, ent, limit=n)
        self.send_json({"entity": ent.name, "read_interval_ms": ent.read_interval_ms,
                        "records": [record_json(ent, r) for r in rows]})


class FileUploadHandler(ApiHandler):
    """``POST /api/v1/files?kind=image&entity=name`` with multipart field ``file``."""

    async def post(self) -> None:
        kind = self.get_argument("kind", "document")
        entity = self.get_argument("entity", "")
        if kind not in FILE_KINDS:
            raise ApiError(400, "invalid_kind")
        await self.entity(entity, write=True)
        upload = (self.request.files.get("file") or [None])[0]
        if upload is None or not upload["body"]:
            raise ApiError(400, "no_file", "send the file as multipart/form-data field 'file'")
        self.check_rate()
        try:
            row = await self.state.db.run(files_repo.save_file, self.state.config.upload_dir, kind, upload["filename"],
                                          upload["body"], upload.get("content_type"), entity, None)
        except ValidationError as exc:
            raise ApiError(422, exc.key.removeprefix("error.")) from None
        self.send_json({"id": row["id"], "name": row["original_name"], "mime_type": row["mime_type"],
                        "size": row["size_bytes"], "sha256": row["sha256"]}, 201)


class FileDownloadHandler(ApiHandler):
    async def get(self, file_id: str) -> None:
        row = await self.state.db.run(files_repo.get_file, int(file_id))
        if row is None or not row["entity"] or not apikeys_repo.key_allows(self.key, row["entity"], False):
            raise ApiError(404, "not_found")
        path = files_repo.storage_path(self.state.config.upload_dir, row["storage_key"])
        try:
            data = await asyncio.get_running_loop().run_in_executor(None, path.read_bytes)
        except OSError:
            raise ApiError(404, "not_found") from None
        self.set_header("Content-Type", row["mime_type"])
        self.set_header("Content-Disposition", f'attachment; filename="{row["original_name"].encode("ascii", "replace").decode()}"')
        self.finish(data)


class StreamHandler(ApiAuth, tornado.websocket.WebSocketHandler):
    """WebSocket ``/api/v1/stream/<entity>`` for real time sensor data.

    * Messages sent by the client (a JSON object or array) are stored as records
      when the key may write.
    * New records of the entity are pushed to every connected client whose key
      may read: ``{"event": "created", "records": [...]}``.
    * On connect the server sends ``{"event": "hello", "read_interval_ms": ...}``.
    """

    ent = None

    def check_origin(self, origin: str) -> bool:
        return True  # authentication uses API keys, not cookies

    async def get(self, *args, **kwargs):
        auth = self.request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else (
            self.request.headers.get("X-API-Key", "") or self.get_argument("token", "")).strip()
        try:
            await self.authenticate_token(token)
            if not (apikeys_repo.key_allows(self.key, args[0], False) or apikeys_repo.key_allows(self.key, args[0], True)):
                raise ApiError(404, "not_found")
            self.ent = await self.application.settings["erp_state"].db.run(entities_repo.get_entity, args[0])
            if self.ent is None:
                raise ApiError(404, "not_found")
        except ApiError as exc:
            self.set_status(exc.status)
            self.finish(json.dumps({"error": exc.code}))
            return
        await super().get(*args, **kwargs)

    def open(self, name: str) -> None:
        state = self.application.settings["erp_state"]
        if self.key["can_read"]:
            state.subscribe(name, self)
        self.write_message(json.dumps({"event": "hello", "entity": name, "read_interval_ms": self.ent.read_interval_ms,
                                       "can_write": self.key["can_write"], "can_read": self.key["can_read"]}))

    async def on_message(self, message) -> None:
        state = self.application.settings["erp_state"]
        ent = self.ent
        try:
            payload = json.loads(message)
            if isinstance(payload, dict) and payload.get("event") in ("config", "ping"):
                current = await state.db.run(entities_repo.get_entity, ent.name)
                interval = current.read_interval_ms if current else ent.read_interval_ms
                self.write_message(json.dumps({"event": "config", "read_interval_ms": interval}))
                return
            if not apikeys_repo.key_allows(self.key, ent.name, True):
                raise ApiError(403, "forbidden")
            items = payload if isinstance(payload, list) else [payload]
            if not items or len(items) > MAX_BATCH or not all(isinstance(i, dict) for i in items):
                raise ApiError(400, "invalid_body")
            self.check_rate()
            prepared = []
            for item in items:
                values, errors = records_repo.validate(ent, records_repo.apply_defaults(ent, item))
                if errors:
                    raise ApiError(422, "validation_failed", details=errors_json(errors))
                prepared.append(values)
            ids = await state.db.run(
                lambda conn: [records_repo.create_record(conn, ent, v, None, self.key["id"]) for v in prepared])
            self.write_message(json.dumps({"event": "stored", "ids": ids}))
            state.publish(ent.name, ids)
        except ApiError as exc:
            self.write_message(json.dumps({"event": "error", "error": exc.code, "details": exc.details}))
        except (ValueError, records_repo.RecordError) as exc:
            details = errors_json(exc.errors) if isinstance(exc, records_repo.RecordError) else {}
            self.write_message(json.dumps({"event": "error", "error": "invalid", "details": details}))

    def on_close(self) -> None:
        if self.ent is not None:
            self.application.settings["erp_state"].unsubscribe(self.ent.name, self)

    async def push(self, ids: list[int]) -> None:
        ent = self.ent
        state = self.application.settings["erp_state"]
        rows = await state.db.run(lambda conn: [records_repo.get_record(conn, ent, i) for i in ids])
        try:
            self.write_message(json.dumps({"event": "created", "records": [record_json(ent, r) for r in rows if r]},
                                          default=json_default))
        except tornado.websocket.WebSocketClosedError:
            pass


class NotFoundApiHandler(ApiHandler):
    async def prepare(self) -> None:
        raise ApiError(404, "not_found")
