"""Download and streaming of uploaded documents, images and videos."""

from __future__ import annotations

import urllib.parse

import tornado.web

from ..repo import entities as entities_repo
from ..repo import files as files_repo
from .base import BaseHandler


def content_disposition(kind: str, filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    quoted = urllib.parse.quote(filename, safe="")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


async def file_access(handler: BaseHandler, file_id: int, user: dict) -> dict:
    def load(conn):
        row = files_repo.get_file(conn, file_id)
        ent = entities_repo.get_entity(conn, row["entity"]) if row and row["entity"] else None
        return row, ent

    row, ent = await handler.db(load)
    if row is None:
        raise tornado.web.HTTPError(404)
    if user["role"] != "admin":
        if ent is None:
            if row["created_by"] != user["id"]:
                raise tornado.web.HTTPError(404)
        elif not ent.can_read(user):
            raise tornado.web.HTTPError(403)
        elif ent.owner_filter(user) is not None and row["created_by"] != user["id"]:
            raise tornado.web.HTTPError(404)
    return row


class FileHandler(BaseHandler, tornado.web.StaticFileHandler):
    """Serves a stored file after checking access; supports HTTP range requests."""

    file_row: dict

    def initialize(self, path: str = "", default_filename: str | None = None) -> None:
        tornado.web.StaticFileHandler.initialize(self, path or ".", default_filename)

    async def get(self, file_id: str, include_body: bool = True) -> None:  # type: ignore[override]
        self.file_row = await file_access(self, int(file_id), self.user)
        self.root = self.state.config.upload_dir
        key = self.file_row["storage_key"]
        disposition = "attachment" if self.file_row["kind"] == "document" or self.get_argument("download", "") else "inline"
        self.set_header("Content-Disposition", content_disposition(disposition, self.file_row["original_name"]))
        await tornado.web.StaticFileHandler.get(self, f"{key[:2]}/{key}", include_body)

    async def head(self, file_id: str) -> None:  # type: ignore[override]
        await self.get(file_id, include_body=False)

    def get_content_type(self) -> str:
        return self.file_row["mime_type"]

    def set_extra_headers(self, path: str) -> None:
        self.set_header("Cache-Control", "private, max-age=3600")
        self.set_header("Content-Security-Policy", "default-src 'none'; sandbox")

    def write_error(self, status_code: int, **kwargs) -> None:
        BaseHandler.write_error(self, status_code, **kwargs)
