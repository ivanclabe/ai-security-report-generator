"""DocumentService.render() -- the DOCX path is exercised heavily already by
test_docx_builder.py; these tests focus on the format dispatch and the new
PDF conversion path (REPORT_GENERATION_ARCHITECTURE.md)."""
import shutil

import pytest

from app.services.report.document import DocumentGenerationError, render
from tests.test_docx_builder import _sample_spec


def test_render_docx_returns_a_docx_path(isolated_settings):
    path = render(_sample_spec(), "conv-doc-1", format="docx")
    assert path.suffix == ".docx"
    assert path.exists()
    assert path.stat().st_size > 0


def test_render_rejects_unsupported_format(isolated_settings):
    with pytest.raises(ValueError, match="Unsupported report format"):
        render(_sample_spec(), "conv-doc-2", format="xlsx")


def test_render_pdf_raises_a_clear_error_when_soffice_is_unavailable(monkeypatch, isolated_settings):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(DocumentGenerationError, match="LibreOffice"):
        render(_sample_spec(), "conv-doc-3", format="pdf")


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed in this environment")
def test_render_pdf_produces_a_real_pdf_file(isolated_settings):
    path = render(_sample_spec(), "conv-doc-4", format="pdf")
    assert path.suffix == ".pdf"
    assert path.exists()
    assert path.read_bytes()[:4] == b"%PDF"
