from .base import Workflow
from .handoff import Handoff
from .identity import Identity
from .red_flags import RedFlags
from .scheduling import Scheduling
from .triage import Triage

REGISTRY: dict[str, type[Workflow]] = {
    w.name: w for w in (RedFlags, Triage, Identity, Scheduling, Handoff)
}


def build_workflows(playbook) -> list[Workflow]:
    return [REGISTRY[name](playbook) for name in playbook.workflows]
