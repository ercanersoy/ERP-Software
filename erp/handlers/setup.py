"""First run installation wizard.

The wizard is only reachable while no instance configuration exists.  It is
protected by a one-time setup token that is printed to the server console.
After a successful installation the application leaves setup mode at once.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from zoneinfo import available_timezones

from .. import charsets, config, schema
from ..db import DIALECTS, Database, get_dialect
from ..fieldtypes import CURRENCIES
from ..i18n import LANGUAGES, get_locale
from ..repo import audit as audit_repo
from ..repo import settings as settings_repo
from ..repo import users as users_repo
from .base import LANG_COOKIE, BaseHandler, FormField

log = logging.getLogger("erp.setup")

DB_FIELDS = ("db_dialect", "db_host", "db_port", "db_name", "db_user", "db_password", "db_driver", "db_odbc_driver")


def common_timezones() -> list[str]:
    zones = sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/", "posix/", "right/")))
    return ["UTC"] + zones


class SetupHandler(BaseHandler):
    allow_in_setup = True
    setup_only = True
    require_login = False

    def fields(self, values: dict, errors: dict) -> list[FormField]:
        t = self.t
        v = lambda k, d="": values.get(k, d)  # noqa: E731
        e = lambda k: t(errors[k]) if k in errors else ""  # noqa: E731
        return [
            FormField("setup_token", t("setup.token"), "password", v("setup_token"), required=True,
                      help=t("setup.token_help"), error=e("setup_token"), attrs={"autocomplete": "off"}),
            FormField("language", t("setup.language"), "select", v("language", self.loc.code),
                      options=list(LANGUAGES.items())),
            FormField("company_name", t("settings.company_name"), "text", v("company_name"), required=True,
                      error=e("company_name")),
            FormField("db_dialect", t("setup.db_dialect"), "select", v("db_dialect", "sqlite"),
                      options=[(d.name, d.title) for d in DIALECTS.values()], help=t("setup.db_dialect_help")),
            FormField("db_host", t("setup.db_host"), "text", v("db_host", "localhost")),
            FormField("db_port", t("setup.db_port"), "number", v("db_port"), help=t("setup.db_port_help")),
            FormField("db_name", t("setup.db_name"), "text", v("db_name", "erp.sqlite3"), required=True,
                      help=t("setup.db_name_help"), error=e("db_name")),
            FormField("db_user", t("setup.db_user"), "text", v("db_user"), attrs={"autocomplete": "off"}),
            FormField("db_password", t("setup.db_password"), "password", v("db_password"),
                      attrs={"autocomplete": "new-password"}),
            FormField("db_driver", t("setup.db_driver"), "text", v("db_driver"), help=t("setup.db_driver_help")),
            FormField("db_odbc_driver", t("setup.db_odbc_driver"), "text",
                      v("db_odbc_driver", "ODBC Driver 18 for SQL Server")),
            FormField("admin_username", t("setup.admin_username"), "text", v("admin_username", "admin"),
                      required=True, error=e("admin_username")),
            FormField("admin_full_name", t("users.full_name"), "text", v("admin_full_name")),
            FormField("admin_password", t("setup.admin_password"), "password", "", required=True,
                      error=e("admin_password"), help=t("users.password_help"),
                      attrs={"autocomplete": "new-password"}),
            FormField("admin_password2", t("setup.admin_password2"), "password", "", required=True,
                      error=e("admin_password2"), attrs={"autocomplete": "new-password"}),
            FormField("default_charset", t("settings.default_charset"), "select", v("default_charset", "utf-8"),
                      options=list(charsets.CHARSETS.items())),
            FormField("timezone", t("settings.timezone"), "select", v("timezone", "Europe/Istanbul"),
                      options=[(z, z) for z in common_timezones()]),
            FormField("default_currency", t("settings.default_currency"), "select", v("default_currency", "TRY"),
                      options=[(c, c) for c in CURRENCIES]),
            FormField("upload_dir", t("setup.upload_dir"), "text", v("upload_dir", "uploads"),
                      help=t("setup.upload_dir_help")),
        ]

    def show(self, values: dict, errors: dict, error: str | None = None, info: str | None = None) -> None:
        self.render(
            "form.html", title=self.t("setup.title"), fields=self.fields(values, errors), crumbs=[],
            action="/setup", submit=self.t("setup.install"), multipart=False, error=error,
            buttons=[("action", "test", self.t("setup.test_connection"))],
            intro=info or self.t("setup.intro"), extra="", cancel_url=None, page_class="setup",
        )

    def get(self) -> None:
        lang = self.get_argument("lang", "")
        if lang in LANGUAGES:
            self.set_cookie(LANG_COOKIE, lang, samesite="Lax")
            self.loc = get_locale(lang)
        self.show({}, {})

    def _db_params(self, values: dict) -> dict:
        dialect = values.get("db_dialect") or "sqlite"
        params = {"dialect": dialect, "name": values.get("db_name", "").strip(), "pool_size": 8}
        if dialect != "sqlite":
            params.update(
                host=values.get("db_host", "").strip() or "localhost",
                port=int(values["db_port"]) if values.get("db_port", "").strip().isdigit() else get_dialect(dialect).default_port,
                user=values.get("db_user", "").strip(),
                password=values.get("db_password", ""),
            )
            if values.get("db_driver", "").strip():
                params["driver"] = values["db_driver"].strip()
            if dialect == "mssql":
                params["odbc_driver"] = values.get("db_odbc_driver", "").strip() or "ODBC Driver 18 for SQL Server"
        return params

    async def post(self) -> None:
        names = [f.name for f in self.fields({}, {})]
        values = {n: self.get_argument(n, "") for n in names}
        if values["language"] in LANGUAGES:
            self.loc = get_locale(values["language"])
            self.set_cookie(LANG_COOKIE, values["language"], samesite="Lax")
        errors: dict[str, str] = {}
        if not hmac.compare_digest(values["setup_token"].strip().encode(), (self.state.setup_token or "").encode()):
            errors["setup_token"] = "setup.token_invalid"
            return self.show(values, errors)
        if not values["db_name"].strip():
            errors["db_name"] = "error.required"
            return self.show(values, errors)

        cfg = config.new_config(self.state.config_path)
        cfg.database = self._db_params(values)
        cfg.storage["upload_dir"] = values["upload_dir"].strip() or "uploads"
        db = Database(get_dialect(cfg.database["dialect"]), cfg.database_params, pool_size=2)
        try:
            version = await asyncio.get_running_loop().run_in_executor(None, db.test)
        except Exception as exc:  # noqa: BLE001 - show any connection problem to the installer
            db.close()
            return self.show(values, errors, error=self.t("setup.connection_failed", error=str(exc)))

        if self.get_argument("action", "") == "test":
            db.close()
            return self.show(values, errors, info=self.t("setup.connection_ok", version=version))

        username = users_repo.normalize_username(values["admin_username"])
        if not users_repo.valid_username(username):
            errors["admin_username"] = "error.invalid_username"
        if len(values["admin_password"]) < users_repo.MIN_PASSWORD_LENGTH:
            errors["admin_password"] = "error.password_too_short"
        elif values["admin_password"] != values["admin_password2"]:
            errors["admin_password2"] = "error.password_mismatch"
        if not values["company_name"].strip():
            errors["company_name"] = "error.required"
        if errors:
            db.close()
            return self.show(values, errors)

        def install(conn):
            existing = schema.is_installed(conn)
            if existing:
                schema.migrate(conn)
            else:
                schema.install_schema(conn)
            created = False
            if users_repo.count_users(conn) == 0:
                users_repo.create_user(conn, username, values["admin_password"], "admin",
                                       values["admin_full_name"], language=values["language"])
                created = True
            if not existing:
                settings_repo.save_settings(conn, {
                    "company_name": values["company_name"].strip(),
                    "default_language": values["language"] if values["language"] in LANGUAGES else "tr-TR",
                    "default_charset": charsets.normalize(values["default_charset"]),
                    "timezone": values["timezone"] or "UTC",
                    "default_currency": values["default_currency"] or "TRY",
                })
            audit_repo.log(conn, None, "install", values["company_name"].strip(),
                           "existing database" if existing else "new database")
            return existing, created

        try:
            existing, created = await asyncio.get_running_loop().run_in_executor(None, db.run_sync, install)
        except Exception as exc:  # noqa: BLE001
            log.exception("installation failed")
            return self.show(values, errors, error=self.t("setup.install_failed", error=str(exc)))
        finally:
            db.close()

        cfg.save()
        self.state.activate(cfg)
        log.info("Installation finished; setup mode is closed.")
        message = self.t("setup.done")
        if existing and not created:
            message += " " + self.t("setup.done_existing")
        self.loc = get_locale(values["language"])
        self.flash(message)
        self.redirect("/login")
