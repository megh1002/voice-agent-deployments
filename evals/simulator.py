"""An AI that plays the caller, so we can run dozens of test calls without people."""

from core import llm

HANGUP = "[HANGUP]"


def caller_system_prompt(persona: str) -> str:
    return f"""You are role-playing a person calling an apartment building's after-hours
maintenance phone line. This is a test of the phone agent; stay in character.

Who you are and what's happening:
{persona}

How to talk:
- Like a real person on the phone: short, natural, sometimes a little vague.
- Only share details when asked, unless your situation says otherwise.
- Follow any instructions in your situation about what to say and when.
- Never mention that you are an AI or that this is a test.
- When the call is naturally over (the agent said goodbye, or you have what you
  need and said goodbye), end your message with {HANGUP}."""


class SimulatedCaller:
    def __init__(self, persona: str):
        self.system = caller_system_prompt(persona)
        # From the caller's side, the agent is the "user" and the caller is the "assistant".
        self.messages: list[dict] = []

    def respond(self, agent_said: str) -> tuple[str, bool]:
        """Returns (what the caller says, whether they hung up)."""
        self.messages.append({"role": "user", "content": agent_said})
        resp = llm.create(effort="low", max_tokens=2000, system=self.system,
                          messages=self.messages)
        text = llm.text_of(resp)
        self.messages.append({"role": "assistant", "content": resp.content})
        hung_up = HANGUP in text
        return text.replace(HANGUP, "").strip(), hung_up
