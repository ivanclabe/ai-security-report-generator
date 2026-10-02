"""Bytes of the alarms CSV export -> DataFrame, tolerant of how PHP/Excel-era
exports usually differ: UTF-8 with BOM or Windows-1252, comma/semicolon/tab
delimiters. Also recognizes the most common silent failure of web exports: a
login or error *HTML page* delivered with HTTP 200.
"""
import io

import pandas as pd

from app.ingestion.errors import SourceFormatError

_CANDIDATE_DELIMITERS = (",", ";", "\t", "|")


def looks_like_html(content: bytes) -> bool:
    head = content[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<") or b"<html" in head or b"<!doctype" in head


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _detect_delimiter(header_line: str) -> str:
    counts = {d: header_line.count(d) for d in _CANDIDATE_DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def decode_alarms_csv(content: bytes) -> pd.DataFrame:
    if not content or not content.strip():
        raise SourceFormatError("La fuente devolvió una respuesta vacía (sin encabezados CSV).")
    if looks_like_html(content):
        raise SourceFormatError(
            "La fuente devolvió una página HTML en lugar del CSV de alarmas: suele indicar sesión/credenciales "
            "inválidas, un parámetro rechazado o una página de error."
        )

    text = _decode_text(content)
    header_line = text.lstrip("\r\n").split("\n", 1)[0]
    delimiter = _detect_delimiter(header_line)
    try:
        # dtype=str keeps ids/dates/scores exactly as sent; keep_default_na=False stops
        # pandas from turning literal text such as "NA" into missing values.
        df = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise SourceFormatError(f"No se pudo interpretar el CSV de alarmas ({type(exc).__name__}).") from exc

    df.columns = [str(c).strip() for c in df.columns]
    return df
