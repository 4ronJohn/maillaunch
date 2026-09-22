from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


class CsvError(ValueError):
    """Raised when a recipient CSV cannot be used for a campaign."""


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str
    values: dict[str, str]


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def detect_email_column(fieldnames: list[str]) -> str:
    for fieldname in fieldnames:
        if "email" in fieldname.lower() or "mail" in fieldname.lower():
            return fieldname
    raise CsvError("could not detect an email column; use a header containing 'email' or 'mail'")


def _parse_rows(handle: TextIO) -> list[Recipient]:
    reader = csv.DictReader(handle)
    if not reader.fieldnames:
        raise CsvError("CSV must contain a header row")
    fieldnames = [field.strip() for field in reader.fieldnames]
    if any(not field for field in fieldnames):
        raise CsvError("CSV contains an empty column name")
    email_column = detect_email_column(fieldnames)
    recipients: list[Recipient] = []
    for row_number, raw_row in enumerate(reader, start=2):
        values = {field: (raw_row.get(original) or "").strip() for original, field in zip(reader.fieldnames, fieldnames)}
        if not any(values.values()):
            continue
        email = values[email_column]
        if not _EMAIL_PATTERN.match(email):
            raise CsvError(f"row {row_number} has an invalid email address: {email!r}")
        name = values.get("name", "").strip()
        recipients.append(Recipient(email=email, name=name, values=values))
    return recipients


def parse_csv(source: str | Path | TextIO) -> list[Recipient]:
    if hasattr(source, "read"):
        return _parse_rows(source)  # type: ignore[arg-type]
    with Path(source).open("r", encoding="utf-8-sig", newline="") as handle:
        return _parse_rows(handle)
