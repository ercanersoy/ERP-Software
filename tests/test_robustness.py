"""Whole-application checks: every page and form, permissions and concurrency.

The crawl and the form fuzzing found no error on their own so far; they
guard against regressions (HTTP 500 pages, untranslated texts) anywhere.
"""

from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser

from .helpers import PNG, WebTestCase


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and (a.get("href") or "").startswith("/"):
            self.links.append(a["href"])
        if tag == "tr" and a.get("data-href"):
            self.links.append(a["data-href"])


#: Translation keys or {placeholders} visible on a page mean a missing text.
RAW_KEY = re.compile(r"(?<![\w/.-])(?:common|error|data|setup|login|backup|apikeys|users|entities|fields|menus|"
                     r"settings|account|admin|system|audit|keys|menu|type|perm|role)\.[a-z][a-z0-9_]+(?![\w(])")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


class RobustnessTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.install()
        self.login()
        self.post("/admin/menus/new", {"title": "Sales", "parent_id": "", "sort_order": "1"})
        self.post("/admin/menus/new", {"title": "Hidden area", "parent_id": "", "sort_order": "2"})
        self.create_entity("customers", "Customers", menu_id="1", perm_dealer="own", is_sensor="1")
        for name, ftype, extra in [("name", "text", {"required": "1", "is_unique": "1"}), ("notes", "longtext", {}),
                                   ("qty", "integer", {}), ("rate", "decimal", {}), ("temp", "float", {}),
                                   ("amount", "currency", {}), ("vip", "boolean", {}), ("day", "date", {}),
                                   ("at", "datetime", {}), ("kind", "choice", {"options": "A\nB"}),
                                   ("mail", "email", {}), ("doc", "document", {}), ("photo", "image", {})]:
            self.add_field("customers", name, ftype, **extra)
        self.create_entity("orders", "Orders", menu_id="2", perm_user="read")
        self.add_field("orders", "customer", "reference", ref_entity="customers")
        self.post("/data/customers/new", {"name": "Çağrı", "qty": "3", "rate": "1,5", "temp": "2.5", "amount": "10",
                                          "vip": "1", "day": "2026-01-02", "at": "2026-01-02T03:04:05", "kind": "A",
                                          "mail": "a@b.co"},
                  files={"photo": ("p.png", PNG, "image/png"), "doc": ("d.pdf", b"%PDF-1.4", "application/pdf")})
        self.post("/data/orders/new", {"customer": "1"})
        for username, role in (("worker", "user"), ("dealer", "dealer")):
            self.post("/admin/users/new", {"username": username, "role": role, "active": "1", "password": "secret123"})
        self.create_api_key("key")

    def as_user(self, username):
        self.post("/logout")
        self.login(username, "secret123" if username != "admin" else "secret123")

    def crawl(self) -> set[str]:
        seen, todo, problems = set(), ["/", "/help"], []
        while todo and len(seen) < 400:
            url = todo.pop().split("#")[0]
            if url in seen or any(s in url for s in ("/logout", "/lang/", "/delete", "download=1")):
                continue
            seen.add(url)
            r = self.get(url)
            self.assertLess(r.code, 500, url)
            if r.code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
                continue
            body = self.text(r)
            visible = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style|pre|code)[^>]*>.*?</\1>", " ", body, flags=re.S))
            problems += [(url, m) for m in RAW_KEY.findall(visible) + PLACEHOLDER.findall(visible)]
            parser = _Links()
            parser.feed(body)
            todo += parser.links
        self.assertEqual(problems, [])
        return seen

    def test_every_page_in_every_language_and_role(self):
        for username in ("admin", "worker", "dealer", None):
            self.post("/logout")
            if username:
                self.login(username, "secret123")
            for lang in ("tr-TR", "en-US", "en-GB"):
                self.get(f"/lang/{lang}?next=/")
                self.assertGreater(len(self.crawl()), 5)

    def test_no_form_answers_with_a_server_error(self):
        forms: dict[str, set[str]] = {}
        for url in sorted(self.crawl()):
            body = self.text(self.get(url))
            for m in re.finditer(r'<form method="post" action="([^"]*)"[^>]*>(.*?)</form>', body, re.S):
                action = m.group(1) or url
                if "/logout" not in action and "/restore" not in action and not action.endswith("/delete"):
                    forms.setdefault(action, set()).update(set(re.findall(r'name="([^"]+)"', m.group(2))) - {"_xsrf"})
        values = ["", "²", "x" * 5000, "99999999999999999999999", "1E+400", "\x00", "<b>", "2026-02-30", "-0"]
        for username in ("worker", "dealer", "admin"):
            self.as_user(username)
            for action, names in sorted(forms.items()):
                for value in values:
                    data = {n: value for n in names if n not in ("password", "new_password", "new_password2")}
                    r = self.post(action, data)
                    self.assertLess(r.code, 500, (username, action, value))

    def test_hidden_menu_can_not_be_opened_by_address(self):
        self.as_user("dealer")
        self.assertEqual(self.get("/menu/2").code, 404)
        self.assertEqual(self.get("/menu/1").code, 200)

    def test_links_to_screens_without_access_are_plain_text(self):
        self.post("/admin/entities/customers/edit", {"label": "Customers", "description": "", "menu_id": "1",
                                                     "sort_order": "0", "perm_user": "none", "perm_dealer": "own",
                                                     "read_interval_ms": "5000", "page_size": "", "title_field": "name"})
        self.as_user("worker")
        body = self.text(self.get("/data/orders/1"))
        self.assertIn("Çağrı", body)
        self.assertNotIn('href="/data/customers/1"', body)

    def test_simultaneous_requests_keep_unique_values_unique(self):
        # A small screen makes the check-then-insert window of the old code
        # show up reliably (it is timing dependent).
        self.create_entity("codes", "Codes")
        self.add_field("codes", "code", "text", is_unique="1")
        token = self.create_api_key("race")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async def send_all():
            async def one():
                r = await self.http_client.fetch(self.get_url("/api/v1/entities/codes/records"), method="POST",
                                                 body=json.dumps({"code": "SAME"}), headers=headers, raise_error=False)
                return r.code
            return await asyncio.gather(*[one() for _ in range(10)])

        codes = self.io_loop.run_sync(send_all, timeout=60)
        self.assertEqual(sorted(codes), [201] + [422] * 9)
        count = self.state.db.run_sync(
            lambda c: c.scalar(f"SELECT COUNT(*) FROM {c.q('d_codes')} WHERE {c.q('code')} = ?", ["SAME"]))
        self.assertEqual(count, 1)
