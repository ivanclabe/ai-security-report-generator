"""Generates data/mock_security_data.json.

Produces fully SYNTHETIC security data for demo companies. Deterministic
(seeded) so the dataset is stable across regenerations. Run:

    python scripts/generate_mock_data.py
"""
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

RANDOM_SEED = 42
START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 12, 31, tzinfo=timezone.utc)

CATEGORIES = [
    "Authentication",
    "Network",
    "Endpoint",
    "Identity",
    "Malware",
    "Data Protection",
    "Vulnerability",
    "Access Control",
]

SEVERITIES = ["low", "medium", "high", "critical"]
SEVERITY_WEIGHTS = [0.40, 0.32, 0.20, 0.08]
SEVERITY_RISK_RANGE = {
    "low": (5, 30),
    "medium": (30, 55),
    "high": (55, 80),
    "critical": (80, 99),
}

STATUS_CHOICES = ["open", "investigating", "resolved"]
STATUS_WEIGHTS = [0.20, 0.15, 0.65]

SOURCES = ["SIEM", "EDR", "IDS", "Cloud Security Posture Mgmt", "Manual Report", "Vulnerability Scanner"]

NOTIFICATION_TYPES = ["email", "slack", "sms", "ticket"]
NOTIFICATION_STATUS_CHOICES = ["sent", "acknowledged", "failed"]
NOTIFICATION_STATUS_WEIGHTS = [0.55, 0.40, 0.05]

ASSETS_BY_CATEGORY = {
    "Authentication": ["SSO Gateway", "VPN Concierge", "Identity Provider", "MFA Service"],
    "Network": ["Core Firewall", "Edge Router", "VPN Gateway", "DMZ Switch"],
    "Endpoint": ["Employee Laptop", "Kiosk Terminal", "Mobile Device Fleet", "Workstation Pool"],
    "Identity": ["Directory Service", "Privileged Access Vault", "HR Identity Feed"],
    "Malware": ["File Server", "Email Gateway", "Employee Laptop", "Build Server"],
    "Data Protection": ["Customer Database", "Backup Storage", "Data Lake", "File Share"],
    "Vulnerability": ["Web Application", "API Gateway", "Internal CRM", "Payment Service"],
    "Access Control": ["Admin Console", "Cloud IAM", "Shared Drive", "Internal Wiki"],
}

TITLE_TEMPLATES = {
    "Authentication": [
        "Repeated failed login attempts detected",
        "Unusual login location flagged",
        "MFA bypass attempt detected",
        "Credential stuffing pattern observed",
        "Password spray activity detected",
    ],
    "Network": [
        "Anomalous outbound traffic detected",
        "Port scan detected from external IP",
        "Firewall rule violation flagged",
        "Suspicious DNS query pattern",
        "Unauthorized network segment access",
    ],
    "Endpoint": [
        "Unmanaged device connected to network",
        "Endpoint protection disabled",
        "Suspicious process execution detected",
        "Unauthorized USB device usage",
    ],
    "Identity": [
        "Privilege escalation attempt detected",
        "Orphaned account with active access",
        "Excessive permission grant flagged",
        "Dormant admin account reactivated",
    ],
    "Malware": [
        "Ransomware signature detected",
        "Trojan payload quarantined",
        "Suspicious macro execution blocked",
        "Command-and-control beacon detected",
    ],
    "Data Protection": [
        "Potential data exfiltration detected",
        "Unencrypted sensitive data at rest",
        "Large volume file download flagged",
        "Backup integrity check failed",
    ],
    "Vulnerability": [
        "Critical CVE unpatched on production system",
        "Outdated TLS configuration detected",
        "Missing security patch identified",
        "Exposed debug endpoint discovered",
    ],
    "Access Control": [
        "Excessive access rights detected",
        "Shared credential usage flagged",
        "Access review overdue for critical system",
        "Unauthorized configuration change detected",
    ],
}

