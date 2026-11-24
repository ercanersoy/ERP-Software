"""A small TOML writer (Python only ships a TOML reader, ``tomllib``).

When a non Unicode character set is requested, characters that can not be
represented in that character set are written as ``\\uXXXX`` escapes, so no
information is lost.
"""

from __future__ import annotations

import datetime as dt
import decimal
import re

from . import charsets

BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


class TomlWriter:
    """Serialises dictionaries of the backup format as TOML 1.0 text."""
    def __init__(self, charset: str = "utf-8"):
        """``charset`` decides which characters may appear unescaped in strings."""
        self.charset = charset
        self.unicode = charsets.is_unicode(charset)

    # ------------------------------------------------------------------ values
    def key(self, key: str) -> str:
        """A key: bare when possible (``name``), quoted otherwise (``"Müşteri adı"``)."""
        return key if BARE_KEY.match(key) else self.string(key)

    def string(self, text: str) -> str:
        """A basic (double quoted) TOML string.

        Control characters are always escaped.  Other characters are written as
        they are when the target character set has them, else as ``\\uXXXX`` or
        ``\\UXXXXXXXX`` escapes, so even a DOS 857 file keeps every character.
        """
        out = ['"']
        for ch in text:
            if ch in _ESCAPES:
                out.append(_ESCAPES[ch])
            elif ord(ch) < 0x20 or ord(ch) == 0x7F:
                out.append(f"\\u{ord(ch):04X}")
            elif ord(ch) < 0x80 or (self.unicode and not 0xD800 <= ord(ch) <= 0xDFFF):
                out.append(ch)
            elif not self.unicode and charsets.can_encode(ch, self.charset):
                out.append(ch)
            elif ord(ch) <= 0xFFFF:
                out.append(f"\\u{ord(ch):04X}")
            else:
                out.append(f"\\U{ord(ch):08X}")
        out.append('"')
        return "".join(out)

    def value(self, value) -> str:
        """Any supported Python value as TOML.

        Decimals are written as strings: TOML floats are binary floating point
        and would change amounts such as 0.10.  ``None`` values are left out,
        TOML has no null; readers treat missing keys as NULL.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value != value:
                return "nan"
            if value in (float("inf"), float("-inf")):
                return "inf" if value > 0 else "-inf"
            return repr(value)
        if isinstance(value, decimal.Decimal):
            return self.string(format(value, "f"))
        if isinstance(value, dt.datetime):
            if value.tzinfo is not None:
                return value.isoformat()
            return value.isoformat(timespec="microseconds" if value.microsecond else "seconds")
        if isinstance(value, (dt.date, dt.time)):
            return value.isoformat()
        if isinstance(value, (list, tuple)):
            items = [self.value(v) for v in value if v is not None]
            return "[" + ", ".join(items) + "]"
        if isinstance(value, dict):
            items = [f"{self.key(k)} = {self.value(v)}" for k, v in value.items() if v is not None]
            return "{ " + ", ".join(items) + " }" if items else "{}"
        if isinstance(value, (bytes, bytearray, memoryview)):
            return self.string(bytes(value).hex())
        return self.string(str(value))

    # ------------------------------------------------------------------ tables
    @staticmethod
    def _is_table_array(value) -> bool:
        """True for a non-empty list of dictionaries, written as ``[[array.of.tables]]``."""
        return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)

    def _table(self, lines: list[str], path: list[str], data: dict, header: str | None) -> None:
        """Append one table to ``lines``.

        TOML requires a table's plain keys before its sub-tables and arrays of
        tables, hence the three passes over ``data``.
        """
        scalars = [(k, v) for k, v in data.items()
                   if v is not None and not isinstance(v, dict) and not self._is_table_array(v)]
        tables = [(k, v) for k, v in data.items() if isinstance(v, dict)]
        arrays = [(k, v) for k, v in data.items() if self._is_table_array(v)]
        if header is not None:
            if lines:
                lines.append("")
            lines.append(header)
        for k, v in scalars:
            lines.append(f"{self.key(k)} = {self.value(v)}")
        for k, v in tables:
            sub = path + [k]
            self._table(lines, sub, v, "[" + ".".join(self.key(p) for p in sub) + "]")
        for k, items in arrays:
            sub = path + [k]
            for item in items:
                self._table(lines, sub, item, "[[" + ".".join(self.key(p) for p in sub) + "]]")

    def dumps(self, data: dict, comments: list[str] | None = None) -> str:
        """The whole document, preceded by ``# comment`` lines."""
        lines: list[str] = []
        for c in comments or []:
            lines.append("# " + c)
        if comments:
            lines.append("")
        body: list[str] = []
        self._table(body, [], data, None)
        return "\n".join(lines + body) + "\n"


def dumps(data: dict, charset: str = "utf-8", comments: list[str] | None = None) -> str:
    """Serialise ``data`` as TOML for the given character set (see :class:`TomlWriter`)."""
    return TomlWriter(charset).dumps(data, comments)
