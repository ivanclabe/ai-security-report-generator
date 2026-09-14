"""ValidationService -- thin wrapper over ReportSpecification's own validation
methods (unchanged). Centralizes "is this report allowed to ship" as one call
site shared by both the conversational node and the future deterministic
endpoint, per ARCHITECTURE_TARGET.md §3.1."""
from app.schemas.report_spec import ReportSpecification


def validate(spec: ReportSpecification, known_alarm_numbers: set[str]) -> list[str]:
    errors = spec.validate_business_rules()
    if errors:
        return errors
    return spec.validate_evidence(known_alarm_numbers)
