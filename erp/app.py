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


class AppState:
    """Mutable state shared by all handlers of one server process."""

    def __init__(self, config_path: Path, setup_token: str | None = None):
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
        return self.db is not None

    def load(self) -> None:
        cfg = config.load(self.config_path)
        if cfg is None:
            self.setup_token = self.setup_token or os.environ.get("ERP_SETUP_TOKEN") or secrets.token_urlsafe(12)
            return
        self.activate(cfg, migrate=True)

    def activate(self, cfg: config.InstanceConfig, migrate: bool = False) -> None:
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
        self.subscribers.setdefault(entity, set()).add(handler)

    def unsubscribe(self, entity: str, handler) -> None:
        self.subscribers.get(entity, set()).discard(handler)

    def publish(self, entity: str, ids: list[int]) -> None:
        for handler in list(self.subscribers.get(entity, ())):
            tornado.ioloop.IOLoop.current().spawn_callback(handler.push, ids)

    def close(self) -> None:
        if self.db is not None:
            self.db.close()


def routes() -> list:
    return [
        (r"/setup", setup.SetupHandler),
        (r"/login", auth.LoginHandler),
        (r"/logout", auth.LogoutHandler),
        (r"/lang/(tr-TR|en-US|en-GB)", auth.LanguageHandler),
        (r"/account", auth.AccountHandler),
        (r"/", menus.MenuHandler),
        (r"/menu/(\d+)", menus.MenuHandler),
        (r"/help", menus.HelpHandler),
        (r"/help/([A-Za-z0-9_-]+)", menus.HelpHandler),
        # data screens
        (rf"/data/{NAME}", data.RecordListHandler),
        (rf"/data/{NAME}/new", data.RecordFormHandler),
        (rf"/data/{NAME}/monitor", data.MonitorHandler),
        (rf"/data/{NAME}/latest\.json", data.LatestJsonHandler),
        (rf"/data/{NAME}/export", data.EntityExportHandler),
        (rf"/data/{NAME}/import", data.EntityImportHandler),
        (rf"/data/{NAME}/(\d+)", data.RecordViewHandler),
        (rf"/data/{NAME}/(\d+)/edit", data.RecordFormHandler),
        (rf"/data/{NAME}/(\d+)/delete", data.RecordDeleteHandler),
        (r"/files/(\d+)(?:/[^/]*)?", files.FileHandler),
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
        (r"/admin/menus/(\d+)", admin.MenuFormHandler),
        (r"/admin/menus/(\d+)/delete", admin.MenuDeleteHandler),
        (r"/admin/users", admin.UserListHandler),
        (r"/admin/users/new", admin.UserFormHandler),
        (r"/admin/users/(\d+)", admin.UserFormHandler),
        (r"/admin/users/(\d+)/delete", admin.UserDeleteHandler),
        (r"/admin/apikeys", admin.ApiKeyListHandler),
        (r"/admin/apikeys/new", admin.ApiKeyFormHandler),
        (r"/admin/apikeys/(\d+)", admin.ApiKeyFormHandler),
        (r"/admin/apikeys/(\d+)/delete", admin.ApiKeyDeleteHandler),
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
        (rf"/api/v1/entities/{NAME}/records/(\d+)", api.RecordHandler),
        (rf"/api/v1/entities/{NAME}/latest", api.LatestHandler),
        (r"/api/v1/files", api.FileUploadHandler),
        (r"/api/v1/files/(\d+)", api.FileDownloadHandler),
        (rf"/api/v1/stream/{NAME}", api.StreamHandler),
        (r"/api/.*", api.NotFoundApiHandler),
    ]


def make_app(state: AppState, debug: bool = False) -> tornado.web.Application:
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
    p = argparse.ArgumentParser(prog="erp", description=f"{APP_NAME} {__version__}")
    p.add_argument("--config", help="instance configuration file (default: instance/erp.toml or $ERP_CONFIG)")
    p.add_argument("--host", help="address to listen on (default: from configuration or 127.0.0.1)")
    p.add_argument("--port", type=int, help="port to listen on (default: from configuration or 8888)")
    p.add_argument("--debug", action="store_true", help="development mode with detailed errors")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p.parse_args(argv)


async def serve(args: argparse.Namespace) -> None:
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
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
