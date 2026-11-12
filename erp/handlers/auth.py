"""Login, logout and the user's own account settings."""

from __future__ import annotations

import asyncio
import time

from ..i18n import LANGUAGES, get_locale
from ..repo import users as users_repo
from .base import LANG_COOKIE, SESSION_COOKIE, BaseHandler, FormField

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


class LoginHandler(BaseHandler):
    require_login = False

    def show(self, username: str = "", error: str | None = None) -> None:
        self.render("login.html", title=self.t("login.title"), username=username, error=error,
                    next_url=self.safe_next(), crumbs=[])

    def get(self) -> None:
        lang = self.get_argument("lang", "")
        if lang in LANGUAGES:
            self.set_cookie(LANG_COOKIE, lang, samesite="Lax", expires_days=365)
            self.loc = get_locale(lang, self.cfg.get("timezone", "UTC"))
        if self.user:
            self.redirect(self.safe_next())
            return
        self.show()

    def _throttle_key(self, username: str) -> str:
        return f"{self.request.remote_ip}|{username}"

    async def post(self) -> None:
        username = users_repo.normalize_username(self.get_argument("username", ""))
        password = self.get_argument("password", "")
        failures = self.state.login_failures
        key = self._throttle_key(username)
        count, since = failures.get(key, (0, time.monotonic()))
        if count >= MAX_FAILURES and time.monotonic() - since < LOCK_SECONDS:
            return self.show(username, self.t("login.locked", minutes=LOCK_SECONDS // 60))
        user = await self.db(users_repo.authenticate, username, password)
        if user is None:
            if time.monotonic() - since >= LOCK_SECONDS:
                count, since = 0, time.monotonic()
            failures[key] = (count + 1, since)
            await asyncio.sleep(0.5)
            return self.show(username, self.t("login.failed"))
        failures.pop(key, None)
        hours = int(self.cfg.get("session_hours") or 12)
        token = await self.db(users_repo.create_session, user["id"], hours, self.request.remote_ip,
                              self.request.headers.get("User-Agent", ""))
        self.user = user
        await self.audit("login", user["username"])
        self.set_session_cookie(token, hours)
        if user.get("language") in LANGUAGES:
            self.set_cookie(LANG_COOKIE, user["language"], samesite="Lax", expires_days=365)
        self.redirect(self.safe_next())


class LogoutHandler(BaseHandler):
    require_login = False

    def get(self) -> None:
        if not self.user:
            self.redirect("/login")
            return
        self.render("confirm.html", title=self.t("menu.logout"), message=self.t("login.logout_confirm"),
                    action="/logout", button=self.t("menu.logout"), crumbs=self.crumbs((self.t("menu.logout"), "/logout")),
                    danger=False)

    async def post(self) -> None:
        raw = self.get_signed_cookie(SESSION_COOKIE, max_age_days=31)
        if raw:
            await self.db(users_repo.delete_session, raw.decode())
        if self.user:
            await self.audit("logout", self.user["username"])
        self.clear_cookie(SESSION_COOKIE)
        self.redirect("/login")


class AccountHandler(BaseHandler):
    """The user's own preferences: language, name, e-mail and password."""

    def fields(self, values: dict, errors: dict) -> list[FormField]:
        t = self.t
        e = lambda k: t(errors[k]) if k in errors else ""  # noqa: E731
        return [
            FormField("username", t("users.username"), "static", self.user["username"]),
            FormField("role", t("users.role"), "static", t(f"role.{self.user['role']}")),
            FormField("full_name", t("users.full_name"), "text", values.get("full_name", self.user.get("full_name") or "")),
            FormField("email", t("users.email"), "email", values.get("email", self.user.get("email") or "")),
            FormField("language", t("account.language"), "select",
                      values.get("language", self.user.get("language") or self.loc.code),
                      options=list(LANGUAGES.items())),
            FormField("current_password", t("account.current_password"), "password", "",
                      help=t("account.password_help"), error=e("current_password"),
                      attrs={"autocomplete": "current-password"}),
            FormField("new_password", t("account.new_password"), "password", "", error=e("new_password"),
                      help=t("users.password_help"), attrs={"autocomplete": "new-password"}),
            FormField("new_password2", t("account.new_password2"), "password", "", error=e("new_password2"),
                      attrs={"autocomplete": "new-password"}),
        ]

    def show(self, values=None, errors=None, error=None) -> None:
        self.form_page(self.t("menu.account"), self.fields(values or {}, errors or {}),
                       self.crumbs((self.t("menu.account"), "/account")), error=error)

    def get(self) -> None:
        self.show()

    async def post(self) -> None:
        values = {k: self.get_argument(k, "") for k in ("full_name", "email", "language", "current_password",
                                                       "new_password", "new_password2")}
        errors: dict[str, str] = {}
        if values["new_password"]:
            if not users_repo.verify_password(values["current_password"], self.user["password_hash"]):
                errors["current_password"] = "error.wrong_password"
            elif len(values["new_password"]) < users_repo.MIN_PASSWORD_LENGTH:
                errors["new_password"] = "error.password_too_short"
            elif values["new_password"] != values["new_password2"]:
                errors["new_password2"] = "error.password_mismatch"
        if errors:
            return self.show(values, errors)
        language = values["language"] if values["language"] in LANGUAGES else ""
        await self.db(users_repo.update_user, self.user["id"], {
            "full_name": values["full_name"].strip()[:200], "email": values["email"].strip()[:200],
            "language": language,
        })
        if language:
            self.set_cookie(LANG_COOKIE, language, samesite="Lax", expires_days=365)
            self.loc = get_locale(language, self.cfg.get("timezone", "UTC"))
        if values["new_password"]:
            await self.db(users_repo.set_password, self.user["id"], values["new_password"])
            await self.audit("password_change", self.user["username"])
            hours = int(self.cfg.get("session_hours") or 12)
            token = await self.db(users_repo.create_session, self.user["id"], hours, self.request.remote_ip,
                                  self.request.headers.get("User-Agent", ""))
            self.set_session_cookie(token, hours)
        self.flash(self.t("common.saved"))
        self.redirect("/account")


class LanguageHandler(BaseHandler):
    """Quick language switch: ``/lang/<code>`` (GET from the header links)."""

    require_login = False

    async def get(self, code: str) -> None:
        if code not in LANGUAGES:
            self.redirect("/")
            return
        self.set_cookie(LANG_COOKIE, code, samesite="Lax", expires_days=365)
        if self.user:
            await self.db(users_repo.update_user, self.user["id"], {"language": code})
        self.redirect(self.safe_next())
