"""Export (SQL/TOML), character sets, import and restore."""

from __future__ import annotations

import sqlite3
import tomllib

from erp import backup, tomlwriter
from erp.repo import entities as entities_repo
from erp.repo import records as records_repo

from .helpers import PNG, WebTestCase


class BackupTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.install()
        self.login()
        self.post("/admin/menus/new", {"title": "Satış", "parent_id": "", "sort_order": "1"})
        self.create_entity("customers", "Müşteriler", menu_id="1")
        self.add_field("customers", "name", "text", required="1")
        self.add_field("customers", "balance", "currency", decimal_places="2")
        self.add_field("customers", "vip", "boolean")
        self.add_field("customers", "since", "date")
        self.add_field("customers", "logo", "image")
        self.post("/data/customers/new", {"name": "Işık Ğıda Şti. €", "balance": "1234.50", "vip": "1",
                                          "since": "2025-02-03"}, files={"logo": ("l.png", PNG, "image/png")})
        self.post("/data/customers/new", {"name": "O'Brien \\ Co", "balance": "-5"})

    def download(self, kind, fmt, charset="utf-8", dialect="sqlite", **extra):
        data = {"format": fmt, "charset": charset, "dialect": dialect}
        data.update(extra)
        r = self.post(f"/admin/backup/{kind}", data)
        self.assertEqual(r.code, 200, r.body[:500])
        self.assertIn("attachment", r.headers["Content-Disposition"])
        return r.body

    def test_toml_exports_parse(self):
        for kind in ("config", "schema", "data", "full"):
            raw = self.download(kind, "toml", entities="customers")
            doc = tomllib.loads(raw.decode())
            self.assertEqual(doc["backup"]["kind"], kind)
        full = tomllib.loads(self.download("full", "toml").decode())
        self.assertEqual(full["entities"][0]["name"], "customers")
        self.assertEqual(full["data"]["customers"][0]["name"], "Işık Ğıda Şti. €")
        self.assertEqual(full["data"]["customers"][0]["balance"], "1234.50")
        self.assertIn("password_hash", full["users"][0])
        config = tomllib.loads(self.download("config", "toml").decode())
        self.assertNotIn("users", config)
        self.assertEqual(config["menus"][0]["title"], "Satış")

    def test_toml_legacy_charsets_are_lossless(self):
        for charset in ("ascii", "cp437", "cp857", "cp1254", "iso-8859-9"):
            raw = self.download("data", "toml", charset=charset, entities="customers")
            raw.decode(charset)  # really in that character set
            doc = backup.load_toml(raw)  # charset detected from the header comment
            self.assertEqual(doc["data"]["customers"][0]["name"], "Işık Ğıda Şti. €", charset)
        cp857 = self.download("data", "toml", charset="cp857", entities="customers")
        self.assertIn("Işık".encode("cp857"), cp857)
        self.assertIn(b"\\u20AC", cp857)  # euro sign does not exist in DOS 857

    def test_sql_full_dump_runs_on_sqlite(self):
        raw = self.download("full", "sql", charset="utf-8", dialect="sqlite")
        con = sqlite3.connect(":memory:")
        con.executescript(raw.decode())
        rows = con.execute("SELECT name, balance, vip FROM d_customers ORDER BY id").fetchall()
        self.assertEqual(rows[0][0], "Işık Ğıda Şti. €")
        self.assertEqual(rows[1][0], "O'Brien \\ Co")
        self.assertEqual(con.execute("SELECT username FROM erp_users").fetchone()[0], "admin")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM erp_fields").fetchone()[0], 5)

    def test_sql_dialects_and_charsets(self):
        for dialect in ("sqlite", "mysql", "mariadb", "mssql", "postgresql"):
            for kind in ("config", "schema", "data", "full"):
                raw = self.download(kind, "sql", dialect=dialect, entities="customers")
                self.assertTrue(raw.startswith(b"-- charset: utf-8"))
        mysql = self.download("data", "sql", dialect="mysql", entities="customers").decode()
        self.assertIn("`d_customers`", mysql)
        self.assertIn("'O''Brien \\\\ Co'", mysql)
        mssql = self.download("full", "sql", dialect="mssql").decode()
        self.assertIn("SET IDENTITY_INSERT [d_customers] ON", mssql)
        self.assertIn("N'Işık", mssql)
        pg = self.download("full", "sql", dialect="postgresql").decode()
        self.assertIn("setval(pg_get_serial_sequence", pg)
        legacy = self.download("data", "sql", charset="cp1254", entities="customers")
        self.assertIn("Işık Ğıda Şti. €".encode("cp1254"), legacy)
        ascii_sql = self.download("data", "sql", charset="ascii", entities="customers")
        self.assertIn(b"I??k ??da ?ti. ?", ascii_sql)

    def test_schema_sql_creates_tables(self):
        raw = self.download("schema", "sql", dialect="sqlite")
        con = sqlite3.connect(":memory:")
        con.executescript(raw.decode())
        cols = [r[1] for r in con.execute("PRAGMA table_info(d_customers)")]
        self.assertEqual(cols, ["id", "created_at", "updated_at", "created_by", "updated_by", "api_key_id",
                                "name", "balance", "vip", "since", "logo"])

    def test_restore_full_backup(self):
        raw = self.download("full", "toml", include_files="1")
        # change things after the backup
        self.post("/data/customers/1/delete")
        self.add_field("customers", "extra", "text")
        self.create_entity("temp", "Temp")
        r = self.post("/admin/restore", {"charset": "", "mode": "append"}, files={"file": ("b.toml", raw, "text/plain")})
        self.assertIn("Tick", self.text(r)) if "Tick" in self.text(r) else self.assertIn("Check", self.text(r))
        r = self.post("/admin/restore", {"charset": "", "mode": "append", "confirm_full": "1"},
                      files={"file": ("b.toml", raw, "text/plain")})
        self.assertIn("Import finished", self.text(r))
        self.login()
        state = self.state

        def check(conn):
            ent = entities_repo.get_entity(conn, "customers")
            return ent, records_repo.list_records(conn, ent, desc=False), entities_repo.get_entity(conn, "temp")

        ent, rows, temp = state.db.run_sync(check)
        self.assertIsNone(temp)
        self.assertIsNone(ent.field("extra"))
        self.assertEqual([r["name"] for r in rows], ["Işık Ğıda Şti. €", "O'Brien \\ Co"])
        self.assertEqual(rows[0]["id"], 1)
        # ids continue after the restored ones
        r = self.post("/data/customers/new", {"name": "New"})
        self.assertEqual(r.headers["Location"], "/data/customers/3")
        # the image still works
        body = self.text(self.get("/data/customers/1"))
        self.assertIn("l.png", body)

    def test_import_data_append_and_replace(self):
        raw = self.download("data", "toml", entities="customers", charset="cp857")
        r = self.post("/admin/restore", {"charset": "", "mode": "append"}, files={"file": ("d.toml", raw, "text/plain")})
        self.assertIn("records: 2", self.text(r))

        def count(conn):
            return records_repo.count_records(conn, entities_repo.get_entity(conn, "customers"))

        self.assertEqual(self.state.db.run_sync(count), 4)
        r = self.post("/admin/restore", {"charset": "cp857", "mode": "replace"}, files={"file": ("d.toml", raw, "text/plain")})
        self.assertIn("records: 2", self.text(r))
        self.assertEqual(self.state.db.run_sync(count), 2)

    def test_import_schema_into_other_installation(self):
        schema = self.download("schema", "toml")
        self.post("/admin/entities/customers/fields/vip/delete", {"confirm": "vip"})
        r = self.post("/admin/restore", {"charset": "", "mode": "append"}, files={"file": ("s.toml", schema, "text/plain")})
        self.assertIn("fields_created: 1", self.text(r))

    def test_invalid_import(self):
        r = self.post("/admin/restore", {"charset": ""}, files={"file": ("x.toml", b"a = [", "text/plain")})
        self.assertIn("not valid TOML", self.text(r))
        r = self.post("/admin/restore", {"charset": ""}, files={"file": ("x.toml", b"a = 1", "text/plain")})
        self.assertIn("not an ERP-Software export", self.text(r))


class TomlWriterTests(WebTestCase):
    def test_roundtrip(self):
        import datetime as dt
        import decimal

        data = {"a": 1, "b": "x\"y\\z\n\tü€😀", "c": [1, 2], "d": {"e": True, "f": dt.datetime(2026, 1, 2, 3, 4, 5)},
                "g": [{"h": 1}, {"h": 2, "i": {"j": "k"}}], "dec": decimal.Decimal("1.50"), "n": None,
                "key with space": dt.date(2026, 1, 1), "empty": []}
        for charset in ("utf-8", "ascii", "cp857"):
            text = tomlwriter.dumps(data, charset)
            text.encode(charset)
            back = tomllib.loads(text)
            self.assertEqual(back["b"], data["b"])
            self.assertEqual(back["g"][1]["i"]["j"], "k")
            self.assertEqual(back["dec"], "1.50")
            self.assertNotIn("n", back)
            self.assertEqual(back["key with space"], dt.date(2026, 1, 1))
