"""Run a customer's eval scenarios and write a report.

  .venv/bin/python -m evals.run ravenswood_clinic          # all scenarios
  .venv/bin/python -m evals.run maple_court --only gas_inside,lockout_roommate
  .venv/bin/python -m evals.run ravenswood_clinic --repeat 3   # catch flaky behavior

Results go to runs/<customer>-<timestamp>/: one JSON per call plus report.md.
The web app reads the same folders.
"""

import argparse
import importlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from core import llm
from core.adapter import Caller
from core.agent import CallSession
from core.notifier import Notifier

from .judge import code_checks, judge
from .simulator import SimulatedCaller

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
MAX_TURNS = 14
SAFETY_GROUPS = {"emergency", "red_flag"}


def load_customer(name: str):
    return importlib.import_module(f"customers.{name}.customer")


def apply_setup(customer, adapter, clock, sc, now, out_dir):
    """Things that happened before this call (e.g. the boiler was already reported)."""
    for prior in sc.get("setup", []):
        earlier = clock[0] = now - timedelta(minutes=prior["minutes_before"])
        session = CallSession(customer.PLAYBOOK, adapter,
                              Notifier("outbox", out_dir / "setup_outbox.jsonl"), "", earlier)
        triage = next(w for w in session.workflows if w.name == "triage")
        triage.report(session, category=prior["category"], summary="(earlier call)",
                      unit=prior["unit"], caller=Caller("Earlier caller", prior["unit"], ""))


def run_scenario(customer, sc: dict, defaults: dict, out_dir: Path) -> dict:
    llm.start_tally("eval")
    pb = customer.PLAYBOOK
    now = datetime.fromisoformat(sc.get("call_time", defaults["call_time"])).replace(
        tzinfo=ZoneInfo(pb.timezone))
    clock = [now]
    adapter = customer.make_adapter(lambda: clock[0])
    apply_setup(customer, adapter, clock, sc, now, out_dir)
    clock[0] = now

    session = CallSession(pb, adapter, Notifier("outbox", out_dir / f"{sc['id']}.outbox.jsonl"),
                          caller_phone=sc["caller_phone"], now=now)
    caller = SimulatedCaller(sc["persona"])
    agent_said = session.start()
    for _ in range(MAX_TURNS):
        said, hung_up = caller.respond(agent_said)
        if said:
            agent_said = session.reply(said)
        if hung_up or session.ended:
            break

    record = session.record
    expect = sc["expect"]
    record.update(scenario=sc["id"], group=sc["group"], expect=expect, persona=sc["persona"])
    record["code_checks"] = code_checks(record, expect, pb.disclosure)
    record["judge"] = judge(record, expect, pb.never)
    record["passed"] = (all(c["passed"] for c in record["code_checks"])
                        and all(c["passed"] for c in record["judge"]))
    record["usage"] = llm.tally()
    (out_dir / f"{sc['id']}.json").write_text(json.dumps(record, indent=2, default=str))
    return record


def summarize(records: list[dict]) -> str:
    def pct(n, d):
        return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"

    safety = [r for r in records if r["group"] in SAFETY_GROUPS]
    by_check = defaultdict(lambda: [0, 0])
    for r in records:
        for c in r["code_checks"]:
            by_check[c["check"]][0] += c["passed"]
            by_check[c["check"]][1] += 1

    lines = [
        f"# Eval report: {records[0]['customer']}",
        "",
        f"- **Calls fully passed:** {pct(sum(r['passed'] for r in records), len(records))}",
        f"- **Safety-critical calls fully passed:** {pct(sum(r['passed'] for r in safety), len(safety))} (target: all)",
        f"- **Guardrail flags:** {sum(len(r['guardrail_flags']) for r in records)} (target: 0)",
        f"- **Cost of this run:** ${sum((r.get('usage') or {}).get('cost_usd') or 0 for r in records):.2f} "
        f"({sum((r.get('usage') or {}).get('requests', 0) for r in records)} API requests)",
        "",
        "| Code check | Passed |",
        "|---|---|",
        *[f"| {name} | {pct(p, t)} |" for name, (p, t) in by_check.items()],
        "",
        "| Scenario | Group | Result | What failed |",
        "|---|---|---|---|",
    ]
    for r in records:
        failed = [f"{c['check']}: {c['detail']}" for c in r["code_checks"] if not c["passed"]]
        failed += [f"judge: {c['criterion']}" for c in r["judge"] if not c["passed"]]
        lines.append(f"| {r['scenario']} | {r['group']} | {'✅' if r['passed'] else '❌'} | "
                     f"{'<br>'.join(failed)} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("customer")
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    customer = load_customer(args.customer)
    spec = yaml.safe_load(customer.SCENARIOS.read_text())
    scenarios = spec["scenarios"]
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]
    scenarios = [dict(s, id=s["id"] + (f"__{i + 1}" if args.repeat > 1 else ""))
                 for s in scenarios for i in range(args.repeat)]

    out_dir = RUNS / f"{args.customer}-{datetime.now():%Y%m%d-%H%M%S}"
    out_dir.mkdir(parents=True)
    print(f"Running {len(scenarios)} calls -> {out_dir.relative_to(ROOT)}")

    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(run_scenario, customer, s, spec["defaults"], out_dir) for s in scenarios]
        records = []
        for f in futures:
            r = f.result()
            records.append(r)
            print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['scenario']}")

    report = summarize(records)
    (out_dir / "report.md").write_text(report)
    print("\n" + report)


if __name__ == "__main__":
    main()
