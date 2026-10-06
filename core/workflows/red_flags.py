"""Red flags: situations where the only right move is a safety instruction.

Two kinds, with opposite instructions:
  end_call      - e.g. chest pain: "hang up and call 911 now", no questions
  stay_on_line  - e.g. suicidal thoughts: give 988, alert staff, do NOT hang up.
                  Code enforces this: end_call is refused while a stay_on_line
                  flag is active.

Adapter methods needed: create_task(queue, description, priority, patient_id)
"""

from typing import Literal

from pydantic import BaseModel

from .base import Workflow, tool


class RedFlag(BaseModel):
    id: str
    description: str
    say: str
    then: Literal["end_call", "stay_on_line"]
    alert_queue: str


class RedFlagRules(BaseModel):
    flags: list[RedFlag]
    staff_alert_phone: str


class RedFlags(Workflow):
    name = "red_flags"

    def __init__(self, playbook):
        super().__init__(playbook)
        self.rules = RedFlagRules.model_validate(playbook.section("red_flags"))

    def prompt(self):
        flags = "\n".join(f'- {f.id}: {f.description}\n  SAY IMMEDIATELY: "{f.say}"'
                          for f in self.rules.flags)
        return f"""## Red flags (these come before everything else)
If at any point the caller describes one of these, say its line immediately, word
for word, before any other question, then call report_red_flag. Don't verify
identity first. Don't ask follow-up questions about the symptoms.

{flags}"""

    def tools(self):
        return [tool(
            "report_red_flag", "Record a red flag and alert staff. Returns what to do next.",
            {"flag": {"type": "string", "enum": [f.id for f in self.rules.flags]},
             "what_caller_said": {"type": "string"}},
        )]

    def handle(self, call, name, args):
        if name != "report_red_flag":
            return None
        flag = next(f for f in self.rules.flags if f.id == args["flag"])
        patient = call.state.get("patient")
        task_id = call.adapter.create_task(
            flag.alert_queue,
            f"RED FLAG ({flag.id}) at {call.now:%H:%M}: {args['what_caller_said']}\n"
            f"Caller phone: {call.caller_phone}. Agent said: {flag.say}",
            "stat", patient.id if patient else None)
        alerted = call.notifier.send_sms(self.rules.staff_alert_phone, (
            f"{self.pb.customer} RED FLAG: {flag.id}. Caller {call.caller_phone}. "
            + ("Caller is ON THE LINE now, join the call." if flag.then == "stay_on_line"
               else "Told to call 911.")))
        call.event(type="red_flag", flag=flag.id, then=flag.then, task_id=task_id,
                   staff_alerted=alerted)
        if flag.then == "stay_on_line":
            call.state["keep_on_line"] = True
            return {"next": "Stay on the line. A staff member has been alerted to join. Keep "
                            "talking gently, listen, and do not end the call."}
        return {"next": "Repeat that they should hang up and call 911 now, then end the call."}
