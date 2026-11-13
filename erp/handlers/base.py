"""Common request handler code: sessions, roles, languages, rendering."""

from __future__ import annotations

import http.client
import json
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any

import tornado.httputil
import tornado.web

from ..i18n import LANGUAGES, from_accept_language, get_locale, normalize_language
from ..repo import audit as audit_repo
from ..repo import settings as settings_repo
from ..repo import users as users_repo

log = logging.getLogger("erp.web")

SESSION_COOKIE = "erp_session"
LANG_COOKIE = "erp_lang"
FLASH_COOKIE = "erp_flash"


@dataclass
class FormField:
    """Description of one control of a generic form (see ``form.html``)."""

    name: str
    label: str
    type: str = "text"  # text password number email textarea select checkbox checkboxes date
    #                     datetime-local file hidden static
    value: Any = None
    options: list[tuple[str, str]] = field(default_factory=list)
    required: bool = False
    help: str = ""
    error: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    current: dict | None = None  # current file for file inputs
    suffix: str = ""

    @property
    def values(self) -> set[str]:
        if isinstance(self.value, (list, set, tuple)):
            return {str(v) for v in self.value}
        return {str(self.value)} if self.value not in (None, "") else set()


class BaseHandler(tornado.web.RequestHandler):
    #: handler is reachable while the application is not installed yet
    allow_in_setup = False
    #: handler is only reachable while the application is not installed
    setup_only = False
    #: a logged in user is required
    require_login = True
    #: roles allowed to use the handler (``None`` = every role)
    roles: tuple[str, ...] | None = None

    user: dict | None = None
    cfg: dict[str, str] = {}

    @property
    def state(self):
        return self.application.settings["erp_state"]

    def set_default_headers(self) -> None:
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")
        self.set_header("Referrer-Policy", "same-origin")
        self.set_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; "
            "script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        self.set_header("Cache-Control", "no-store")

    # ------------------------------------------------------------------ setup
    async def prepare(self) -> None:
        self.cfg = dict(settings_repo.DEFAULT_SETTINGS)
        if not self.state.installed:
            self.loc = get_locale(self._language_from_request(self.cfg["default_language"]))
            if not self.allow_in_setup:
                self.redirect("/setup")
            return
        if self.setup_only:
            raise tornado.web.HTTPError(404)
        token = self.get_signed_cookie(SESSION_COOKIE, max_age_days=31)
        token = token.decode() if token else None

        def load(conn):
            settings = settings_repo.get_settings(conn)
            user = users_repo.session_user(conn, token) if token else None
            return settings, user

        self.cfg, self.user = await self.db(load)
        lang = (self.user or {}).get("language") or self._language_from_request(self.cfg["default_language"])
        self.loc = get_locale(normalize_language(lang, self.cfg["default_language"]), self.cfg.get("timezone", "UTC"))
        if self.require_login and self.user is None:
            if self.request.method in ("GET", "HEAD"):
                self.redirect(self.get_login_url() + "?" + tornado.httputil.urlencode({"next": self.request.uri}))
                return
            raise tornado.web.HTTPError(403)
        if self.roles is not None and (self.user is None or self.user["role"] not in self.roles):
            raise tornado.web.HTTPError(403)

    def _language_from_request(self, default: str) -> str:
        cookie = self.get_cookie(LANG_COOKIE)
        if cookie in LANGUAGES:
            return cookie
        return from_accept_language(self.request.headers.get("Accept-Language"), default)

    def get_current_user(self):
        return self.user

    async def db(self, fn, *args, **kwargs):
        return await self.state.db.run(fn, *args, **kwargs)

    def t(self, key: str, **params) -> str:
        return self.loc.t(key, **params)

    def is_admin(self) -> bool:
        return bool(self.user) and self.user["role"] == "admin"

    async def audit(self, action: str, target: str = "", detail: str = "") -> None:
        await self.db(audit_repo.log, self.user, action, target, detail)

    # ------------------------------------------------------------------ cookies
    def set_session_cookie(self, token: str, hours: int) -> None:
        self.set_signed_cookie(
            SESSION_COOKIE, token, expires_days=max(hours, 1) / 24, httponly=True, samesite="Lax",
            secure=self.request.protocol == "https",
        )

    def flash(self, message: str, kind: str = "ok") -> None:
        self.set_signed_cookie(FLASH_COOKIE, json.dumps([kind, message]), expires_days=None, httponly=True,
                               samesite="Lax", secure=self.request.protocol == "https")

    def pop_flash(self) -> tuple[str, str] | None:
        raw = self.get_signed_cookie(FLASH_COOKIE, max_age_days=1)
        if not raw:
            return None
        self.clear_cookie(FLASH_COOKIE)
        try:
            kind, message = json.loads(raw)
            return str(kind), str(message)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------ rendering
    def get_template_namespace(self) -> dict:
        ns = super().get_template_namespace()
        loc = getattr(self, "loc", None) or get_locale("en-US")
        ns.update(
            t=loc.t,
            loc=loc,
            user=self.user,
            cfg=self.cfg,
            languages=LANGUAGES,
            installed=self.state.installed,
            json_attr=lambda v: json.dumps(v, ensure_ascii=False),
        )
        return ns

    def render(self, template_name: str, **kwargs) -> None:
        kwargs.setdefault("crumbs", [])
        kwargs.setdefault("title", "")
        if "flash" not in kwargs:
            kwargs["flash"] = self.pop_flash()
        kwargs.setdefault("back_url", kwargs["crumbs"][-2][1] if len(kwargs["crumbs"]) > 1 else None)
        kwargs.setdefault("page_class", "")
        for key, default in (("sort_base", None), ("sort", None), ("desc", True), ("base_url", None),
                             ("description", ""), ("notice", None), ("actions", []), ("empty", ""),
                             ("confirm_input", None), ("danger", False), ("intro", ""), ("extra", "")):
            kwargs.setdefault(key, default)
        super().render(template_name, **kwargs)

    def crumbs(self, *items: tuple[str, str]) -> list[tuple[str, str]]:
        return [(self.t("menu.main"), "/")] + list(items)

    def form_page(self, title: str, fields: list[FormField], crumbs, *, action: str | None = None,
                  submit: str | None = None, buttons: list[tuple[str, str, str]] | None = None,
                  multipart: bool = False, error: str | None = None, intro: str = "", extra: str = "",
                  cancel_url: str | None = None) -> None:
        self.render(
            "form.html", title=title, fields=fields, crumbs=crumbs, action=action or self.request.path,
            submit=submit or self.t("common.save"), buttons=buttons or [], multipart=multipart,
            error=error, intro=intro, extra=extra,
            cancel_url=cancel_url or (crumbs[-2][1] if len(crumbs) > 1 else "/"),
        )

    def message_page(self, title: str, message: str, crumbs, *, code: str | None = None,
                     links: list[tuple[str, str]] | None = None) -> None:
        self.render("message.html", title=title, message=message, code=code, crumbs=crumbs,
                    links=links or [])

    def write_error(self, status_code: int, **kwargs) -> None:
        reason = self._reason or http.client.responses.get(status_code, "Error")
        detail = ""
        if self.settings.get("serve_traceback") and "exc_info" in kwargs:
            detail = "".join(traceback.format_exception(*kwargs["exc_info"]))
        if not hasattr(self, "loc"):
            self.loc = get_locale("en-US")
        key = {403: "error.forbidden", 404: "error.not_found", 413: "error.too_large"}.get(status_code)
        message = self.t(key) if key else reason
        try:
            self.render("error.html", title=f"{status_code}", message=message, detail=detail,
                        crumbs=self.crumbs() if self.user else [], flash=None)
        except Exception:  # pragma: no cover - last resort
            self.finish(f"{status_code} {reason}")

    # ------------------------------------------------------------------ args
    def int_arg(self, name: str, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
        try:
            value = int(self.get_argument(name, str(default)))
        except ValueError:
            value = default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def bool_arg(self, name: str) -> bool:
        return self.get_argument(name, "") in ("1", "on", "true", "yes")

    def safe_next(self, default: str = "/") -> str:
        nxt = self.get_argument("next", default)
        if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
            return default
        return nxt


class NotFoundHandler(BaseHandler):
    require_login = False
    allow_in_setup = True

    async def prepare(self) -> None:
        await super().prepare()
        if self._finished:
            return
        raise tornado.web.HTTPError(404)


def page_window(total: int, page: int, size: int) -> tuple[int, int, int]:
    """Return ``(pages, page, offset)`` with ``page`` clamped to the valid range."""
    pages = max(1, (total + size - 1) // size)
    page = min(max(1, page), pages)
    return pages, page, (page - 1) * size

