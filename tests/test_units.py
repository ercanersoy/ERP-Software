"""Unit tests for field types, character sets, languages and the help renderer."""

from __future__ import annotations

import datetime as dt
import decimal
import unittest

from erp import charsets
from erp.db import get_dialect
from erp.fieldtypes import Field, ValidationError
from erp.handlers.menus import markdown_to_html
from erp.i18n import get_locale, normalize_language


class FieldTypeTests(unittest.TestCase):
    def test_decimal_parsing(self):
        f = Field(None, None, "amount", "Amount", "currency", decimal_places=2)
        self.assertEqual(f.parse("1.234,56"), decimal.Decimal("1234.56"))
        self.assertEqual(f.parse("1,234.56"), decimal.Decimal("1234.56"))
        self.assertEqual(f.parse("12,5"), decimal.Decimal("12.50"))
        self.assertEqual(f.parse(3), decimal.Decimal("3.00"))
        self.assertIsNone(f.parse(""))
        with self.assertRaises(ValidationError):
            f.parse("abc")
        with self.assertRaises(ValidationError):
            f.parse("NaN")

    def test_other_types(self):
        self.assertEqual(Field(None, None, "d", "D", "date").parse("31.01.2026"), dt.date(2026, 1, 31))
        self.assertEqual(Field(None, None, "t", "T", "datetime").parse("2026-01-31T10:00:00+03:00"),
                         dt.datetime(2026, 1, 31, 7, 0))
        self.assertTrue(Field(None, None, "b", "B", "boolean").parse("evet"))
        self.assertFalse(Field(None, None, "b", "B", "boolean").parse(""))
        with self.assertRaises(ValidationError):
            Field(None, None, "e", "E", "email").parse("not-an-email")
        with self.assertRaises(ValidationError):
            Field(None, None, "c", "C", "choice", options="A\nB").parse("C")
        with self.assertRaises(ValidationError):
            Field(None, None, "x", "X", "text", max_length=3).parse("abcd")
        with self.assertRaises(ValidationError):
            Field(None, None, "i", "I", "integer").parse(True)


class CharsetTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(charsets.normalize("Windows-1254"), "cp1254")
        self.assertEqual(charsets.normalize("windows-2254"), "cp1254")
        self.assertEqual(charsets.normalize("DOS857"), "cp857")
        self.assertEqual(charsets.normalize("IBM437"), "cp437")
        self.assertEqual(charsets.normalize("latin5"), "iso-8859-9")
        self.assertEqual(charsets.normalize("UTF8"), "utf-8")
        self.assertEqual(charsets.normalize("nonsense"), "utf-8")

    def test_detect_declared(self):
        self.assertEqual(charsets.detect_declared(b"# charset: cp857\n[backup]"), "cp857")
        self.assertEqual(charsets.detect_declared(b"-- charset: windows-1254\n"), "cp1254")
        self.assertIsNone(charsets.detect_declared(b"[backup]"))


class DialectTests(unittest.TestCase):
    def test_quote_rejects_injection(self):
        with self.assertRaises(Exception):
            get_dialect("mysql").quote("a`; DROP TABLE x; --")

    def test_literals(self):
        self.assertEqual(get_dialect("mysql").literal("a'b\\c"), "'a''b\\\\c'")
        self.assertEqual(get_dialect("postgresql").literal("a'b\\c"), "'a''b\\c'")
        self.assertEqual(get_dialect("mssql").literal("ş"), "N'ş'")
        self.assertEqual(get_dialect("postgresql").literal(True), "TRUE")
        self.assertEqual(get_dialect("sqlite").literal(None), "NULL")
        self.assertEqual(get_dialect("mysql").literal(decimal.Decimal("1.50")), "1.50")

    def test_limits(self):
        self.assertEqual(get_dialect("mssql").limit_sql(10, 20), " OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY")
        self.assertEqual(get_dialect("mysql").limit_sql(10, 20), " LIMIT 10 OFFSET 20")


class LanguageTests(unittest.TestCase):
    def test_formats(self):
        value = decimal.Decimal("1234.5")
        self.assertEqual(get_locale("tr-TR").currency(value, "TRY"), "1.234,50 ₺")
        self.assertEqual(get_locale("en-US").currency(value, "USD"), "$1,234.50")
        self.assertEqual(get_locale("en-GB").currency(value, "GBP"), "£1,234.50")
        day = dt.date(2026, 3, 4)
        self.assertEqual(get_locale("tr-TR").date(day), "04.03.2026")
        self.assertEqual(get_locale("en-US").date(day), "03/04/2026")
        self.assertEqual(get_locale("en-GB").date(day), "04/03/2026")

    def test_fallback_and_normalize(self):
        self.assertEqual(get_locale("en-GB").t("common.save"), "Save")
        self.assertEqual(get_locale("en-GB").t("admin.menus_hint"), "Menu groups that organise the data screens")
        self.assertEqual(normalize_language("en_gb"), "en-GB")
        self.assertEqual(normalize_language("tr"), "tr-TR")
        self.assertEqual(normalize_language("en"), "en-US")


class MarkdownTests(unittest.TestCase):
    def test_escapes_html(self):
        html = markdown_to_html("# Title\n\nText <script>x</script> `code` **bold** [API](API.md)\n\n- a\n- b\n")
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('<a href="/help/API">API</a>', html)
        self.assertIn("<ul><li>a</li>", html.replace("\n", ""))
