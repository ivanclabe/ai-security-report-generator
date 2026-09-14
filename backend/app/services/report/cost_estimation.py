"""Estimated USD cost from aggregated LLM token usage (QUALITY_OBSERVABILITY.md
-- "costos estimados" per execution). Deliberately approximate: rates below are
a best-effort snapshot, not billing data -- verify against Anthropic's current
published pricing (https://www.claude.com/pricing) before using this for real
budget decisions. An unknown model returns None rather than a guessed number.
"""

# USD per 1,000,000 tokens, (input_rate, output_rate). Add a model here when the
# app starts using it -- get_chat_model()'s configured model is what actually
# shows up in usage_metadata, keyed by the exact model string sent to the API.
PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-5": (15.0, 75.0),
}


def estimate_cost_usd(usage_metadata: dict | None) -> float | None:
    """usage_metadata is the dict langchain_core.callbacks.get_usage_metadata_callback()
    produces: {model_name: {"input_tokens": int, "output_tokens": int, ...}}.
    Returns None (not a guess) if no model in the usage is in the pricing table."""
    if not usage_metadata:
        return None
    total = 0.0
    matched_any = False
    for model_name, usage in usage_metadata.items():
        rates = PRICING_PER_MILLION_TOKENS.get(model_name)
        if not rates:
            continue
        matched_any = True
        input_rate, output_rate = rates
        total += (usage.get("input_tokens", 0) / 1_000_000) * input_rate
        total += (usage.get("output_tokens", 0) / 1_000_000) * output_rate
    return round(total, 6) if matched_any else None
