"""A customer's playbook: their rules, written down, loaded from playbook.yaml.

The parts every customer has (greeting, hours, never-list) live here. Each
workflow a customer switches on (triage, scheduling, ...) has its own section in
the same file, which that workflow's module reads and checks.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class Playbook(BaseModel):
    model_config = ConfigDict(extra="allow")  # workflow sections live alongside

    customer: str
    timezone: str
    disclosure: str
    office_hours: str
    office_phone: str
    workflows: list[str]
    never: list[str]
    human_request: str
    confirmation_sms: bool = True

    def section(self, name: str) -> dict:
        data = (self.model_extra or {}).get(name)
        if data is None:
            raise KeyError(f"playbook for {self.customer} has no '{name}' section")
        return data


def load_playbook(path: Path) -> Playbook:
    return Playbook.model_validate(yaml.safe_load(path.read_text()))
