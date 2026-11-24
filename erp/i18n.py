"""Interface languages: Turkish (Türkiye), English (US) and English (UK).

Translations live in ``erp/locales/<code>.toml``.  ``en-GB`` only contains the
strings that differ from ``en-US``; missing strings fall back to ``en-US``.
"""

from __future__ import annotations

import datetime as dt
import decimal
import tomllib
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOCALE_DIR = Path(__file__).parent / "locales"
LANGUAGES: dict[str, str] = {
    "tr-TR": "Türkçe (Türkiye)",
    "en-US": "English (United States)",
    "en-GB": "English (United Kingdom)",
}
FALLBACK = {"en-GB": "en-US", "tr-TR": "en-US"}
CURRENCY_SYMBOLS = {"TRY": "₺", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥"}


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    """Turn nested TOML tables into dotted keys: ``{"menu": {"main": ..}}`` -> ``menu.main``."""
    out: dict[str, str] = {}
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, full + "."))
        else:
            out[full] = str(value)
    return out


@lru_cache(maxsize=None)
def _messages(code: str) -> dict[str, str]:
    """All texts of one language as a flat dictionary (read once and cached)."""
    path = LOCALE_DIR / f"{code}.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as fh:
        return _flatten(tomllib.load(fh))


def normalize_language(code: str | None, default: str = "tr-TR") -> str:
    """Map a language tag to a supported interface language.

    "tr", "tr_TR" and "TR-tr" give ``tr-TR``; British-like English variants
    give ``en-GB``; any other English gives ``en-US``; anything else ``default``.
    """
    if not code:
        return default
    code = code.strip().replace("_", "-")
    for lang in LANGUAGES:
        if lang.lower() == code.lower():
            return lang
    low = code.lower()
    if low.startswith("tr"):
        return "tr-TR"
    if low in ("en-gb", "en-uk", "en-ie", "en-au", "en-nz") or low.startswith("en-gb"):
        return "en-GB"
    if low.startswith("en"):
        return "en-US"
    return default


def from_accept_language(header: str | None, default: str) -> str:
    """First supported language of a browser's ``Accept-Language`` header, else ``default``."""
    if not header:
        return default
    for part in header.split(","):
        tag = part.split(";")[0].strip()
        if tag:
            lang = normalize_language(tag, "")
            if lang:
                return lang
    return default


class Locale:
    """One interface language plus the configured time zone.

    Provides translated texts (:meth:`t`) and locale specific formatting of
    numbers, amounts, dates and times.
    """
    def __init__(self, code: str, timezone: str = "UTC"):
        """Load the texts of ``code`` and set separators and date/time formats of the language."""
        self.code = code if code in LANGUAGES else "en-US"
        self.messages = _messages(self.code)
        self.fallback = _messages(FALLBACK.get(self.code, "en-US")) if self.code != "en-US" else {}
        try:
            self.tz = ZoneInfo(timezone or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            self.tz = ZoneInfo("UTC")
        if self.code == "tr-TR":
            self.decimal_sep, self.group_sep = ",", "."
            self.date_fmt, self.time_fmt = "%d.%m.%Y", "%H:%M:%S"
        elif self.code == "en-GB":
            self.decimal_sep, self.group_sep = ".", ","
            self.date_fmt, self.time_fmt = "%d/%m/%Y", "%H:%M:%S"
        else:
            self.decimal_sep, self.group_sep = ".", ","
            # en-US: month first and the 12-hour clock with AM/PM.
            self.date_fmt, self.time_fmt = "%m/%d/%Y", "%I:%M:%S %p"

    @property
    def html_lang(self) -> str:
        """Value for ``<html lang>``."""
        return self.code

    def t(self, key: str, **params) -> str:
        """Translated text for ``key`` with ``{placeholders}`` filled from ``params``.

        Missing texts fall back to the parent language (en-GB -> en-US), then to
        en-US, then to the key itself, so a missing translation never breaks a page.
        """
        text = self.messages.get(key) or self.fallback.get(key) or _messages("en-US").get(key) or key
        if params:
            try:
                return text.format(**params)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    __call__ = t

    # ---------------------------------------------------------------- formats
    def number(self, value, places: int | None = None) -> str:
        """Format a number with the language's separators: 1.234,56 (tr-TR) or 1,234.56.

        Floats show up to six decimals without trailing zeros, integers none, and
        decimals as many as they have unless ``places`` is given.  The separators
        are swapped through a NUL placeholder so they can not mix up.
        """
        if value is None or value == "":
            return ""
        if isinstance(value, float) and places is None:
            text = f"{value:,.6f}".rstrip("0").rstrip(".")
        elif isinstance(value, int) and places is None:
            text = f"{value:,}"
        else:
            dec = value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))
            if places is None:
                places = max(0, -dec.as_tuple().exponent) if isinstance(dec.as_tuple().exponent, int) else 2
            text = f"{dec:,.{places}f}"
        return text.replace(",", "\x00").replace(".", self.decimal_sep).replace("\x00", self.group_sep)

    def currency(self, value, code: str | None, places: int = 2) -> str:
        """Format an amount: "1.234,56 ₺" in Turkish, "₺1,234.56" / "-£5.00" in English.

        Currencies without a known symbol are shown with their ISO code.
        """
        if value is None or value == "":
            return ""
        code = (code or "").upper()
        text = self.number(value, places)
        symbol = CURRENCY_SYMBOLS.get(code)
        if symbol is None:
            return f"{text} {code}".strip()
        if self.code == "tr-TR":
            return f"{text} {symbol}"
        if text.startswith("-"):
            return f"-{symbol}{text[1:]}"
        return f"{symbol}{text}"

    def date(self, value) -> str:
        """Format a date (or the local date of a UTC date-time)."""
        if value is None or value == "":
            return ""
        if isinstance(value, dt.datetime):
            value = self.localtime(value).date()
        return value.strftime(self.date_fmt) if isinstance(value, dt.date) else str(value)

    def localtime(self, value: dt.datetime) -> dt.datetime:
        """Convert a naive UTC date-time to the configured time zone."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value.astimezone(self.tz)

    def datetime(self, value) -> str:
        """Format a UTC date-time in the configured time zone."""
        if value is None or value == "":
            return ""
        if not isinstance(value, dt.datetime):
            return str(value)
        local = self.localtime(value)
        return local.strftime(f"{self.date_fmt} {self.time_fmt}")

    def boolean(self, value) -> str:
        """"Yes"/"No" in the interface language."""
        if value is None:
            return ""
        return self.t("common.yes") if value else self.t("common.no")

    def to_local_input(self, value: dt.datetime | None) -> str:
        """Value for an ``<input type=datetime-local>`` in the configured time zone."""
        if value is None:
            return ""
        return self.localtime(value).replace(tzinfo=None).isoformat(timespec="seconds")

    def from_local_input(self, text: str) -> dt.datetime | None:
        """Read an ``<input type=datetime-local>`` value (local time) back as naive UTC."""
        if not text:
            return None
        value = dt.datetime.fromisoformat(text)
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.tz)
        return value.astimezone(dt.UTC).replace(tzinfo=None)


@lru_cache(maxsize=64)
def get_locale(code: str, timezone: str = "UTC") -> Locale:
    """Cached :class:`Locale` for a language and time zone."""
    return Locale(code, timezone)
