import json
from types import SimpleNamespace as NS

import pytest

from core.agent import CallSession
from core.notifier import Notifier


@pytest.fixture
def outbox(tmp_path):
    return tmp_path / "outbox.jsonl"


def make_call(customer, phone, now, outbox):
    """A call with no model attached: tests drive the tools directly."""
    adapter = customer.make_adapter(lambda: now)
    call = CallSession(customer.PLAYBOOK, adapter, Notifier("outbox", outbox), phone, now)
    call.start()
    return call


def use_tool(call, name, **args) -> dict:
    """Run a tool exactly as the model would, return its parsed result."""
    out = call._run_tool(NS(name=name, input=args, id=f"tu_{name}"))
    return json.loads(out["content"])


def sent(outbox) -> list[dict]:
    return [json.loads(l) for l in outbox.read_text().splitlines()] if outbox.exists() else []
