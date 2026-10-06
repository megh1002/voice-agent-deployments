"""One place that calls the Claude API, so every part uses the same settings.

The API key comes from the ANTHROPIC_API_KEY environment variable, or from a
.env file in the project folder (copy .env.example to .env and fill it in).
.env is gitignored and never committed.
"""

import os
import threading
from pathlib import Path

import anthropic

from . import budget

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")

# If a safety classifier declines a request, the API retries it on Anthropic's
# recommended fallback model instead of returning nothing.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens for the default model (input, output, cache read, cache write).
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.20, 5.00)}

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

_client: anthropic.Anthropic | None = None
_usage = threading.local()  # per-thread tally, so parallel calls don't mix


def cost_of(usage: dict) -> float | None:
    price = PRICES.get(MODEL)
    return sum(usage[k] * p / 1e6 for k, p in zip(USAGE_KEYS, price)) if price else None


def start_tally(source: str = "eval"):
    """Start counting this thread's API usage. `source` labels it in the spend log."""
    _usage.calls = []
    _usage.source = source


def tally() -> dict:
    calls = getattr(_usage, "calls", [])
    total = {k: sum(c[k] for c in calls) for k in USAGE_KEYS}
    total["requests"] = len(calls)
    cost = cost_of(total)
    total["cost_usd"] = round(cost, 4) if cost is not None else None
    return total


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def create(*, effort: str, **kwargs):
    output_config = kwargs.pop("output_config", {})
    response = client().beta.messages.create(
        model=MODEL,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": effort, **output_config},
        cache_control={"type": "ephemeral"},
        **kwargs,
    )
    used = {k: getattr(response.usage, k, 0) or 0 for k in USAGE_KEYS}
    if hasattr(_usage, "calls"):
        _usage.calls.append(used)
    if (cost := cost_of(used)) is not None:
        budget.record(cost, getattr(_usage, "source", "other"))
    return response


def text_of(response) -> str:
    return " ".join(b.text for b in response.content if b.type == "text").strip()
