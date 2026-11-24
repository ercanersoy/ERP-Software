"""Application state, URL routes and server start-up."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
from pathlib import Path

import tornado.httpserver
import tornado.ioloop
import tornado.web

from . import APP_NAME, __version__, config, schema
from .db import Database, get_dialect
from .handlers import admin, api, auth, data, files, menus, setup
from .handlers.base import NotFoundHandler

log = logging.getLogger("erp")
BASE_DIR = Path(__file__).resolve().parent
NAME = r"([a-z][a-z0-9_]{0,49})"
#: Numeric ids in URLs.  At most 18 digits, so every matching id fits into the
#: signed 64 bit integer columns (longer numbers simply do not match: 404).
ID = r"(\d{1,18})"


class AppState:
    """Mutable state shared by all handlers of one server process."""

    def __init__(self, config_path: Path, setup_token: str | None = None):
        """Create an empty state; :meth:`load` fills it from the configuration file.

        ``login_failures`` maps "ip|username" to ``(failures, first failure time)``
        for the login throttle, ``api_last_write`` maps an API key id to the
        monotonic time of its last write (rate limit), and ``subscribers`` maps an
        entity name to the WebSocket handlers that want its new records.
        """
        self.config_path = Path(config_path)
        self.config: config.InstanceConfig | None = None
        self.db: Database | None = None
        self.setup_token = setup_token
        self.login_failures: dict[str, tuple[int, float]] = {}
        self.api_last_write: dict[int, float] = {}
        self.subscribers: dict[str, set] = {}
        self.app: tornado.web.Application | None = None

    @property
    def installed(self) -> bool:
        """True once a database is connected, i.e. the setup wizard has run."""
        return self.db is not None

    def load(self) -> None:
        """Read the configuration file at start-up.

        Without a file the program stays in setup mode and needs a setup token:
        the one given to the constructor, ``$ERP_SETUP_TOKEN`` or a random one
        (printed to the console by :func:`serve`).
        """
        cfg = config.load(self.config_path)
        if cfg is None:
            self.setup_token = self.setup_token or os.environ.get("ERP_SETUP_TOKEN") or secrets.token_urlsafe(12)
            return
        self.activate(cfg, migrate=True)

    def activate(self, cfg: config.InstanceConfig, migrate: bool = False) -> None:
        """Connect to the configured database and leave setup mode.

        Called at start-up (with ``migrate=True``, so older installations are
        brought up to date) and by the setup wizard right after installation, so
        no restart is needed.  The cookie secret of the running application is
        replaced by the one of the new configuration.
        """
        params = cfg.database_params
        db = Database(get_dialect(params.get("dialect", "sqlite")), params, int(params.get("pool_size") or 8))
        if migrate:
            db.run_sync(schema.migrate)
        Path(cfg.upload_dir).mkdir(parents=True, exist_ok=True)
        self.config = cfg
        self.db = db
        self.setup_token = None
        if self.app is not None:
            self.app.settings["cookie_secret"] = cfg.cookie_secret

    # ---------------------------------------------------------------- live data
    def subscribe(self, entity: str, handler) -> None:
        """Register a WebSocket ``handler`` for new records of ``entity``."""
        self.subscribers.setdefault(entity, set()).add(handler)

    def unsubscribe(self, entity: str, handler) -> None:
        """Remove a WebSocket ``handler``; unknown handlers are ignored."""
        self.subscribers.get(entity, set()).discard(handler)

    def publish(self, entity: str, ids: list[int]) -> None:
        """Tell every subscriber of ``entity`` about the new record ``ids``.

        Each ``handler.push(ids)`` runs as its own callback on the event loop, so a
        slow client never delays the request that created the records.
        """
        for handler in list(self.subscribers.get(entity, ())):
            tornado.ioloop.IOLoop.current().spawn_callback(handler.push, ids)

    def close(self) -> None:
        """Close the database connections (server shutdown)."""
        if self.db is not None:
            self.db.close()


def routes() -> list:
    """URL routes of the application.

    ``NAME`` matches technical entity and field names, ``ID`` numeric ids.
    The order matters only for ``/api/.*``, the catch-all of the REST API,
    which must come last.
    """
    return [
        (r"/setup", setup.SetupHandler),
        (r"/login", auth.LoginHandler),
        (r"/logout", auth.LogoutHandler),
        (r"/lang/(tr-TR|en-US|en-GB)", auth.LanguageHandler),
        (r"/account", auth.AccountHandler),
        (r"/", menus.MenuHandler),
        (rf"/menu/{ID}", menus.MenuHandler),
        (r"/help", menus.HelpHandler),
        (r"/help/([A-Za-z0-9_-]+)", menus.HelpHandler),
        # data screens
        (rf"/data/{NAME}", data.RecordListHandler),
        (rf"/data/{NAME}/new", data.RecordFormHandler),
        (rf"/data/{NAME}/monitor", data.MonitorHandler),
        (rf"/data/{NAME}/latest\.json", data.LatestJsonHandler),
        (rf"/data/{NAME}/export", data.EntityExportHandler),
        (rf"/data/{NAME}/import", data.EntityImportHandler),
        (rf"/data/{NAME}/{ID}", data.RecordViewHandler),
        (rf"/data/{NAME}/{ID}/edit", data.RecordFormHandler),
        (rf"/data/{NAME}/{ID}/delete", data.RecordDeleteHandler),
        (rf"/files/{ID}(?:/[^/]*)?", files.FileHandler),
        # administration
        (r"/admin", menus.AdminMenuHandler),
        (r"/admin/entities", admin.EntityListHandler),
        (r"/admin/entities/new", admin.EntityFormHandler),
        (rf"/admin/entities/{NAME}", admin.EntityDetailHandler),
        (rf"/admin/entities/{NAME}/edit", admin.EntityFormHandler),
        (rf"/admin/entities/{NAME}/delete", admin.EntityDeleteHandler),
        (rf"/admin/entities/{NAME}/fields/new", admin.FieldFormHandler),
        (rf"/admin/entities/{NAME}/fields/{NAME}", admin.FieldFormHandler),
        (rf"/admin/entities/{NAME}/fields/{NAME}/delete", admin.FieldDeleteHandler),
        (r"/admin/menus", admin.MenuListHandler),
        (r"/admin/menus/new", admin.MenuFormHandler),
        (rf"/admin/menus/{ID}", admin.MenuFormHandler),
        (rf"/admin/menus/{ID}/delete", admin.MenuDeleteHandler),
        (r"/admin/users", admin.UserListHandler),
        (r"/admin/users/new", admin.UserFormHandler),
        (rf"/admin/users/{ID}", admin.UserFormHandler),
        (rf"/admin/users/{ID}/delete", admin.UserDeleteHandler),
        (r"/admin/apikeys", admin.ApiKeyListHandler),
        (r"/admin/apikeys/new", admin.ApiKeyFormHandler),
        (rf"/admin/apikeys/{ID}", admin.ApiKeyFormHandler),
        (rf"/admin/apikeys/{ID}/delete", admin.ApiKeyDeleteHandler),
        (r"/admin/settings", admin.SettingsHandler),
        (r"/admin/backup", menus.BackupMenuHandler),
        (r"/admin/backup/(config|schema|data|full)", admin.BackupHandler),
        (r"/admin/restore", admin.RestoreHandler),
        (r"/admin/audit", admin.AuditHandler),
        (r"/admin/system", admin.SystemHandler),
        (r"/admin/system/cleanup", admin.CleanupHandler),
        # REST API
        (r"/api/v1/ping", api.PingHandler),
        (r"/api/v1/entities", api.EntitiesHandler),
        (rf"/api/v1/entities/{NAME}", api.EntitySchemaHandler),
        (rf"/api/v1/entities/{NAME}/config", api.EntityConfigHandler),
        (rf"/api/v1/entities/{NAME}/records", api.RecordsHandler),
        (rf"/api/v1/entities/{NAME}/records/{ID}", api.RecordHandler),
        (rf"/api/v1/entities/{NAME}/latest", api.LatestHandler),
        (r"/api/v1/files", api.FileUploadHandler),
        (rf"/api/v1/files/{ID}", api.FileDownloadHandler),
        (rf"/api/v1/stream/{NAME}", api.StreamHandler),
        (r"/api/.*", api.NotFoundApiHandler),
    ]


def make_app(state: AppState, debug: bool = False) -> tornado.web.Application:
    """Create the Tornado application for ``state``.

    XSRF protection is on for all forms (the REST API switches it off, it uses
    API keys instead of cookies).  Before installation a temporary random
    cookie secret is used; :meth:`AppState.activate` replaces it.
    """
    cookie_secret = state.config.cookie_secret if state.config else secrets.token_urlsafe(48)
    app = tornado.web.Application(
        routes(),
        template_path=str(BASE_DIR / "templates"),
        static_path=str(BASE_DIR / "static"),
        cookie_secret=cookie_secret,
        xsrf_cookies=True,
        xsrf_cookie_kwargs={"httponly": True, "samesite": "Lax"},
        login_url="/login",
        default_handler_class=NotFoundHandler,
        compress_response=True,
        debug=debug,
        autoreload=False,
        erp_state=state,
        websocket_ping_interval=30,
    )
    state.app = app
    return app


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line options (see ``python3 -m erp --help``)."""
    p = argparse.ArgumentParser(prog="erp", description=f"{APP_NAME} {__version__}")
    p.add_argument("--config", help="instance configuration file (default: instance/erp.toml or $ERP_CONFIG)")
    p.add_argument("--host", help="address to listen on (default: from configuration or 127.0.0.1)")
    p.add_argument("--port", type=int, help="port to listen on (default: from configuration or 8888)")
    p.add_argument("--debug", action="store_true", help="development mode with detailed errors")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p.parse_args(argv)


