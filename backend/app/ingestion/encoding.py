"""Decoding of text responses from the source.

The source's pages declare UTF-8 but mix in Latin-1/Windows-1252 bytes from
static templates (e.g. "Descripci\\xf3n"). Decoding strictly would fail and
decoding everything as cp1252 would mangle the valid UTF-8 data. This decodes
UTF-8 and falls back to cp1252 only for the individual bytes that are not valid
UTF-8, so both parts come out right.
"""
import codecs

_ERROR_HANDLER = "ingestion_cp1252_fallback"


def _cp1252_fallback(error: UnicodeDecodeError) -> tuple[str, int]:
    bad = error.object[error.start : error.end]
    return bad.decode("cp1252", errors="replace"), error.end


codecs.register_error(_ERROR_HANDLER, _cp1252_fallback)


def decode_source_text(content: bytes) -> str:
    return content.decode("utf-8-sig", errors=_ERROR_HANDLER)
