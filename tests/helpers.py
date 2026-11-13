"""Test helpers: an HTTP client with cookies and XSRF handling."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode

from tornado.testing import AsyncHTTPTestCase

from erp.app import AppState, make_app

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def db_settings_for_tests() -> dict:
    """Database used by the web tests: SQLite unless ERP_TEST_DB (JSON) is set.

    Example: ERP_TEST_DB='{"db_dialect": "postgresql", "db_name": "erp_test", "db_user": "erp", "db_password": "x"}'
    """
    raw = os.environ.get("ERP_TEST_DB")
    if raw:
        return json.loads(raw)
    return {"db_dialect": "sqlite", "db_name": "test.sqlite3"}


def multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{v}\r\n'.encode())
    for name, (filename, data, ctype) in files.items():
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n").encode()
        parts.append(head + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class WebTestCase(AsyncHTTPTestCase):
    SETUP_TOKEN = "test-token"

    def get_app(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "erp.toml"
        self.state = AppState(self.config_path, setup_token=self.SETUP_TOKEN)
        self.state.load()
        self.cookies: dict[str, str] = {"_xsrf": "testxsrf"}
        return make_app(self.state)

    def tearDown(self):
        db = self.state.db
        if db is not None and os.environ.get("ERP_TEST_DB"):
            # Clean the shared test database for the next test.
            def wipe(conn):
                from erp.repo import entities as entities_repo
                from erp.schema import SYSTEM_TABLES

                for ent in entities_repo.list_entities(conn):
                    conn.execute(conn.dialect.drop_table_sql(ent.table)).close()
                for table in SYSTEM_TABLES:
                    conn.execute(conn.dialect.drop_table_sql(table.name)).close()

            db.run_sync(wipe)
        self.state.close()
        super().tearDown()
        self.tmp.cleanup()

    # ------------------------------------------------------------------ http
    def request(self, method: str, path: str, data: dict | None = None, files: dict | None = None,
                headers: dict | None = None, body: bytes | None = None, follow: bool = False):
        headers = dict(headers or {})
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if method == "POST" and body is None:
            data = dict(data or {})
            data["_xsrf"] = "testxsrf"
            if files:
                body, ctype = multipart(data, files)
            else:
                body = urlencode(data, doseq=True).encode()
                ctype = "application/x-www-form-urlencoded"
            headers["Content-Type"] = ctype
        response = self.fetch(path, method=method, body=body, headers=headers, follow_redirects=False,
                              allow_nonstandard_methods=True)
        for header in response.headers.get_list("Set-Cookie"):
            cookie = SimpleCookie()
            cookie.load(header)
            for key, morsel in cookie.items():
                if morsel.value == "" or 'expires=Thu, 01 Jan 1970' in header or "Max-Age=0" in header:
                    self.cookies.pop(key, None)
                else:
                    self.cookies[key] = morsel.value
        if follow and response.code in (301, 302, 303) and "Location" in response.headers:
            return self.request("GET", response.headers["Location"], follow=True)
        return response

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, data=None, **kw):
        return self.request("POST", path, data, **kw)

    @staticmethod
    def text(response) -> str:
        return response.body.decode("utf-8", "replace")

    # ------------------------------------------------------------------ flows
    def install(self, language: str = "en-US", **overrides) -> None:
        data = {
            "setup_token": self.SETUP_TOKEN, "language": language, "company_name": "Test Ltd",
            "db_host": "", "db_port": "", "db_user": "", "db_password": "", "db_driver": "", "db_odbc_driver": "",
            "admin_username": "admin", "admin_full_name": "Admin", "admin_password": "secret123",
            "admin_password2": "secret123", "default_charset": "utf-8", "timezone": "Europe/Istanbul",
            "default_currency": "TRY", "upload_dir": "uploads",
        }
        data.update(db_settings_for_tests())
        data.update(overrides)
        r = self.post("/setup", data)
        assert r.code == 302, self.text(r)
        assert r.headers["Location"] == "/login"

    def login(self, username: str = "admin", password: str = "secret123") -> None:
        r = self.post("/login", {"username": username, "password": password, "next": "/"})
        assert r.code == 302, self.text(r)
        assert "erp_session" in self.cookies

    def create_entity(self, name: str, label: str, **extra) -> None:
        data = {"name": name, "label": label, "description": "", "menu_id": "", "sort_order": "0",
                "perm_user": "write", "perm_dealer": "none", "read_interval_ms": "5000", "page_size": ""}
        data.update(extra)
        r = self.post("/admin/entities/new", data)
        assert r.code == 302, self.text(r)

    def add_field(self, entity: str, name: str, field_type: str, **extra) -> None:
        data = {"name": name, "label": name.title(), "field_type": field_type, "max_length": "255",
                "decimal_places": "", "ref_entity": "", "currency": "TRY", "options": "", "default_value": "",
                "help_text": "", "sort_order": "", "show_in_list": "1"}
        data.update(extra)
        r = self.post(f"/admin/entities/{entity}/fields/new", data)
        assert r.code == 302, self.text(r)

    def create_api_key(self, name: str = "sensor", **extra) -> str:
        data = {"name": name, "can_read": "1", "can_write": "1", "allowed_ips": "", "min_interval_ms": "0",
                "expires_at": "", "active": "1"}
        data.update(extra)
        r = self.post("/admin/apikeys/new", data)
        assert r.code == 200, self.text(r)
        m = re.search(r'<pre class="token"[^>]*>(erp_[^<]+)</pre>', self.text(r))
        assert m, self.text(r)
        return m.group(1)
