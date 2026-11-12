"""Connection pool and a thin, dialect aware wrapper around DB-API 2.0."""

from __future__ import annotations

import asyncio
import datetime as dt
import functools
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .dialects import Dialect

log = logging.getLogger("erp.db")


class Conn:
    """A connection wrapper that speaks a single SQL style.

    Queries are written with ``?`` placeholders and identifiers quoted with
    :meth:`q`; the wrapper converts them for the active database driver.
    """

    def __init__(self, raw, dialect: Dialect, paramstyle: str):
        self.raw = raw
        self.dialect = dialect
        self._format = paramstyle in ("format", "pyformat")

    def q(self, ident: str) -> str:
        return self.dialect.quote(ident)

    def _sql(self, sql: str, has_params: bool) -> str:
        if self._format and has_params:
            return sql.replace("%", "%%").replace("?", "%s")
        return sql

    def execute(self, sql: str, params=()):
        cur = self.raw.cursor()
        params = tuple(params)
        if params:
            cur.execute(self._sql(sql, True), params)
        else:
            cur.execute(sql)
        return cur

    def script(self, statements: list[str]) -> None:
        for stmt in statements:
            cur = self.execute(stmt)
            cur.close()

    @staticmethod
    def _rows(cur) -> list[dict]:
        if cur.description is None:
            return []
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def all(self, sql: str, params=()) -> list[dict]:
        cur = self.execute(sql, params)
        try:
            return self._rows(cur)
        finally:
            cur.close()

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params=()):
        cur = self.execute(sql, params)
        try:
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close()

    # -- convenience helpers -------------------------------------------------
    def insert(self, table: str, values: dict, return_id: bool = True) -> int | None:
        cols = list(values)
        sql = self.dialect.insert_sql(table, cols, return_id)
        cur = self.execute(sql, [values[c] for c in cols])
        try:
            if not return_id:
                return None
            if self.dialect.id_strategy in ("returning", "output"):
                row = cur.fetchone()
                return int(row[0])
            return int(cur.lastrowid)
        finally:
            cur.close()

    def update(self, table: str, values: dict, where: dict) -> int:
        if not values:
            return 0
        sets = ", ".join(f"{self.q(c)} = ?" for c in values)
        conds = " AND ".join(f"{self.q(c)} = ?" for c in where)
        cur = self.execute(
            f"UPDATE {self.q(table)} SET {sets} WHERE {conds}",
            list(values.values()) + list(where.values()),
        )
        n = cur.rowcount
        cur.close()
        return n

    def delete(self, table: str, where: dict) -> int:
        conds = " AND ".join(f"{self.q(c)} = ?" for c in where) or "1 = 1"
        cur = self.execute(f"DELETE FROM {self.q(table)} WHERE {conds}", list(where.values()))
        n = cur.rowcount
        cur.close()
        return n

    def table_exists(self, table: str) -> bool:
        return bool(self.scalar(self.dialect.table_exists_sql(), [table]))

    def commit(self) -> None:
        self.raw.commit()


class Database:
    """A small connection pool whose work runs in a thread pool.

    All blocking database work happens in worker threads, so the Tornado
    event loop stays responsive for many simultaneous users and sensors.
    """

    def __init__(self, dialect: Dialect, cfg: dict, pool_size: int = 8):
        self.dialect = dialect
        self.cfg = dict(cfg)
        self.pool_size = max(1, int(pool_size))
        self.executor = ThreadPoolExecutor(self.pool_size, thread_name_prefix="erp-db")
        self._idle: queue.LifoQueue = queue.LifoQueue()
        self._lock = threading.Lock()
        self._module = None

    # -- connections ---------------------------------------------------------
    def _new_raw(self):
        raw = self.dialect.connect(self.cfg)
        self.dialect.init_connection(raw)
        if self._module is None:
            self._module = __import__(type(raw).__module__.split(".")[0])
        return raw

    def _acquire(self):
        while True:
            try:
                raw, last_used = self._idle.get_nowait()
            except queue.Empty:
                return self._new_raw()
            if time.monotonic() - last_used < 300:
                return raw
            try:  # validate long idle connections
                cur = raw.cursor()
                cur.execute("SELECT 1")
                cur.fetchall()
                cur.close()
                raw.rollback()
                return raw
            except Exception:  # pragma: no cover - depends on server
                self._close_raw(raw)

    def _release(self, raw) -> None:
        if self._idle.qsize() >= self.pool_size:
            self._close_raw(raw)
        else:
            self._idle.put((raw, time.monotonic()))

    @staticmethod
    def _close_raw(raw) -> None:
        try:
            raw.close()
        except Exception:  # pragma: no cover
            pass

    def _paramstyle(self) -> str:
        return self.dialect.paramstyle(self._module) if self._module else "qmark"

    # -- running work ----------------------------------------------------------
    def run_sync(self, fn, *args, **kwargs):
        """Run ``fn(conn, *args)`` in a transaction and return its result."""
        raw = self._acquire()
        conn = Conn(raw, self.dialect, self._paramstyle())
        try:
            result = fn(conn, *args, **kwargs)
            raw.commit()
        except BaseException:
            try:
                raw.rollback()
            except Exception:  # pragma: no cover - broken connection
                self._close_raw(raw)
                raise
            self._release(raw)
            raise
        self._release(raw)
        return result

    async def run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor, functools.partial(self.run_sync, fn, *args, **kwargs)
        )

    def test(self) -> str:
        """Open a connection and return the server version string."""
        return self.run_sync(server_version)

    def close(self) -> None:
        while True:
            try:
                raw, _ = self._idle.get_nowait()
            except queue.Empty:
                break
            self._close_raw(raw)
        self.executor.shutdown(wait=False, cancel_futures=True)


def server_version(conn: Conn) -> str:
    sql = {"sqlite": "SELECT sqlite_version()", "mssql": "SELECT @@VERSION"}.get(conn.dialect.name, "SELECT VERSION()")
    try:
        return str(conn.scalar(sql)).splitlines()[0]
    except Exception:  # noqa: BLE001
        conn.raw.rollback()
        return "?"


def utcnow() -> dt.datetime:
    """Current UTC time as a naive datetime with millisecond precision."""
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)