COMPANIES = [
    {"id": "acme-corp", "name": "ACME Corp", "industry": "Manufacturing", "country": "United States"},
    {"id": "globex-corp", "name": "Globex Corporation", "industry": "Financial Services", "country": "United Kingdom"},
    {"id": "initech-sa", "name": "Initech S.A.", "industry": "Software", "country": "Mexico"},
    {"id": "umbrella-analytics", "name": "Umbrella Analytics", "industry": "Healthcare", "country": "Canada"},
]

ALERTS_PER_COMPANY_PER_MONTH = (6, 14)


def month_range(start: datetime, end: datetime):
    current = start.replace(day=1)
    while current <= end:
        yield current
        year = current.year + (current.month // 12)
        month = current.month % 12 + 1
        current = current.replace(year=year, month=month)


def build_alert(rng: random.Random, company_id: str, month_start: datetime) -> dict:
    category = rng.choice(CATEGORIES)
    severity = rng.choices(SEVERITIES, weights=SEVERITY_WEIGHTS, k=1)[0]
    status = rng.choices(STATUS_CHOICES, weights=STATUS_WEIGHTS, k=1)[0]
    day_offset = rng.randint(0, 27)
    hour = rng.randint(0, 23)
    minute = rng.randint(0, 59)
    timestamp = month_start + timedelta(days=day_offset, hours=hour, minutes=minute)
    risk_low, risk_high = SEVERITY_RISK_RANGE[severity]
    title = rng.choice(TITLE_TEMPLATES[category])
    asset = rng.choice(ASSETS_BY_CATEGORY[category])
    return {
        "id": f"alert-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "timestamp": timestamp.isoformat(),
        "severity": severity,
        "category": category,
        "title": title,
        "description": (
            f"Synthetic demo alert: {title.lower()} affecting {asset}. "
            f"Generated for demonstration purposes only, no real incident occurred."
        ),
        "status": status,
        "source": rng.choice(SOURCES),
        "affected_asset": asset,
        "risk_score": round(rng.uniform(risk_low, risk_high), 1),
    }


def build_notifications(rng: random.Random, alert: dict) -> list[dict]:
    count = rng.randint(1, 2)
    notifications = []
    base_ts = datetime.fromisoformat(alert["timestamp"])
    for _ in range(count):
        delay_minutes = rng.randint(1, 45)
        ntype = rng.choice(NOTIFICATION_TYPES)
        nstatus = rng.choices(
            NOTIFICATION_STATUS_CHOICES, weights=NOTIFICATION_STATUS_WEIGHTS, k=1
        )[0]
        notifications.append(
            {
                "id": f"notif-{uuid.uuid4().hex[:12]}",
                "alert_id": alert["id"],
                "notification_type": ntype,
                "timestamp": (base_ts + timedelta(minutes=delay_minutes)).isoformat(),
                "status": nstatus,
            }
        )
    return notifications


def main() -> None:
    rng = random.Random(RANDOM_SEED)
    alerts: list[dict] = []
    notifications: list[dict] = []

    for company in COMPANIES:
        for month_start in month_range(START, END):
            n_alerts = rng.randint(*ALERTS_PER_COMPANY_PER_MONTH)
            for _ in range(n_alerts):
                alert = build_alert(rng, company["id"], month_start)
                alerts.append(alert)
                notifications.extend(build_notifications(rng, alert))

    alerts.sort(key=lambda a: a["timestamp"])
    notifications.sort(key=lambda n: n["timestamp"])

    dataset = {
        "_disclaimer": "All data in this file is synthetic and generated for demo purposes. It does not represent any real company or security incident.",
        "companies": COMPANIES,
        "alerts": alerts,
        "notifications": notifications,
    }

    out_path = Path(__file__).resolve().parents[1] / "data" / "mock_security_data.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dataset, indent=2))
    print(f"Wrote {len(alerts)} alerts and {len(notifications)} notifications to {out_path}")


if __name__ == "__main__":
    main()
