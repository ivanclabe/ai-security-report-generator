"""ValidationService -- thin wrapper over ReportSpecification's own validation
methods (unchanged). Centralizes "is this report allowed to ship" as one call
site shared by both the conversational node and the future deterministic
endpoint, per ARCHITECTURE_TARGET.md §3.1."""
import re

from app.schemas.report_spec import ReportSpecification


def validate(spec: ReportSpecification, known_alarm_numbers: set[str]) -> list[str]:
    """Section by section, before the document is drawn: business rules, every cited alarm
    exists, and every table/chart is internally consistent."""
    errors = spec.validate_business_rules()
    if errors:
        return errors
    return spec.validate_evidence(known_alarm_numbers) + validate_layout(spec)


def _iter_blocks(spec: ReportSpecification):
    for section in spec.sections:
        for block in section.blocks:
            yield section.number, block
        for sub in section.subsections:
            for block in sub.blocks:
                yield sub.number, block


def _table_errors(where: str, table) -> list[str]:
    errors = []
    width = sum(c.colspan for c in table.header_rows[0]) if table.header_rows else 0
    for row in table.rows:
        if sum(c.colspan for c in row) != width:
            errors.append(f"Sección {where}: una fila de la tabla no coincide con sus columnas.")
            break
    return errors


def validate_layout(spec: ReportSpecification) -> list[str]:
    errors: list[str] = []
    for where, block in _iter_blocks(spec):
        kind = getattr(block, "kind", None)
        if kind == "chart":
            for series in block.series:
                if len(series.values) != len(block.categories):
                    errors.append(f"Sección {where}: el gráfico «{block.title}» tiene series de distinto largo.")
                if any(v < 0 for v in series.values):
                    errors.append(f"Sección {where}: el gráfico «{block.title}» tiene valores negativos.")
        elif kind == "table":
            errors += _table_errors(where, block)
        elif kind == "side_by_side":
            errors += _table_errors(where, block.left) + _table_errors(where, block.right)
    return errors


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def unsupported_numbers(text: str, allowed: set[str]) -> list[str]:
    """Figures in `text` that the report's facts cannot justify."""
    return [n for n in _NUMBER.findall(text or "") if n not in allowed]


def ground_recommendations(recommendations, allowed_numbers: set[str], known_alarms: set[str]):
    """Keep only recommendations whose every figure and cited alarm is backed by the data.
    Returns (kept, notes) -- notes say what was removed and why (stored with the version)."""
    kept, notes = [], []
    for finding in recommendations:
        bad_numbers = unsupported_numbers(finding.statement, allowed_numbers)
        cited = finding.evidence.source_alarm_numbers if finding.evidence else []
        unknown = [n for n in cited if n not in known_alarms]
        if bad_numbers or unknown:
            reason = []
            if bad_numbers:
                reason.append(f"cifras sin respaldo en los datos: {', '.join(bad_numbers)}")
            if unknown:
                reason.append(f"alarmas inexistentes: {', '.join(unknown)}")
            notes.append(f"Recomendación descartada ({'; '.join(reason)}): {finding.statement[:160]}")
            continue
        kept.append(finding)
    return kept, notes
