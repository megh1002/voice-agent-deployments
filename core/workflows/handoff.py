"""Handoff: pass a call to the right staff queue with a clean summary.

The handoff is the product. The goal is that staff never have to call someone
back just to ask what they called about, so the tool requires the details staff
need, and code records whether the caller was verified.

Adapter methods needed: create_task(queue, description, priority, patient_id)
"""

from pydantic import BaseModel

from .base import Workflow, tool


class Queue(BaseModel):
    id: str
    handles: str
    callback_promise: str


class HandoffRules(BaseModel):
    queues: list[Queue]


class Handoff(Workflow):
    name = "handoff"

    def __init__(self, playbook):
        super().__init__(playbook)
        self.rules = HandoffRules.model_validate(playbook.section("handoff"))

    def prompt(self):
        queues = "\n".join(f"- {q.id}: {q.handles}" for q in self.rules.queues)
        return f"""## Handing off to staff
Anything you can't fully handle goes to the right staff queue with create_handoff.
Before you hand off, gather what staff will need so they don't have to call back
just to ask: what the caller wants, details (for symptoms: what, since when, how
bad, anything tried), the best callback number, and a good time to call.
Verify identity first when you can, but don't refuse a handoff if verification
fails; staff will verify on the callback.

Queues:
{queues}"""

    def tools(self):
        return [tool(
            "create_handoff", "Send this call to a staff queue with a structured summary.",
            {"queue": {"type": "string", "enum": [q.id for q in self.rules.queues]},
             "request": {"type": "string", "description": "What the caller wants, one sentence"},
             "details": {"type": "string", "description": "Everything staff need to act without calling to ask"},
             "callback_number": {"type": "string"},
             "best_time": {"type": "string", "description": "When to call back, or 'any time'"}},
        )]

    def handle(self, call, name, args):
        if name != "create_handoff":
            return None
        q = next(q for q in self.rules.queues if q.id == args["queue"])
        patient = call.state.get("patient")
        who = f"VERIFIED: {patient.name}, DOB {patient.birth_date}" if patient else "NOT VERIFIED"
        description = (f"{args['request']}\n{who}\nDetails: {args['details']}\n"
                       f"Callback: {args['callback_number']} ({args['best_time']})\n"
                       f"Call received {call.now:%Y-%m-%d %H:%M}")
        task_id = call.adapter.create_task(q.id, description, "routine",
                                           patient.id if patient else None)
        call.event(type="handoff", queue=q.id, task_id=task_id, verified=patient is not None,
                   request=args["request"], details=args["details"])
        return {"handed_off": True, "tell_caller": q.callback_promise}
