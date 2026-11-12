"""Character set support for exports, imports and API input.

Text inside the application is always Unicode.  Files that leave or enter the
system (SQL, TOML and CSV files, API requests) can use legacy character sets
such as DOS code pages 437/857 or Windows-1254.
"""

from __future__ import annotations

import codecs

#: (Python codec name, label) of the supported character sets.
CHARSETS: dict[str, str] = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 (BOM)",
    "utf-16": "UTF-16",
    "ascii": "ASCII (US-ASCII)",
    "cp437": "DOS 437 (US)",
    "cp850": "DOS 850 (Western Europe)",
    "cp857": "DOS 857 (Turkish)",
    "cp1252": "Windows-1252 (Western Europe)",
    "cp1254": "Windows-1254 (Turkish)",
    "iso-8859-1": "ISO-8859-1 (Latin-1)",
    "iso-8859-9": "ISO-8859-9 (Latin-5, Turkish)",
    "iso-8859-15": "ISO-8859-15 (Latin-9)",
    "mac-turkish": "Mac Turkish",
}

ALIASES = {
    "utf8": "utf-8",
    "us-ascii": "ascii",
    "dos437": "cp437",
    "dos-437": "cp437",
    "ibm437": "cp437",
    "dos857": "cp857",
    "dos-857": "cp857",
    "ibm857": "cp857",
    "dos850": "cp850",
    "windows-1254": "cp1254",
    "windows1254": "cp1254",
    "windows-2254": "cp1254",  # common typo for Windows-1254
    "windows-1252": "cp1252",
    "latin1": "iso-8859-1",
    "latin5": "iso-8859-9",
    "latin-5": "iso-8859-9",
    "latin9": "iso-8859-15",
    "macturkish": "mac-turkish",
}


def normalize(name: str | None, default: str = "utf-8") -> str:
    key = (name or "").strip().lower().replace("_", "-")
    key = ALIASES.get(key, key)
    if key in CHARSETS:
        return key
    try:
        info = codecs.lookup(key)
    except LookupError:
        return default
    for candidate in CHARSETS:
        if codecs.lookup(candidate).name == info.name:
            return candidate
    return default


def is_unicode(charset: str) -> bool:
    return charset.startswith("utf")


def http_name(charset: str) -> str:
    return {
        "utf-8-sig": "utf-8",
        "cp437": "IBM437",
        "cp850": "IBM850",
        "cp857": "IBM857",
        "cp1252": "windows-1252",
        "cp1254": "windows-1254",
        "mac-turkish": "x-mac-turkish",
    }.get(charset, charset)


def encode(text: str, charset: str, errors: str = "replace") -> bytes:
    return text.encode(charset, errors=errors)


def decode(data: bytes, charset: str) -> str:
    if charset == "utf-8" and data.startswith(codecs.BOM_UTF8):
        data = data[3:]
    return data.decode(charset, errors="replace")


def can_encode(char: str, charset: str) -> bool:
    try:
        char.encode(charset)
        return True
    except UnicodeEncodeError:
        return False


def detect_declared(data: bytes) -> str | None:
    """Find a ``charset: <name>`` declaration in the first lines of a file."""
    head = data[:400]
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8"
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    text = head.decode("ascii", errors="ignore")
    for line in text.splitlines()[:5]:
        line = line.strip().lstrip("#-").strip()
        if line.lower().startswith("charset:"):
            return normalize(line.split(":", 1)[1].strip())
    return None
