"""What every workflow module looks like.

A workflow is one job the agent can do for a customer: triage a maintenance
problem, verify identity, book appointments, hand off to staff. Each one brings
its own instructions for the model, its own tools, the code behind those tools,
and its own checks on what the agent says.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import CallSession
    from core.playbook import Playbook


def tool(name: str, description: str, properties: dict | None = None) -> dict:
    """A strict tool definition: every field required, nothing extra allowed.
    Optional values use an empty string, which keeps strict mode simple."""
    properties = properties or {}
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


class Workflow:
    name = ""

    def __init__(self, playbook: Playbook):
        self.pb = playbook

    def context(self, call: CallSession) -> str | None:
        """A line of call context for the model at the start (e.g. caller ID)."""
        return None

    def prompt(self) -> str:
        """This workflow's instructions for the model."""
        return ""

    def tools(self) -> list[dict]:
        return []

    def handle(self, call: CallSession, name: str, args: dict) -> dict | None:
        """Run one of this workflow's tools. None if the tool isn't ours."""
        return None

    def check_reply(self, reply: str, call: CallSession) -> list[dict]:
        """Guardrail checks on what the agent just said."""
        return []
