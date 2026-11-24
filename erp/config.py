"""Instance configuration file (``erp.toml``) written by the setup wizard.

The file holds what is needed before the database can be reached: server
options, the database connection and the upload directory.  Everything else
is stored in the database.
"""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import tomlwriter

DEFAULT_PATH = Path("instance") / "erp.toml"


@dataclass
class InstanceConfig:
    """Contents of ``erp.toml``.

    ``server``: address, port, cookie_secret, max_upload_mb, certfile, keyfile,
    xheaders; ``database``: dialect, name, host, port, user, password, driver,
    pool_size; ``storage``: upload_dir.  Relative paths are relative to the
    directory of the configuration file, not to the working directory.
    """
    path: Path
    server: dict = field(default_factory=dict)
    database: dict = field(default_factory=dict)
    storage: dict = field(default_factory=dict)

    @property
    def base_dir(self) -> Path:
        """Directory of the configuration file; relative paths are resolved against it."""
        return self.path.resolve().parent

    def resolve(self, value: str) -> str:
        """Make ``value`` absolute, relative to :attr:`base_dir`."""
        p = Path(value)
        return str(p if p.is_absolute() else (self.base_dir / p))

    @property
    def upload_dir(self) -> str:
        """Absolute path of the directory that holds uploaded files."""
        return self.resolve(self.storage.get("upload_dir") or "uploads")

    @property
    def database_params(self) -> dict:
        """Connection parameters; the file name of an SQLite database is made absolute."""
        params = dict(self.database)
        if params.get("dialect") == "sqlite" and params.get("name") not in (None, "", ":memory:"):
            params["name"] = self.resolve(params["name"])
        return params

    @property
    def cookie_secret(self) -> str:
        """Secret used to sign the session, language and flash cookies."""
        return self.server.get("cookie_secret") or ""

    @property
    def max_upload_bytes(self) -> int:
        """Largest accepted request body in bytes (default 256 MB)."""
        return int(self.server.get("max_upload_mb") or 256) * 1024 * 1024

    def to_dict(self) -> dict:
        """The configuration as a dictionary, ready for the TOML writer."""
        return {"server": self.server, "database": self.database, "storage": self.storage}

    def save(self) -> None:
        """Write the file atomically and readable only by its owner (mode 0600).

        The text is first written to ``erp.tmp`` and then renamed, so a crash can
        never leave a half written configuration behind.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = tomlwriter.dumps(
            self.to_dict(),
            comments=[
                "ERP-Software instance configuration.",
                "Written by the setup wizard. Delete this file to run the setup wizard again.",
                "Keep it private: it contains the database password and the cookie secret.",
            ],
        )
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self.path)


def config_path(explicit: str | None = None) -> Path:
    """Configuration file to use: the ``--config`` option, ``$ERP_CONFIG`` or ``instance/erp.toml``."""
    return Path(explicit or os.environ.get("ERP_CONFIG") or DEFAULT_PATH)


def load(path: Path) -> InstanceConfig | None:
    """Load the instance configuration, or ``None`` when setup has not run yet."""
    if not path.exists():
        return None
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return InstanceConfig(
        path=path,
        server=dict(data.get("server", {})),
        database=dict(data.get("database", {})),
        storage=dict(data.get("storage", {})),
    )


def new_config(path: Path) -> InstanceConfig:
    """A fresh configuration with a new random cookie secret (used by the setup wizard)."""
    return InstanceConfig(
        path=path,
        server={"cookie_secret": secrets.token_urlsafe(48), "max_upload_mb": 256},
        database={"pool_size": 8},
        storage={"upload_dir": "uploads"},
    )
