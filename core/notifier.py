"""Sending pages (text messages) to the on-call technician.

Three modes, set by the NOTIFY_MODE environment variable:
  outbox  - write messages to runs/outbox.jsonl, send nothing (evals, default)
  shadow  - same as outbox, but marked as shadow mode (pilot phase 1)
  twilio  - really send an SMS (pilot phase 2, go-live)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

OUTBOX = Path(__file__).resolve().parent.parent / "runs" / "outbox.jsonl"


class Notifier:
    def __init__(self, mode: str | None = None, outbox: Path | None = None):
        self.mode = mode or os.environ.get("NOTIFY_MODE", "outbox")
        self.outbox = outbox

    def send_sms(self, to: str, body: str) -> bool:
        """Returns True only if the message was accepted for delivery."""
        if self.mode in ("outbox", "shadow"):
            path = self.outbox or OUTBOX
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(json.dumps({
                    "at": datetime.now(timezone.utc).isoformat(),
                    "mode": self.mode, "to": to, "body": body,
                }) + "\n")
            return True
        if self.mode == "twilio":
            raise NotImplementedError("Twilio sending is added in the pilot phase")
        raise ValueError(f"Unknown NOTIFY_MODE {self.mode!r}")
