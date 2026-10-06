"""Spend tracking and a daily budget, so a demo can't quietly drain API credits.

Every API call appends its cost to runs/spend.jsonl. The web app refuses new
turns once today's web-app spend reaches DAILY_BUDGET_USD (default $1.00, set
it in your environment or the key file). Eval runs are logged but not capped:
you start those on purpose and see the cost in the report.
"""

import json
import os
import threading
from datetime import date, datetime
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "runs" / "spend.jsonl"
_lock = threading.Lock()


def daily_budget() -> float:
    return float(os.environ.get("DAILY_BUDGET_USD", "1.00"))


def record(cost_usd: float, source: str) -> None:
    with _lock:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as f:
            f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                "source": source, "cost_usd": round(cost_usd, 6)}) + "\n")


def spent(day: date | None = None, source: str | None = None) -> float:
    day = (day or date.today()).isoformat()
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    for line in LEDGER.read_text().splitlines():
        row = json.loads(line)
        if row["at"].startswith(day) and (source is None or row["source"] == source):
            total += row["cost_usd"]
    return round(total, 4)


def over_budget(source: str = "webapp") -> bool:
    return spent(source=source) >= daily_budget()
