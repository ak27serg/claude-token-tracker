"""
Pricing tables for Claude models (USD per million tokens).
Update these if Anthropic changes their pricing.
"""

# fmt: off
PRICING: dict[str, dict[str, float]] = {
    # Sonnet 4.6 / 4.5
    "claude-sonnet-4-6":        {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-sonnet-4-5":        {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    # Opus 4.6 / 4.5
    "claude-opus-4-6":          {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-opus-4-5":          {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    # Haiku 4.5
    "claude-haiku-4-5":         {"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-haiku-4-5-20251001":{"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    # Older Sonnet / Opus / Haiku 3.x fallbacks
    "claude-3-5-sonnet-20241022":{"input": 3.00, "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-3-opus-20240229":    {"input": 15.00,"output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
}
# fmt: on

_DEFAULT = {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}


def get_pricing(model: str) -> dict[str, float]:
    """Return pricing dict for a model, falling back to Sonnet defaults."""
    # Try exact match first, then prefix match
    if model in PRICING:
        return PRICING[model]
    for key in PRICING:
        if model.startswith(key) or key.startswith(model):
            return PRICING[key]
    return _DEFAULT


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
) -> float:
    """Return USD cost for a single API turn."""
    p = get_pricing(model)
    return (
        input_tokens * p["input"] / 1_000_000
        + output_tokens * p["output"] / 1_000_000
        + cache_creation_tokens * p["cache_write"] / 1_000_000
        + cache_read_tokens * p["cache_read"] / 1_000_000
    )
