"""The phone agent: one CallSession per call, the same code for every customer.

Text in, text out. The voice platform (added later) turns speech into text,
calls reply(), and speaks the answer. Evals and the web app call the exact same
code, so what we test is what we ship.

The agent is assembled from the workflows the customer's playbook switches on.
Who does what:
  code   - plays the disclosure, enforces identity, applies the playbook's rules,
           books, pages, hands off, writes the call record, checks every reply
  model  - talks to the caller and decides which tool fits what they said
"""

import json
from datetime import datetime

from . import llm
from .guardrails import check_reply
from .notifier import Notifier
from .playbook import Playbook
from .workflows import build_workflows
from .workflows.base import tool

MAX_TOOL_ROUNDS = 6


def build_system_prompt(pb: Playbook, workflows) -> str:
    never = "\n".join(f"- {n}" for n in pb.never)
    sections = "\n\n".join(p for w in workflows if (p := w.prompt()))
    return f"""You answer the phone for {pb.customer}. You are an AI assistant. The caller
has already heard that, and that the call is recorded.

How to work:
- Safety first. If the caller describes an emergency covered below, follow those
  instructions immediately, before anything else.
- Only state facts your tools gave you. Never guess or invent details about
  appointments, people, schedules, or what staff will do.
- Tell the caller what actually happened, based on tool results. Don't promise
  anything a tool didn't confirm.
- When the caller is done, say goodbye and call end_call.

{sections}

Never:
{never}

If the caller asks for a person: {pb.human_request}

This is a phone call. Speak in short, plain sentences, one or two at a time. No
lists, no formatting, no emoji. Be calm and kind; people calling are often
stressed or unwell. If the caller speaks another language, reply in that language.
Office hours: {pb.office_hours}. Office phone: {pb.office_phone}."""


END_CALL = tool("end_call", "Hang up, after saying goodbye.")


class CallSession:
    def __init__(self, playbook: Playbook, adapter, notifier: Notifier,
                 caller_phone: str, now: datetime):
        self.playbook, self.adapter, self.notifier = playbook, adapter, notifier
        self.caller_phone, self.now = caller_phone, now
        self.workflows = build_workflows(playbook)
        self.system = build_system_prompt(playbook, self.workflows)
        self.tools = [t for w in self.workflows for t in w.tools()] + [END_CALL]
        self.state: dict = {}
        self.ended = False
        self.messages: list[dict] = []
        self.record = {
            "customer": playbook.customer, "caller_phone": caller_phone,
            "started_at": now.isoformat(), "transcript": [], "tool_calls": [],
            "events": [], "guardrail_flags": [], "refusals": 0, "ended_by_agent": False,
        }

    # ---- helpers workflows use -------------------------------------------------

    def event(self, **ev) -> dict:
        self.record["events"].append(ev)
        return ev

    def events(self, *types: str) -> list[dict]:
        return [e for e in self.record["events"] if e["type"] in types]

    def _say(self, speaker: str, text: str):
        self.record["transcript"].append({"speaker": speaker, "text": text})

    # ---- the call ----------------------------------------------------------------

    def start(self) -> str:
        """The greeting, played by code so the disclosure can never be skipped."""
        context = " ".join(c for w in self.workflows if (c := w.context(self)))
        self.messages = [
            {"role": "user", "content": (
                f"[Call connected at {self.now:%A %-I:%M %p, %B %-d, %Y}. {context} "
                "The greeting below has already been played to the caller.]")},
            {"role": "assistant", "content": self.playbook.disclosure},
        ]
        self._say("agent", self.playbook.disclosure)
        return self.playbook.disclosure

    def reply(self, caller_text: str) -> str:
        n_messages, n_transcript = len(self.messages), len(self.record["transcript"])
        try:
            return self._reply(caller_text)
        except Exception:
            # If the API failed before the agent did anything, undo the caller's
            # turn so it can simply be retried. If tools already ran (a booking,
            # a page), keep the history: those side effects really happened.
            if len(self.messages) == n_messages + 1:
                del self.messages[n_messages:]
                del self.record["transcript"][n_transcript:]
            raise

    def _reply(self, caller_text: str) -> str:
        self._say("caller", caller_text)
        self.messages.append({"role": "user", "content": caller_text})
        spoken: list[str] = []

        for _ in range(MAX_TOOL_ROUNDS):
            resp = llm.create(effort="low", max_tokens=4000, system=self.system,
                              tools=self.tools, messages=self.messages)
            if resp.stop_reason == "refusal":
                self.record["refusals"] += 1
                spoken.append("I'm sorry, I'm having trouble. If this is an emergency, call "
                              f"911. Otherwise please call {self.playbook.office_phone}.")
                break
            self.messages.append({"role": "assistant", "content": resp.content})
            if text := llm.text_of(resp):
                spoken.append(text)
            if resp.stop_reason != "tool_use":
                break
            results = [self._run_tool(b) for b in resp.content if b.type == "tool_use"]
            self.messages.append({"role": "user", "content": results})
            if self.ended:
                break

        reply = " ".join(spoken)
        self._say("agent", reply)
        self.record["guardrail_flags"] += check_reply(reply, self)
        return reply

    def _run_tool(self, block) -> dict:
        name, args = block.name, block.input
        if name == "end_call":
            if self.state.get("keep_on_line"):
                result = {"ok": False, "error": "Do not end this call. A staff member is joining."}
            else:
                self.ended = self.record["ended_by_agent"] = True
                result = {"ok": True}
        else:
            result = next((r for w in self.workflows
                           if (r := w.handle(self, name, args)) is not None),
                          {"error": f"unknown tool {name}"})
        self.record["tool_calls"].append({"tool": name, "input": args, "result": result})
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": json.dumps(result, default=str)}
