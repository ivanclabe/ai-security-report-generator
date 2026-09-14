"""DocumentService -- builds the .docx (docx_builder.py, unchanged, the one
and only layout/branding implementation) and, when PDF is requested, converts
it via headless LibreOffice instead of building a second, parallel PDF
renderer. See REPORT_GENERATION_ARCHITECTURE.md for why: a second renderer
(e.g. reportlab) would duplicate every table/chart/branding rule and could
silently drift from the .docx output -- converting the exact same file
guarantees DOCX and PDF are always visually identical, because the PDF *is*
a render of that file, not an independent implementation.
"""
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.config.settings import get_settings
from app.document.docx_builder import build_document
from app.schemas.report_spec import ReportSpecification

SUPPORTED_FORMATS = ("docx", "pdf")


class DocumentGenerationError(Exception):
    pass


def render(spec: ReportSpecification, conversation_id: str, format: str = "docx") -> Path:
    if format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported report format: {format}")

    settings = get_settings()
    base_name = f"{conversation_id}-{uuid.uuid4().hex[:8]}"
    docx_path = settings.reports_dir / f"{base_name}.docx"
    build_document(spec, docx_path)

    if format == "docx":
        return docx_path
    return _convert_to_pdf(docx_path, settings.reports_dir, settings.soffice_binary)


def _convert_to_pdf(docx_path: Path, output_dir: Path, soffice_binary: str) -> Path:
    if shutil.which(soffice_binary) is None:
        raise DocumentGenerationError(
            f"No se encontró el conversor a PDF ('{soffice_binary}' / LibreOffice) en este "
            "servidor. El .docx sí se generó correctamente; instala LibreOffice o pide el "
            "informe en formato .docx mientras tanto."
        )

    # A dedicated, disposable user profile per conversion -- LibreOffice's headless mode
    # locks a shared profile directory by default, so two conversions running at the same
    # time (two reports generated concurrently) can otherwise block or fail each other.
    with tempfile.TemporaryDirectory(prefix="soffice-profile-") as profile_dir:
        try:
            result = subprocess.run(
                [
                    soffice_binary,
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation=file://{profile_dir}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(docx_path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentGenerationError(
                "La conversión a PDF superó el tiempo límite (60s)."
            ) from exc

    pdf_path = docx_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf_path.exists():
        raise DocumentGenerationError(
            f"No se pudo convertir el informe a PDF (soffice salió con código {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return pdf_path