async def serve(args: argparse.Namespace) -> None:
    """Start the HTTP(S) server and run until the process is stopped.

    The listening address and port come from the command line, else from the
    ``[server]`` table of the configuration, else 127.0.0.1:8888.  HTTPS is used
    when ``certfile`` and ``keyfile`` are configured.  The maximum request size
    follows ``max_upload_mb`` so large videos can be uploaded.
    """
    state = AppState(config.config_path(args.config))
    state.load()
    app = make_app(state, debug=args.debug)
    server_cfg = state.config.server if state.config else {}
    host = args.host or server_cfg.get("address") or "127.0.0.1"
    port = args.port or int(server_cfg.get("port") or 8888)
    ssl_options = None
    if server_cfg.get("certfile") and server_cfg.get("keyfile"):
        import ssl

        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(server_cfg["certfile"], server_cfg["keyfile"])
        ssl_options = ctx
    max_body = state.config.max_upload_bytes if state.config else 256 * 1024 * 1024
    server = tornado.httpserver.HTTPServer(app, xheaders=bool(server_cfg.get("xheaders")), ssl_options=ssl_options,
                                           max_body_size=max_body, max_buffer_size=max_body)
    server.listen(port, address=host)
    scheme = "https" if ssl_options else "http"
    log.info("%s %s listening on %s://%s:%s", APP_NAME, __version__, scheme, host, port)
    if not state.installed:
        log.warning("Setup mode: open %s://%s:%s/setup", scheme, host, port)
        log.warning("Setup token: %s", state.setup_token)
    try:
        await asyncio.Event().wait()
    finally:
        server.stop()
        state.close()


def main(argv=None) -> None:
    """Console entry point (``erp-software`` / ``python3 -m erp``)."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
