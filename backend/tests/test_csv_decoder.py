import pytest

from app.ingestion.csv_decoder import decode_alarms_csv, looks_like_html
from app.ingestion.errors import SourceFormatError

CSV = "id,cliente,description\n1,THOMAS TGS-TPS,Conexión sospechosa\n2,THOMAS TGS-TPS,NA\n"


def test_decodes_utf8_with_bom():
    df = decode_alarms_csv(("﻿" + CSV).encode("utf-8"))
    assert list(df.columns) == ["id", "cliente", "description"]  # BOM does not leak into the first header
    assert df.loc[0, "description"] == "Conexión sospechosa"


def test_decodes_windows_1252_exports():
    df = decode_alarms_csv(CSV.encode("cp1252"))
    assert df.loc[0, "description"] == "Conexión sospechosa"


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_detects_the_delimiter(delimiter):
    df = decode_alarms_csv(CSV.replace(",", delimiter).encode("utf-8"))
    assert list(df.columns) == ["id", "cliente", "description"]
    assert len(df) == 2


def test_literal_text_is_not_turned_into_missing_values():
    df = decode_alarms_csv(CSV.encode("utf-8"))
    assert df.loc[1, "description"] == "NA"


def test_header_only_csv_is_an_empty_result_not_an_error():
    df = decode_alarms_csv(b"id,cliente,timestamp\n")
    assert df.empty and list(df.columns) == ["id", "cliente", "timestamp"]


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body>Login</body></html>",
        b"\xef\xbb\xbf  \n<!DOCTYPE html><html></html>",
        b"<?xml version='1.0'?><error/>",
    ],
)
def test_html_delivered_as_csv_is_detected(body):
    assert looks_like_html(body)
    with pytest.raises(SourceFormatError) as excinfo:
        decode_alarms_csv(body)
    assert "HTML" in str(excinfo.value)


@pytest.mark.parametrize("body", [b"", b"   \n  "])
def test_empty_response_is_an_error(body):
    with pytest.raises(SourceFormatError):
        decode_alarms_csv(body)


def test_csv_text_is_not_mistaken_for_html():
    assert not looks_like_html(CSV.encode())
