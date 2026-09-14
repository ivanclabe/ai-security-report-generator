from app.services.report.cost_estimation import estimate_cost_usd


def test_estimate_cost_for_known_model():
    usage = {"claude-sonnet-5": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
    # 1M input @ $3 + 1M output @ $15 = $18
    assert estimate_cost_usd(usage) == 18.0


def test_estimate_cost_sums_across_multiple_models():
    usage = {
        "claude-sonnet-5": {"input_tokens": 1_000_000, "output_tokens": 0},
        "claude-haiku-4-5": {"input_tokens": 1_000_000, "output_tokens": 0},
    }
    assert estimate_cost_usd(usage) == 3.0 + 1.0


def test_estimate_cost_returns_none_for_unknown_model():
    usage = {"some-future-model": {"input_tokens": 1000, "output_tokens": 1000}}
    assert estimate_cost_usd(usage) is None


def test_estimate_cost_returns_none_for_empty_usage():
    assert estimate_cost_usd({}) is None
    assert estimate_cost_usd(None) is None


def test_estimate_cost_ignores_unknown_models_but_counts_known_ones():
    usage = {
        "claude-sonnet-5": {"input_tokens": 1_000_000, "output_tokens": 0},
        "some-future-model": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    }
    assert estimate_cost_usd(usage) == 3.0
