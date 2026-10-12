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
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
}
# Server-side refusal fallback and effort levels aren't supported on every model.
SUPPORTS_FALLBACK = {"claude-opus-5-5", "claude-sonnet-5-5"}
SUPPORTS_EFFORT = {"claude-opus-5-5", "claude-sonnet-5-5"}

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

_client: anthropic.Anthropic | None = None
_usage = threading.local()  # per-thread tally, so parallel calls don't mix


def current_model() -> str:
    return getattr(_usage, "model", None) or MODEL


def use_model(name: str | None):
    """Use a different model for this thread's next calls (e.g. a faster one for voice)."""
    _usage.model = name


def cost_of(usage: dict, model: str | None = None) -> float | None:
    price = PRICES.get(model or current_model())
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
    model = current_model()
    output_config = kwargs.pop("output_config", {})
    if model in SUPPORTS_EFFORT:
        output_config = {"effort": effort, **output_config}
    extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if model in SUPPORTS_FALLBACK else {}
    if output_config:
        extra["output_config"] = output_config
    response = client().beta.messages.create(
        model=model, cache_control={"type": "ephemeral"}, **extra, **kwargs)
    used = {k: getattr(response.usage, k, 0) or 0 for k in USAGE_KEYS}
    if hasattr(_usage, "calls"):
        _usage.calls.append(used)
    if (cost := cost_of(used, model)) is not None:
        budget.record(cost, getattr(_usage, "source", "other"))
    return response


def text_of(response) -> str:
    return " ".join(b.text for b in response.content if b.type == "text").strip()
