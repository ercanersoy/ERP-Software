"""End-to-end tests through the web interface."""

from __future__ import annotations

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
