"""User definable field types.

Each field type knows how it is stored in the database, how it is entered in
the user interface and how values are converted from forms, JSON, CSV and TOML.
"""

from __future__ import annotations

import datetime as dt
import decimal
import re
from dataclasses import dataclass

from .db import Column

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
CURRENCIES = ("TRY", "USD", "EUR", "GBP", "CHF", "JPY", "CNY", "RUB", "SAR", "AED", "AZN")


class ValidationError(ValueError):
    """Raised when a value can not be converted; ``key`` is a translation key."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


@dataclass(frozen=True, slots=True)
class FieldType:
    name: str
    column_kind: str
    is_file: bool = False
    accept: str = ""


FIELD_TYPES: dict[str, FieldType] = {
    ft.name: ft
    for ft in (
        FieldType("text", "varchar"),
        FieldType("longtext", "text"),
        FieldType("integer", "int"),
        FieldType("decimal", "decimal"),
        FieldType("float", "float"),
        FieldType("currency", "decimal"),
        FieldType("boolean", "bool"),
        FieldType("date", "date"),
        FieldType("datetime", "datetime"),
        FieldType("choice", "varchar"),
        FieldType("email", "varchar"),
        FieldType("reference", "int"),
        FieldType(
            "document",
            "int",
            True,
            ".pdf,.txt,.csv,.rtf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.ods,.odp,.xml,.json,.zip,.7z",
        ),
        FieldType("image", "int", True, "image/png,image/jpeg,image/gif,image/webp,image/bmp"),
        FieldType("video", "int", True, "video/mp4,video/webm,video/ogg,video/quicktime"),
    )
}

FILE_KINDS = ("document", "image", "video")

IMAGE_MIME = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"BM": "image/bmp",
}


def sniff_image(head: bytes) -> str | None:
    for magic, mime in IMAGE_MIME.items():
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_video(head: bytes) -> str | None:
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        return "video/quicktime" if brand == b"qt  " else "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"OggS"):
        return "video/ogg"
    return None


@dataclass(slots=True)
class Field:
    """A user defined field of an entity."""

    id: int | None
    entity_id: int | None
    name: str
    label: str
    field_type: str
    required: bool = False
    is_unique: bool = False
    show_in_list: bool = True
    max_length: int | None = None
    decimal_places: int | None = None
    currency: str | None = None
    options: str | None = None
    ref_entity: str | None = None
    default_value: str | None = None
    help_text: str | None = None
    sort_order: int = 0

    @property
    def type(self) -> FieldType:
        return FIELD_TYPES[self.field_type]

    @property
    def is_file(self) -> bool:
        return self.type.is_file

    @property
    def choices(self) -> list[str]:
        return [line.strip() for line in (self.options or "").splitlines() if line.strip()]

    @property
    def scale(self) -> int:
        if self.field_type == "currency":
            return 4 if self.decimal_places is None else self.decimal_places
        return 2 if self.decimal_places is None else self.decimal_places

    def column(self) -> Column:
        kind = self.type.column_kind
        match self.field_type:
            case "text":
                return Column(self.name, kind, length=self.max_length or 255)
            case "choice" | "email":
                return Column(self.name, kind, length=255)
            case "decimal":
                return Column(self.name, kind, precision=18, scale=self.scale)
            case "currency":
                return Column(self.name, kind, precision=19, scale=self.scale)
        return Column(self.name, kind)

    # ------------------------------------------------------------------ parsing
    def parse(self, raw):
        """Convert a value from a form/JSON/CSV/TOML into a Python value.

        Returns ``None`` for empty values.  Raises :class:`ValidationError`.
        """
        if isinstance(raw, str):
            raw = raw.strip()
        if raw is None or raw == "":
            if self.field_type == "boolean":
                return False
            return None
        match self.field_type:
            case "text" | "longtext":
                value = str(raw)
                limit = self.max_length if self.field_type == "text" else None
                if limit and len(value) > limit:
                    raise ValidationError("error.too_long", max=limit)
                return value
            case "email":
                value = str(raw)
                if not EMAIL_RE.match(value) or len(value) > 255:
                    raise ValidationError("error.invalid_email")
                return value
            case "choice":
                value = str(raw)
                if self.choices and value not in self.choices:
                    raise ValidationError("error.invalid_choice")
                return value
            case "integer" | "reference" | "document" | "image" | "video":
                if isinstance(raw, bool):
                    raise ValidationError("error.invalid_integer")
                if isinstance(raw, float) and raw.is_integer():
                    raw = int(raw)
                try:
                    value = int(str(raw).replace(" ", ""))
                except ValueError:
                    raise ValidationError("error.invalid_integer") from None
                if not -(2**63) <= value < 2**63:
                    raise ValidationError("error.invalid_integer")
                return value
            case "decimal" | "currency":
                return self._parse_decimal(raw)
            case "float":
                if isinstance(raw, bool):
                    raise ValidationError("error.invalid_number")
                try:
                    value = float(str(raw).replace(",", "."))
                except ValueError:
                    raise ValidationError("error.invalid_number") from None
                if value != value or value in (float("inf"), float("-inf")):
                    raise ValidationError("error.invalid_number")
                return value
            case "boolean":
                if isinstance(raw, bool):
                    return raw
                if isinstance(raw, (int, float)):
                    return bool(raw)
                return str(raw).lower() in ("1", "true", "yes", "on", "evet", "e", "y", "x")
            case "date":
                if isinstance(raw, dt.datetime):
                    return raw.date()
                if isinstance(raw, dt.date):
                    return raw
                return parse_date(str(raw))
            case "datetime":
                if isinstance(raw, dt.datetime):
                    return raw.replace(tzinfo=None) if raw.tzinfo is None else raw.astimezone(dt.UTC).replace(tzinfo=None)
                if isinstance(raw, dt.date):
                    return dt.datetime(raw.year, raw.month, raw.day)
                return parse_datetime(str(raw))
        raise ValidationError("error.invalid_value")  # pragma: no cover

    def _parse_decimal(self, raw) -> decimal.Decimal:
        if isinstance(raw, bool):
            raise ValidationError("error.invalid_number")
        if isinstance(raw, float):
            raw = repr(raw)
        text = str(raw).replace(" ", "").replace(" ", "")
        if "," in text and "." in text:
            # Use the last separator as the decimal point ("1.234,56" or "1,234.56").
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        try:
            value = decimal.Decimal(text)
        except decimal.InvalidOperation:
            raise ValidationError("error.invalid_number") from None
        if not value.is_finite():
            raise ValidationError("error.invalid_number")
        quant = decimal.Decimal(1).scaleb(-self.scale)
        value = value.quantize(quant, rounding=decimal.ROUND_HALF_UP)
        precision = 19 if self.field_type == "currency" else 18
        if len(value.as_tuple().digits) > precision:
            raise ValidationError("error.number_too_large")
        return value

    def normalize(self, value):
        """Normalise a value read back from the database driver."""
        if value is None:
            return None
        match self.field_type:
            case "boolean":
                if isinstance(value, (bytes, bytearray)):
                    return value not in (b"\x00", b"0", b"")
                return bool(int(value)) if not isinstance(value, bool) else value
            case "integer" | "reference" | "document" | "image" | "video":
                return int(value)
            case "decimal" | "currency":
                value = value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))
                try:
                    return value.quantize(decimal.Decimal(1).scaleb(-self.scale))
                except decimal.InvalidOperation:
                    return value
            case "float":
                return float(value)
            case "date":
                if isinstance(value, dt.datetime):
                    return value.date()
                if isinstance(value, str):
                    return parse_date(value)
                return value
            case "datetime":
                if isinstance(value, str):
                    return parse_datetime(value)
                if isinstance(value, dt.datetime) and value.tzinfo is not None:
                    return value.astimezone(dt.UTC).replace(tzinfo=None)
                return value
        return value

    def to_json(self, value):
        if value is None:
            return None
        if isinstance(value, decimal.Decimal):
            return str(value)
        if isinstance(value, (dt.datetime, dt.date)):
            return value.isoformat()
        return value

    def to_text(self, value) -> str:
        """Plain, locale independent text (used for CSV)."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, decimal.Decimal):
            return format(value, "f")
        if isinstance(value, dt.datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        if isinstance(value, dt.date):
            return value.isoformat()
        return str(value)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "field_type": self.field_type,
            "required": self.required,
            "is_unique": self.is_unique,
            "show_in_list": self.show_in_list,
            "max_length": self.max_length,
            "decimal_places": self.decimal_places,
            "currency": self.currency,
            "options": self.options,
            "ref_entity": self.ref_entity,
            "default_value": self.default_value,
            "help_text": self.help_text,
            "sort_order": self.sort_order,
        }


def parse_date(text: str) -> dt.date:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        raise ValidationError("error.invalid_date") from None


def parse_datetime(text: str) -> dt.datetime:
    text = text.strip().replace("Z", "+00:00")
    try:
        value = dt.datetime.fromisoformat(text)
    except ValueError:
        value = None
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"):
            try:
                value = dt.datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if value is None:
            try:
                d = parse_date(text)
            except ValidationError:
                raise ValidationError("error.invalid_datetime") from None
            value = dt.datetime(d.year, d.month, d.day)
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    return value


def field_from_row(row: dict) -> Field:
    return Field(
        id=row.get("id"),
        entity_id=row.get("entity_id"),
        name=row["name"],
        label=row["label"],
        field_type=row["field_type"],
        required=bool(row.get("required")),
        is_unique=bool(row.get("is_unique")),
        show_in_list=bool(row.get("show_in_list")),
        max_length=row.get("max_length"),
        decimal_places=row.get("decimal_places"),
        currency=row.get("currency"),
        options=row.get("options"),
        ref_entity=row.get("ref_entity"),
        default_value=row.get("default_value"),
        help_text=row.get("help_text"),
        sort_order=int(row.get("sort_order") or 0),
    )
