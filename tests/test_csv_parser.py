from io import StringIO

import pytest

from utils.csv_parser import CsvError, detect_email_column, parse_csv


def test_standard_csv_and_empty_rows():
    rows = parse_csv(StringIO("name,email,company\nJohn,john@example.com,ABC\n,,\n"))
    assert len(rows) == 1
    assert rows[0].values["company"] == "ABC"


def test_bom_and_quoted_commas(tmp_path):
    path = tmp_path / "recipients.csv"
    path.write_text("\ufeffname,work_mail,company\nSarah,sarah@example.com,\"XYZ, Inc.\"\n", encoding="utf-8")
    rows = parse_csv(path)
    assert rows[0].email == "sarah@example.com"
    assert rows[0].values["company"] == "XYZ, Inc."


def test_email_column_detection():
    assert detect_email_column(["Name", "Contact Email"]) == "Contact Email"
    assert detect_email_column(["name", "work_mail"]) == "work_mail"


def test_invalid_email_is_rejected():
    with pytest.raises(CsvError, match="invalid email"):
        parse_csv(StringIO("name,email\nJohn,not-an-email\n"))
