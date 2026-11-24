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
        """Wrap the DB-API connection ``raw``.

        Drivers with the ``format``/``pyformat`` parameter style (PyMySQL,
        psycopg, pymssql) expect ``%s`` instead of ``?``; :meth:`_sql` converts.
        """
        self.raw = raw
        self.dialect = dialect
        self._format = paramstyle in ("format", "pyformat")

    def q(self, ident: str) -> str:
        """Quote an identifier (table or column name) for the active database system."""
        return self.dialect.quote(ident)

    def _sql(self, sql: str, has_params: bool) -> str:
        """Convert ``?`` placeholders for drivers that use ``%s``.

        Literal ``%`` signs must then be doubled.  Queries without parameters are
        sent unchanged, because those drivers do not interpret ``%`` there.
        """
        if self._format and has_params:
            # Note: no SQL text of the application contains a literal '?' or '%' outside parameters; search
            # patterns are passed as parameters, never inlined.
            return sql.replace("%", "%%").replace("?", "%s")
        return sql

    def execute(self, sql: str, params=()):
        """Run one statement and return the open cursor (the caller closes it)."""
        cur = self.raw.cursor()
        params = tuple(params)
        if params:
            cur.execute(self._sql(sql, True), params)
        else:
            cur.execute(sql)
        return cur

    def script(self, statements: list[str]) -> None:
        """Run several statements (e.g. CREATE TABLE plus its indexes) one after another."""
        for stmt in statements:
            cur = self.execute(stmt)
            cur.close()

    @staticmethod
    def _rows(cur) -> list[dict]:
        """Fetch all rows of ``cur`` as dictionaries keyed by column name."""
        if cur.description is None:
            return []
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def all(self, sql: str, params=()) -> list[dict]:
        """Run a query and return all rows as dictionaries."""
        cur = self.execute(sql, params)
        try:
            return self._rows(cur)
        finally:
            cur.close()

    def one(self, sql: str, params=()) -> dict | None:
        """Run a query and return the first row, or ``None``."""
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params=()):
        """Run a query and return the first column of the first row, or ``None``."""
        cur = self.execute(sql, params)
        try:
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close()

    # -- convenience helpers -------------------------------------------------
    def insert(self, table: str, values: dict, return_id: bool = True) -> int | None:
        """Insert one row and return its generated ``id`` (unless ``return_id`` is false).

        How the id is obtained depends on the database system: ``RETURNING``
        (PostgreSQL), ``OUTPUT INSERTED`` (SQL Server) or ``cursor.lastrowid``.
        """
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
        """``UPDATE table SET values WHERE where``; returns the number of changed rows."""
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
        """``DELETE FROM table WHERE where`` (an empty ``where`` deletes all rows)."""
        conds = " AND ".join(f"{self.q(c)} = ?" for c in where) or "1 = 1"
        cur = self.execute(f"DELETE FROM {self.q(table)} WHERE {conds}", list(where.values()))
        n = cur.rowcount
        cur.close()
        return n

    def table_exists(self, table: str) -> bool:
        """True when the table exists in the current database/schema."""
        return bool(self.scalar(self.dialect.table_exists_sql(), [table]))

    def commit(self) -> None:
        """Commit the current transaction (normally done by :meth:`Database.run_sync`)."""
        self.raw.commit()


class Database:
    """A small connection pool whose work runs in a thread pool.

    All blocking database work happens in worker threads, so the Tornado
    event loop stays responsive for many simultaneous users and sensors.
    """

    def __init__(self, dialect: Dialect, cfg: dict, pool_size: int = 8):
        """Prepare the pool; connections are opened lazily on first use.

        ``pool_size`` is both the number of worker threads and the maximum number
        of idle connections kept for re-use.
        """
        self.dialect = dialect
        self.cfg = dict(cfg)
        self.pool_size = max(1, int(pool_size))
        self.executor = ThreadPoolExecutor(self.pool_size, thread_name_prefix="erp-db")
        self._idle: queue.LifoQueue = queue.LifoQueue()
        self._lock = threading.Lock()
        self._module = None

    # -- connections ---------------------------------------------------------
    def _new_raw(self):
        """Open a new driver connection and remember the driver module (for its paramstyle)."""
        raw = self.dialect.connect(self.cfg)
        self.dialect.init_connection(raw)
        if self._module is None:
            self._module = __import__(type(raw).__module__.split(".")[0])
        return raw

    def _acquire(self):
        """Take an idle connection from the pool or open a new one.

        Connections idle for more than five minutes may have been closed by the
        server (MySQL's wait_timeout, firewalls), so they are tested first and
        replaced when broken.  A LIFO queue re-uses the most recent, warmest one.
        """
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
        """Return a connection to the pool, or close it when the pool is full."""
        if self._idle.qsize() >= self.pool_size:
            self._close_raw(raw)
        else:
            self._idle.put((raw, time.monotonic()))

    @staticmethod
    def _close_raw(raw) -> None:
        """Close a connection, ignoring errors of already broken connections."""
        try:
            raw.close()
        except Exception:  # pragma: no cover
            pass

    def _paramstyle(self) -> str:
        """Parameter style of the driver (``qmark`` until the first connection exists)."""
        return self.dialect.paramstyle(self._module) if self._module else "qmark"

    # -- running work ----------------------------------------------------------
    def run_sync(self, fn, *args, **kwargs):
        """Run ``fn(conn, *args)`` in a transaction and return its result."""
        raw = self._acquire()
        conn = Conn(raw, self.dialect, self._paramstyle())
        try:
            result = fn(conn, *args, **kwargs)
            raw.commit()
        # BaseException, not Exception: also cancelled tasks and KeyboardInterrupt must roll back, or the
        # connection would return to the pool with an open transaction.
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
        """Run ``fn(conn, *args)`` in a worker thread and await its result.

        This is how request handlers use the database: the event loop keeps serving
        other users while the query runs.  The whole function is one transaction.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor, functools.partial(self.run_sync, fn, *args, **kwargs)
        )

    def test(self) -> str:
        """Open a connection and return the server version string."""
        return self.run_sync(server_version)

    def close(self) -> None:
        """Close idle connections and stop the worker threads."""
        while True:
            try:
                raw, _ = self._idle.get_nowait()
            except queue.Empty:
                break
            self._close_raw(raw)
        self.executor.shutdown(wait=False, cancel_futures=True)


def server_version(conn: Conn) -> str:
    """Version string of the database server, or ``?`` when it can not be determined."""
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
