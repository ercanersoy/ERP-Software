"""End-to-end tests through the web interface."""

from __future__ import annotations

import json
import re

from erp import config

from .helpers import PNG, WebTestCase


class SetupTests(WebTestCase):
    def test_redirects_to_setup_until_installed(self):
        r = self.get("/")
        self.assertEqual(r.code, 302)
        self.assertEqual(r.headers["Location"], "/setup")
        r = self.get("/setup")
        self.assertEqual(r.code, 200)
        self.assertIn("setup_token", self.text(r))

    def test_wrong_setup_token(self):
        r = self.post("/setup", {"setup_token": "nope", "language": "en-US", "company_name": "X", "db_dialect": "sqlite",
                                 "db_name": "x.sqlite3"})
        self.assertEqual(r.code, 200)
        self.assertIn("setup token is wrong", self.text(r))
        self.assertFalse(self.config_path.exists())

    def test_install_closes_setup_mode(self):
        self.install()
        self.assertTrue(self.config_path.exists())
        self.assertEqual(oct(self.config_path.stat().st_mode & 0o777), "0o600")
        cfg = config.load(self.config_path)
        self.assertTrue(cfg.cookie_secret)
        self.assertEqual(self.get("/setup").code, 404)
        r = self.get("/login")
        self.assertIn("Installation complete", self.text(r))

    def test_password_rules(self):
        r = self.post("/setup", {"setup_token": self.SETUP_TOKEN, "language": "tr-TR", "company_name": "X",
                                 "db_dialect": "sqlite", "db_name": "x.sqlite3", "admin_username": "admin",
                                 "admin_password": "short", "admin_password2": "short"})
        self.assertEqual(r.code, 200)
        self.assertIn("en az 8 karakter", self.text(r))


class AppTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.install()
        self.login()

    def test_login_logout_and_wrong_password(self):
        r = self.get("/")
        self.assertEqual(r.code, 200)
        self.assertIn("No data screens have been defined yet", self.text(r))
        r = self.post("/logout")
        self.assertEqual(r.code, 302)
        self.assertEqual(self.get("/").code, 302)
        r = self.post("/login", {"username": "admin", "password": "wrong-password"})
        self.assertIn("Wrong user name or password", self.text(r))

    def test_no_fields_by_default(self):
        self.create_entity("customers", "Customers")
        r = self.get("/data/customers")
        self.assertIn("has no fields yet", self.text(r))
        r = self.get("/admin/entities/customers")
        self.assertIn("no fields yet", self.text(r))

    def test_languages(self):
        for code, word in (("tr-TR", "Ana menü"), ("en-GB", "Main menu"), ("en-US", "Main menu")):
            r = self.get(f"/lang/{code}?next=/admin")
            self.assertEqual(r.code, 302)
            r = self.get("/admin")
            self.assertIn(f'<html lang="{code}">', self.text(r))
            self.assertIn(word, self.text(r))
        self.get("/lang/en-GB")
        self.assertIn("organise", self.text(self.get("/admin")))
        for code in ("tr-TR", "en-US", "en-GB"):
            self.get(f"/lang/{code}")
            r = self.get("/help")
            self.assertEqual(r.code, 200)
            r = self.get("/help/API")
            self.assertEqual(r.code, 200)
            self.assertIn("/api/v1/", self.text(r))

    def test_records_crud_with_files(self):
        self.create_entity("customers", "Customers")
        self.add_field("customers", "name", "text", required="1", is_unique="1")
        self.add_field("customers", "balance", "currency", currency="TRY")
        self.add_field("customers", "active", "boolean", default_value="1")
        self.add_field("customers", "joined", "date")
        self.add_field("customers", "kind", "choice", options="Retail\nWholesale")
        self.add_field("customers", "photo", "image")
        self.add_field("customers", "notes", "longtext")
        r = self.post("/data/customers/new", {"name": "Çağrı Şirketi", "balance": "1.234,56", "active": "1",
                                              "joined": "2026-01-31", "kind": "Retail", "notes": "a\nb"},
                      files={"photo": ("p.png", PNG, "image/png")})
        self.assertEqual(r.code, 302, self.text(r))
        record_url = r.headers["Location"]
        r = self.get(record_url)
        body = self.text(r)
        self.assertIn("Çağrı Şirketi", body)
        self.assertIn("₺1,234.56", body)
        self.assertIn("01/31/2026", body)
        file_url = re.search(r'src="(/files/\d+)"', body).group(1)
        r = self.get(file_url)
        self.assertEqual(r.code, 200)
        self.assertEqual(r.body, PNG)
        self.assertEqual(r.headers["Content-Type"], "image/png")
        # unique and required checks
        r = self.post("/data/customers/new", {"name": "Çağrı Şirketi"})
        self.assertIn("already exists", self.text(r))
        r = self.post("/data/customers/new", {"name": ""})
        self.assertIn("This field is required", self.text(r))
        # wrong image type
        r = self.post("/data/customers/new", {"name": "B"}, files={"photo": ("x.png", b"not an image", "image/png")})
        self.assertIn("not a supported image", self.text(r))
        # list and search
        r = self.get("/data/customers?q=%C3%A7a%C4%9FRI")  # "çağRI": Turkish aware, case insensitive
        self.assertIn("Çağrı Şirketi", self.text(r))
        r = self.get("/data/customers?q=zzz")
        self.assertNotIn("Çağrı Şirketi", self.text(r))
        # edit
        r = self.post(record_url + "/edit", {"name": "Yeni Ad", "balance": "10", "joined": "", "kind": "Wholesale"})
        self.assertEqual(r.code, 302, self.text(r))
        body = self.text(self.get(record_url))
        self.assertIn("Yeni Ad", body)
        self.assertIn("p.png", body)  # file kept
        # remove file then delete record
        self.post(record_url + "/edit", {"name": "Yeni Ad", "__remove_photo": "1"})
        self.assertEqual(self.get(file_url).code, 404)
        r = self.post(record_url + "/delete")
        self.assertEqual(r.code, 302)
        self.assertEqual(self.get(record_url).code, 404)

    def test_reference_fields_and_csv(self):
        self.create_entity("customers", "Customers")
        self.add_field("customers", "name", "text")
        self.create_entity("invoices", "Invoices")
        self.add_field("invoices", "customer", "reference", ref_entity="customers")
        self.add_field("invoices", "amount", "decimal", decimal_places="2")
        self.post("/data/customers/new", {"name": "ACME"})
        r = self.post("/data/invoices/new", {"customer": "1", "amount": "12.5"})
        self.assertEqual(r.code, 302, self.text(r))
        self.assertIn("ACME", self.text(self.get("/data/invoices")))
        r = self.post("/data/invoices/new", {"customer": "99", "amount": "1"})
        self.assertIn("linked record does not exist", self.text(r))
        # CSV import in DOS 857 (Turkish)
        csv = "name\r\nİstanbul Ticaret\r\nŞube\r\n".encode("cp857")
        r = self.post("/data/customers/import", {"charset": "cp857", "delimiter": ";"},
                      files={"file": ("c.csv", csv, "text/csv")})
        self.assertIn("2 records were imported", self.text(r))
        r = self.post("/data/customers/export", {"format": "csv", "charset": "cp857", "delimiter": ";"})
        self.assertEqual(r.code, 200)
        self.assertIn("İstanbul Ticaret", r.body.decode("cp857"))
        self.assertIn("IBM857", r.headers["Content-Type"])

    def test_menus_and_dealer_permissions(self):
        r = self.post("/admin/menus/new", {"title": "Sales", "parent_id": "", "sort_order": "1"})
        self.assertEqual(r.code, 302)
        self.create_entity("orders", "Orders", menu_id="1", perm_dealer="own")
        self.add_field("orders", "item", "text")
        self.create_entity("secret", "Secret")
        r = self.post("/admin/users/new", {"username": "bayi1", "full_name": "Bayi", "email": "", "role": "dealer",
                                           "language": "tr-TR", "active": "1", "password": "dealer123"})
        self.assertEqual(r.code, 302, self.text(r))
        self.post("/data/orders/new", {"item": "admin order"})
        self.post("/logout")
        self.login("bayi1", "dealer123")
        body = self.text(self.get("/"))
        self.assertIn("Sales", body)
        self.assertNotIn("Secret", body)
        self.assertEqual(self.get("/admin").code, 403)
        self.assertEqual(self.get("/data/secret").code, 403)
        self.assertNotIn("admin order", self.text(self.get("/data/orders")))
        r = self.post("/data/orders/new", {"item": "dealer order"})
        self.assertEqual(r.code, 302)
        body = self.text(self.get("/data/orders"))
        self.assertIn("dealer order", body)
        self.assertNotIn("admin order", body)
        self.assertEqual(self.get("/data/orders/1").code, 404)

    def test_last_admin_protected(self):
        r = self.post("/admin/users/1", {"full_name": "A", "email": "", "role": "user", "language": "", "active": "1",
                                         "password": ""})
        self.assertIn("At least one active administrator", self.text(r))

    def test_sensor_monitor(self):
        self.create_entity("temps", "Temperatures", is_sensor="1", read_interval_ms="1000")
        self.add_field("temps", "celsius", "float")
        self.post("/data/temps/new", {"celsius": "21.5"})
        r = self.get("/data/temps/monitor")
        self.assertIn('data-interval="1000"', self.text(r))
        r = self.get("/data/temps/latest.json")
        self.assertIn("21.5", self.text(r))

    def test_settings_saved_together(self):
        r = self.post("/admin/settings", {"company_name": "Yeni Şirket", "default_language": "tr-TR",
                                          "default_charset": "cp1254", "timezone": "UTC", "default_currency": "EUR",
                                          "page_size": "50", "session_hours": "8", "api_enabled": "1"})
        self.assertEqual(r.code, 302, self.text(r))
        r = self.post("/admin/backup/config", {"format": "toml", "charset": "utf-8"})
        body = r.body.decode()
        self.assertIn('company_name = "Yeni Şirket"', body)
        self.assertIn('default_charset = "cp1254"', body)

    def test_security_headers_and_xsrf(self):
        r = self.get("/")
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        r = self.fetch("/admin/settings", method="POST", body="company_name=x",
                       headers={"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items() if k != "_xsrf")})
        self.assertEqual(r.code, 403)

    def test_linked_entity_can_not_be_deleted(self):
        self.create_entity("customers", "Customers")
        self.create_entity("invoices", "Invoices")
        self.add_field("invoices", "customer", "reference", ref_entity="customers")
        r = self.post("/admin/entities/customers/delete", {"confirm": "customers"})
        self.assertEqual(r.headers["Location"], "/admin/entities/customers")
        self.assertIn("invoices.customer", self.text(self.get("/admin/entities/customers")))
        self.post("/admin/entities/invoices/fields/customer/delete", {"confirm": "customer"})
        r = self.post("/admin/entities/customers/delete", {"confirm": "customers"})
        self.assertEqual(r.headers["Location"], "/admin/entities")

    def test_dealer_can_not_link_to_hidden_records(self):
        self.create_entity("customers", "Customers", perm_dealer="own")
        self.add_field("customers", "name", "text")
        self.create_entity("orders", "Orders", perm_dealer="own")
        self.add_field("orders", "customer", "reference", ref_entity="customers")
        self.post("/data/customers/new", {"name": "Secret customer"})
        self.post("/admin/users/new", {"username": "bayi2", "role": "dealer", "active": "1", "password": "dealer123"})
        self.post("/logout")
        self.login("bayi2", "dealer123")
        r = self.post("/data/orders/new", {"customer": "1"})
        self.assertIn("linked record does not exist", self.text(r))
        self.assertNotIn("Secret customer", self.text(r))


class RegressionTests(WebTestCase):
    """Bugs found in review; each test failed before its fix."""

    def setUp(self):
        super().setUp()
        self.install()
        self.login()

    def test_odd_numbers_in_urls_and_forms_do_not_crash(self):
        self.create_entity("items", "Items")
        self.add_field("items", "name", "text")
        self.add_field("items", "price", "decimal")
        # ids that do not fit into 64 bits are simply "not found"
        self.assertEqual(self.get("/data/items/99999999999999999999999").code, 404)
        self.assertEqual(self.get("/menu/99999999999999999999999").code, 404)
        # superscript digits pass str.isdigit() but not int()
        self.assertEqual(self.get("/data/items?q=%C2%B2").code, 200)
        self.assertEqual(self.get("/data/items?q=99999999999999999999999").code, 200)
        r = self.post("/admin/settings", {"company_name": "X", "default_language": "en-US", "default_charset": "utf-8",
                                          "timezone": "UTC", "default_currency": "TRY", "page_size": "²",
                                          "session_hours": "8", "api_enabled": "1"})
        self.assertEqual(r.code, 200)
        self.assertIn("Invalid value", self.text(r))
        r = self.post("/admin/menus/new", {"title": "M", "parent_id": "²", "sort_order": "0"})
        self.assertEqual(r.code, 302)
        r = self.post("/data/items/new", {"name": "Big", "price": "1E+30"})
        self.assertEqual(r.code, 200)
        self.assertIn("The number is too large", self.text(r))

    def test_csv_import_reports_real_line_numbers(self):
        self.create_entity("items", "Items")
        self.add_field("items", "code", "text", is_unique="1")
        self.add_field("items", "qty", "integer")
        csv = "code;qty\r\nA;x\r\nB;1\r\nB;2\r\n".encode()
        r = self.post("/data/items/import", {"charset": "utf-8", "delimiter": ";"},
                      files={"file": ("c.csv", csv, "text/csv")})
        body = self.text(r)
        self.assertIn("1 records were imported", body)
        self.assertRegex(body, r"[Ll]ine 2\b")   # "x" is not an integer
        self.assertRegex(body, r"[Ll]ine 4\b")   # duplicate "B" (was reported as line 3)

    def test_file_can_not_be_shared_between_records(self):
        self.create_entity("people", "People")
        self.add_field("people", "name", "text")
        self.add_field("people", "photo", "image")
        r = self.post("/data/people/new", {"name": "A"}, files={"photo": ("a.png", PNG, "image/png")})
        self.assertEqual(r.code, 302)
        file_id = re.search(r'src="/files/(\d+)"', self.text(self.get(r.headers["Location"]))).group(1)
        r = self.post("/data/people/new", {"name": "B"})
        self.assertEqual(r.code, 302)
        # Give record 2 the file of record 1 through the API ...
        token = self.create_api_key("k")
        resp = self.fetch("/api/v1/entities/people/records/2", method="PATCH",
                          body=json.dumps({"photo": int(file_id)}),
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.assertEqual(resp.code, 422)
        self.assertIn("file_in_use", resp.body.decode())
        # ... record 1 keeps its picture.
        self.assertEqual(self.get(f"/files/{file_id}").code, 200)

    def test_invalid_email_rejected(self):
        r = self.post("/account", {"full_name": "A", "email": "nope", "language": "en-US"})
        self.assertIn("Not a valid e-mail address", self.text(r))
        r = self.post("/admin/users/new", {"username": "u1", "email": "nope", "role": "user", "active": "1",
                                           "password": "secret123"})
        self.assertIn("Not a valid e-mail address", self.text(r))

    def test_records_created_on_the_web_are_published(self):
        self.create_entity("temps", "Temps", is_sensor="1")
        self.add_field("temps", "celsius", "float")
        seen = []

        class Sub:
            async def push(self, ids):
                seen.extend(ids)

        self.state.subscribe("temps", Sub())
        self.post("/data/temps/new", {"celsius": "20"})
        self.io_loop.run_sync(lambda: None)
        self.assertEqual(seen, [1])


class LimitTests(WebTestCase):
    """Values that SQLite accepts but PostgreSQL, MySQL and SQL Server reject.

    Run these with ERP_TEST_DB pointing to such a database too: before the
    fixes they ended in HTTP 500 there ("value too long", "out of range").
    """

    def setUp(self):
        super().setUp()
        self.install()
        self.login()

    def test_long_definition_texts_are_refused(self):
        long = "x" * 300
        r = self.post("/admin/entities/new", {"name": "e1", "label": long, "description": "", "menu_id": "",
                                              "sort_order": "0", "perm_user": "write", "perm_dealer": "none",
                                              "read_interval_ms": "5000", "page_size": ""})
        self.assertEqual(r.code, 200)
        self.assertIn("Too long", self.text(r))
        self.create_entity("e2", "E2")
        for extra in ({"label": long}, {"help_text": "y" * 600}, {"default_value": "z" * 300, "max_length": "4000"},
                      {"field_type": "choice", "options": "ok\n" + long}, {"field_type": "currency", "currency": "EURO"}):
            data = {"name": "f1", "label": "F1", "field_type": "text", "max_length": "255", "decimal_places": "",
                    "ref_entity": "", "currency": "TRY", "options": "", "default_value": "", "help_text": "",
                    "sort_order": ""}
            data.update(extra)
            r = self.post("/admin/entities/e2/fields/new", data)
            self.assertEqual(r.code, 200, (extra.keys(), self.text(r)[:200]))
        r = self.post("/admin/entities/e2/edit", {"label": "E2", "description": "", "menu_id": "", "sort_order": "0",
                                                  "perm_user": "write", "perm_dealer": "none", "read_interval_ms": "5000",
                                                  "page_size": "", "title_field": "t" * 80})
        self.assertEqual(r.code, 302)  # an unknown title field is ignored, not stored

    def test_huge_sort_orders_are_limited(self):
        self.create_entity("e3", "E3", sort_order="99999999999999999999")
        self.add_field("e3", "f", "text", sort_order="99999999999999999999")
        r = self.post("/admin/menus/new", {"title": "M", "parent_id": "", "sort_order": "99999999999999999999"})
        self.assertEqual(r.code, 302)
        self.assertEqual(self.get("/admin/entities/e3").code, 200)

    def test_decimals_keep_all_digits_and_sort_numerically(self):
        self.create_entity("money", "Money")
        self.add_field("money", "amount", "currency")
        for value in ("123456789012345.6789", "9", "100"):
            self.assertEqual(self.post("/data/money/new", {"amount": value}).code, 302)
        token = self.create_api_key("k")
        r = self.fetch("/api/v1/entities/money/records/1", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(json.loads(r.body)["amount"], "123456789012345.6789")
        r = self.fetch("/api/v1/entities/money/records?order=amount&dir=asc", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual([x["amount"] for x in json.loads(r.body)["records"]],
                         ["9.0000", "100.0000", "123456789012345.6789"])

    def test_empty_api_filter_matches_empty_values(self):
        self.create_entity("notes", "Notes")
        self.add_field("notes", "tag", "text")
        self.post("/data/notes/new", {"tag": ""})
        self.post("/data/notes/new", {"tag": "a"})
        token = self.create_api_key("k")
        r = self.fetch("/api/v1/entities/notes/records?tag=", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual([x["id"] for x in json.loads(r.body)["records"]], [1])

    def test_next_with_control_characters_is_ignored(self):
        self.post("/logout")
        r = self.post("/login", {"username": "admin", "password": "secret123", "next": "/\t/evil.example"})
        self.assertEqual(r.code, 302)
        self.assertEqual(r.headers["Location"], "/")

    def test_deleting_missing_items_is_not_found(self):
        self.assertEqual(self.post("/admin/menus/42/delete").code, 404)
        self.assertEqual(self.post("/admin/apikeys/42/delete").code, 404)


class RoundTripTests(WebTestCase):
    """Editing a record must not change values the user did not touch (third review)."""

    def setUp(self):
        super().setUp()
        self.install()
        self.login()

    def test_removed_choice_survives_editing_other_fields(self):
        self.create_entity("c", "C")
        self.add_field("c", "name", "text")
        self.add_field("c", "kind", "choice", options="Retail\nWholesale")
        self.post("/data/c/new", {"name": "A", "kind": "Wholesale"})
        self.post("/admin/entities/c/fields/kind", {"label": "Kind", "options": "Retail", "currency": "",
                                                    "default_value": "", "help_text": "", "sort_order": "",
                                                    "show_in_list": "1"})
        form = self.text(self.get("/data/c/1/edit"))
        self.assertIn('<option value="Wholesale" selected>', form)
        r = self.post("/data/c/1/edit", {"name": "B", "kind": "Wholesale"})
        self.assertEqual(r.code, 302, self.text(r))
        self.assertIn("Wholesale", self.text(self.get("/data/c/1")))
        # choosing a removed value for another record is still refused
        r = self.post("/data/c/new", {"name": "C", "kind": "Wholesale"})
        self.assertIn("Not one of the allowed choices", self.text(r))

    def test_link_beyond_first_1000_records_is_kept(self):
        self.create_entity("t", "T")
        self.add_field("t", "n", "text")

        def fill(conn):
            for i in range(1005):
                conn.insert("d_t", {"n": f"r{i}"})

        self.state.db.run_sync(fill)
        self.create_entity("o", "O")
        self.add_field("o", "ref", "reference", ref_entity="t")
        self.post("/data/o/new", {"ref": "1005"})
        self.assertIn('<option value="1005" selected>r1004</option>', self.text(self.get("/data/o/1/edit")))

    def test_admin_keeps_session_after_changing_own_password(self):
        r = self.post("/admin/users/1", {"full_name": "A", "email": "", "role": "admin", "language": "",
                                         "active": "1", "password": "newsecret1"})
        self.assertEqual(r.code, 302)
        self.assertEqual(self.get("/admin").code, 200)
        self.post("/logout")
        self.login("admin", "newsecret1")

    def test_appending_a_data_export_twice_does_not_share_files(self):
        self.create_entity("p", "P")
        self.add_field("p", "name", "text")
        self.add_field("p", "photo", "image")
        self.post("/data/p/new", {"name": "A"}, files={"photo": ("a.png", PNG, "image/png")})
        data = self.post("/admin/backup/data", {"format": "toml", "charset": "utf-8", "entities": ["p"],
                                                "include_files": "1"}).body
        self.post("/admin/restore", {"charset": "", "mode": "append"}, files={"file": ("d.toml", data, "text/plain")})
        rows = self.state.db.run_sync(lambda c: c.all('SELECT "id", "photo" FROM "d_p" ORDER BY "id"'))
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["photo"], rows[1]["photo"])
        self.assertEqual(self.get(f"/files/{rows[1]['photo']}").body, PNG)
        self.post("/data/p/2/delete")
        self.assertEqual(self.get(f"/files/{rows[0]['photo']}").body, PNG)

    def test_database_refusal_is_shown_on_the_form(self):
        self.create_entity("z", "Z")
        self.state.db.run_sync(lambda c: c.execute('ALTER TABLE "d_z" ADD COLUMN "dup" TEXT').close())
        r = self.post("/admin/entities/z/fields/new", {"name": "dup", "label": "Dup", "field_type": "text",
                                                       "max_length": "255", "decimal_places": "", "ref_entity": "",
                                                       "currency": "TRY", "options": "", "default_value": "",
                                                       "help_text": "", "sort_order": ""})
        self.assertEqual(r.code, 200)
        self.assertIn("The database refused the change", self.text(r))
