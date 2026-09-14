"""AnalysisService -- moved verbatim from the old analyze_data node body.
Pure computation over collected_data, no I/O -- kept sync internally, the
node awaits nothing extra by calling it."""


def _trend_direction(trends: list[dict]) -> str:
    if len(trends) < 2:
        return "insufficient_data"
    first_half = trends[: len(trends) // 2]
    second_half = trends[len(trends) // 2 :]
    avg_first = sum(t["total_alerts"] for t in first_half) / len(first_half)
    avg_second = sum(t["total_alerts"] for t in second_half) / len(second_half)
    if avg_second > avg_first * 1.1:
        return "increasing"
    if avg_second < avg_first * 0.9:
        return "decreasing"
    return "stable"


def analyze(collected_data: dict) -> dict:
    data = collected_data or {}
    metrics = data.get("metrics", {})
    alerts_by_category = data.get("alerts_by_category", {})
    alerts_by_risk_level = data.get("alerts_by_risk_level", {})
    trends = data.get("trends", [])

    top_categories = sorted(alerts_by_category.items(), key=lambda kv: kv[1], reverse=True)[:5]
    total = metrics.get("total_alerts", 0)
    resolved = metrics.get("resolved_alerts", 0)
    resolution_rate = round((resolved / total) * 100, 1) if total else 0.0

    return {
        "trend_direction": _trend_direction(trends),
        "top_categories": [{"category": c, "count": n} for c, n in top_categories],
        "resolution_rate_pct": resolution_rate,
        "alerts_by_risk_level": alerts_by_risk_level,
        "critico_open_count": sum(
            1
            for a in data.get("alerts", [])
            if a.get("risk_level") == "Critico" and a.get("status") != "resolved"
        ),
    }
