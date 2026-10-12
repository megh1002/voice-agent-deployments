"""Web app: see the customers, try calls, watch the staff side, read eval runs.

Run locally:  .venv/bin/uvicorn webapp.app:app --port 8770
Open:         http://localhost:8770

Two modes:
  local (default)  - for the owner: one shared copy of each customer's systems,
                     live calls open, today's API spend shown in the header.
  public           - PUBLIC_MODE=1, for a hosted demo: every visitor gets their
                     own private copy of each customer's systems, spend is
                     hidden, and limits protect the API budget: a daily dollar
                     cap, calls per visitor and per network, turns per call.
"""

import hmac
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import yaml
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import budget, llm
from core.agent import CallSession
from core.notifier import Notifier
from customers import CUSTOMERS
from evals.run import RUNS, load_customer

HERE = Path(__file__).parent
LIVE = RUNS / "live"
# Eval runs stay private in runs/. Copy a run folder into showcase/ to publish it.
SHOWCASE = HERE.parent / "showcase"

PUBLIC = os.environ.get("PUBLIC_MODE") == "1"
MAX_TURNS_PER_CALL = 20
MAX_CALLS_PER_VISITOR_PER_DAY = 8
MAX_CALLS_PER_NETWORK_PER_DAY = 20  # visitor ids are easy to reset; IP addresses less so
MAX_SANDBOXES = 300
SANDBOX_IDLE_SECONDS = 2 * 60 * 60

# The auto-generated API reference holds no secrets, but a public demo doesn't need it.
app = FastAPI(title="Voice agent deployments",
              docs_url=None if PUBLIC else "/docs", redoc_url=None,
              openapi_url=None if PUBLIC else "/openapi.json")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


class Live:
    """One copy of a customer's systems: adapter, a movable clock, a text outbox."""

    def __init__(self, cid: str, owner: str):
        self.cid, self.owner = cid, owner
        self.customer = load_customer(cid)
        self.tz = ZoneInfo(self.customer.PLAYBOOK.timezone)
        self.outbox = LIVE / owner / f"{cid}.outbox.jsonl"
        self.used = time.time()
        self.reset()

    def reset(self):
        self.clock = [datetime.now(self.tz)]
        self.adapter = self.customer.make_adapter(lambda: self.clock[0])
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        self.outbox.write_text("")

    def discard(self):
        self.outbox.unlink(missing_ok=True)


# One read-only copy per customer for page metadata, plus a copy per visitor.
TEMPLATES = {cid: Live(cid, "_template") for cid in CUSTOMERS}
SANDBOXES: "OrderedDict[tuple[str, str], Live]" = OrderedDict()
CALLS: dict[str, tuple[str, str, CallSession]] = {}          # call_id -> (visitor, cid, session)
CALLS_TODAY: dict[tuple[str, str], int] = {}                 # (visitor, day) -> calls started


def visitor_id(x_visitor: str | None) -> str:
    """Each browser sends a random id. Locally everyone shares one copy."""
    if not PUBLIC:
        return "local"
    if not x_visitor or not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", x_visitor):
        raise HTTPException(400, "Missing visitor id. Reload the page.")
    return x_visitor


def sandbox(visitor: str, cid: str) -> Live:
    if cid not in TEMPLATES:
        raise HTTPException(404, f"unknown customer {cid}")
    now = time.time()
    for key in [k for k, lv in SANDBOXES.items() if now - lv.used > SANDBOX_IDLE_SECONDS]:
        SANDBOXES.pop(key).discard()
    key = (visitor, cid)
    if key not in SANDBOXES:
        while len(SANDBOXES) >= MAX_SANDBOXES:
            SANDBOXES.popitem(last=False)[1].discard()
        SANDBOXES[key] = Live(cid, visitor)
    SANDBOXES.move_to_end(key)
    SANDBOXES[key].used = now
    return SANDBOXES[key]


def live_calls_mode() -> str:
    return "open" if llm.has_credentials() else "off"


def require_live_calls():
    if live_calls_mode() == "off":
        raise HTTPException(400, "Live calls are off: no API key is configured.")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")  # set by the host's proxy
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _count_call(key: tuple[str, str], limit: int, message: str):
    if CALLS_TODAY.get(key, 0) >= limit:
        raise HTTPException(429, message)
    CALLS_TODAY[key] = CALLS_TODAY.get(key, 0) + 1


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/status")
def status():
    out = {"api_key": llm.has_credentials(), "model": llm.MODEL, "public": PUBLIC,
           "live_calls": live_calls_mode()}
    if not PUBLIC:  # the owner sees spend; visitors don't
        out.update(spent_today=budget.spent(source="webapp"), daily_budget=budget.daily_budget())
    # Vapi's public key is meant for web pages (the secret never leaves the server).
    if os.environ.get("VAPI_PUBLIC_KEY") and os.environ.get("VAPI_ASSISTANT_ID") and os.environ.get("VAPI_SECRET"):
        out["vapi"] = {"public_key": os.environ["VAPI_PUBLIC_KEY"],
                       "assistant_id": os.environ["VAPI_ASSISTANT_ID"], "customer": PHONE_CUSTOMER}
    return out


def _friendly_api_error(e: anthropic.APIError) -> HTTPException:
    """Turn API failures into messages a person can act on."""
    text = getattr(e, "message", str(e)).lower()
    if PUBLIC:
        return HTTPException(503, "The live demo is unavailable right now. You can still browse recorded calls under Eval runs.")
    if isinstance(e, anthropic.AuthenticationError):
        return HTTPException(401, "The API key was rejected. Check the key in your key file, or create a new one at platform.claude.com.")
    if "credit balance" in text or "billing" in text:
        return HTTPException(402, "Your API credits have run out. Add credits at platform.claude.com under Billing, then try again.")
    if isinstance(e, anthropic.RateLimitError):
        return HTTPException(429, "Too many requests right now. Wait a few seconds and try again.")
    if isinstance(e, anthropic.APIConnectionError):
        return HTTPException(503, "Can't reach the Claude API. Check your internet connection.")
    return HTTPException(502, f"The Claude API returned an error: {getattr(e, 'message', e)}")


@app.get("/api/customers")
def customers():
    out = []
    for cid, lv in TEMPLATES.items():
        c, pb = lv.customer, lv.customer.PLAYBOOK
        scenarios = yaml.safe_load(c.SCENARIOS.read_text())["scenarios"]
        out.append({"id": cid, "name": pb.customer, "industry": c.INDUSTRY, "summary": c.SUMMARY,
                    "workflows": pb.workflows, "scenarios": len(scenarios),
                    "latest_run": _latest_run(cid)})
    return out


@app.get("/api/customers/{cid}")
def customer(cid: str):
    if cid not in TEMPLATES:
        raise HTTPException(404, f"unknown customer {cid}")
    lv = TEMPLATES[cid]
    c, pb = lv.customer, lv.customer.PLAYBOOK
    session = CallSession(pb, lv.adapter, Notifier("outbox", lv.outbox), "", lv.clock[0])
    return {
        "id": cid, "name": pb.customer, "industry": c.INDUSTRY, "summary": c.SUMMARY,
        "workflows": [{"name": w.name, "tools": [t["name"] for t in w.tools()],
                       "doc": (sys.modules[type(w).__module__].__doc__ or "").strip()}
                      for w in session.workflows],
        "playbook": (c.HERE / "playbook.yaml").read_text(),
        "discovery": c.DISCOVERY.read_text(),
        "scenarios": yaml.safe_load(c.SCENARIOS.read_text())["scenarios"],
        "sample_callers": [{"phone": p, "label": l} for p, l in c.SAMPLE_CALLERS],
        "demo_calls": getattr(c, "DEMO_CALLS", []),
        "disclosure": pb.disclosure,
        "agent_name": pb.agent_name,
    }


class NewCall(BaseModel):
    caller_phone: str
    call_time: str | None = None  # "YYYY-MM-DDTHH:MM", local time; default now


@app.post("/api/customers/{cid}/calls")
def start_call(cid: str, body: NewCall, request: Request, x_visitor: str | None = Header(None)):
    visitor = visitor_id(x_visitor)
    require_live_calls()
    if PUBLIC:
        today = date.today().isoformat()
        limit_msg = "That's the demo's daily call limit. Come back tomorrow, or browse recorded calls under Eval runs."
        _count_call(("visitor:" + visitor, today), MAX_CALLS_PER_VISITOR_PER_DAY, limit_msg)
        _count_call(("ip:" + _client_ip(request), today), MAX_CALLS_PER_NETWORK_PER_DAY, limit_msg)
    lv = sandbox(visitor, cid)
    now = (datetime.fromisoformat(body.call_time).replace(tzinfo=lv.tz)
           if body.call_time else datetime.now(lv.tz))
    lv.clock[0] = now
    session = CallSession(lv.customer.PLAYBOOK, lv.adapter, Notifier("outbox", lv.outbox),
                          body.caller_phone[:20], now)
    greeting = session.start()
    call_id = uuid.uuid4().hex
    CALLS[call_id] = (visitor, cid, session)
    return {"call_id": call_id, "greeting": greeting}


class Say(BaseModel):
    text: str


def _own_call(call_id: str, visitor: str) -> tuple[str, CallSession]:
    found = CALLS.get(call_id)
    if not found or found[0] != visitor:   # a visitor can only see their own calls
        raise HTTPException(404, "call not found")
    return found[1], found[2]


@app.post("/api/calls/{call_id}/say")
def say(call_id: str, body: Say, x_visitor: str | None = Header(None)):
    visitor = visitor_id(x_visitor)
    cid, session = _own_call(call_id, visitor)
    require_live_calls()
    if session.ended:
        raise HTTPException(400, "The agent already ended this call.")
    turns = sum(1 for t in session.record["transcript"] if t["speaker"] == "caller")
    if turns >= MAX_TURNS_PER_CALL:
        raise HTTPException(429, f"This call reached the {MAX_TURNS_PER_CALL}-turn demo limit. Start a new call.")
    if budget.over_budget("webapp"):
        raise HTTPException(429, "Today's demo budget is used up. Browse recorded calls under Eval runs, or try again tomorrow."
                            if PUBLIC else
                            f"Today's demo budget of ${budget.daily_budget():.2f} is used up. "
                            "Raise DAILY_BUDGET_USD in your key file and restart, or try again tomorrow.")
    sandbox(visitor, cid).clock[0] = session.now
    llm.start_tally("webapp")
    try:
        reply = session.reply(body.text[:1000])
    except anthropic.APIError as e:
        raise _friendly_api_error(e)
    session.record["cost_usd"] = round(session.record.get("cost_usd", 0) + (llm.tally()["cost_usd"] or 0), 4)
    return {"reply": reply, **_call_view(session)}


@app.get("/api/calls/{call_id}")
def get_call(call_id: str, x_visitor: str | None = Header(None)):
    _, session = _own_call(call_id, visitor_id(x_visitor))
    return _call_view(session)


def _call_view(s: CallSession) -> dict:
    r = s.record
    view = {"ended": s.ended, "transcript": r["transcript"], "events": r["events"],
            "tool_calls": r["tool_calls"], "guardrail_flags": r["guardrail_flags"]}
    if not PUBLIC:
        view.update(cost_usd=r.get("cost_usd", 0), spent_today=budget.spent(source="webapp"),
                    daily_budget=budget.daily_budget())
    return view


@app.get("/api/customers/{cid}/staff")
def staff(cid: str, x_visitor: str | None = Header(None)):
    lv = sandbox(visitor_id(x_visitor), cid)
    texts = [json.loads(l) for l in lv.outbox.read_text().splitlines() if l.strip()]
    return {"tables": lv.customer.staff_view(lv.adapter), "texts": list(reversed(texts))}


@app.post("/api/customers/{cid}/reset")
def reset(cid: str, x_visitor: str | None = Header(None)):
    sandbox(visitor_id(x_visitor), cid).reset()
    return {"ok": True}


# ---- write-up documents ----------------------------------------------------------

DOCS = {"findings": "FINDINGS.md", "decisions": "DECISIONS.md", "plan": "PLAN.md"}


@app.get("/api/docs/{name}")
def doc(name: str):
    if name not in DOCS:
        raise HTTPException(404, "unknown document")
    return {"name": name, "markdown": (HERE.parent / DOCS[name]).read_text()}


# ---- eval runs ----------------------------------------------------------------

def _run_dirs():
    found = {}
    for root in (SHOWCASE, RUNS):   # a run in both places is listed once
        if root.exists():
            for d in root.iterdir():
                if d.is_dir() and d.name != "live":
                    found.setdefault(d.name, d)
    return sorted(found.values(), key=lambda d: d.name, reverse=True)


def _run_summary(d: Path) -> dict:
    # Folder names look like "<customer>-<YYYYmmdd>-<HHMMSS>".
    customer, day, clock = d.name.rsplit("-", 2)
    records = [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))]
    return {"id": d.name, "customer": customer,
            "when": datetime.strptime(f"{day}{clock}", "%Y%m%d%H%M%S").isoformat(),
            "calls": len(records), "passed": sum(r.get("passed", False) for r in records)}


def _latest_run(cid: str):
    for d in _run_dirs():
        if d.name.rsplit("-", 2)[0] == cid:
            return _run_summary(d)
    return None


@app.get("/api/runs")
def runs():
    return [_run_summary(d) for d in _run_dirs()]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    d = next((x for x in _run_dirs() if x.name == run_id), None)
    if not re.fullmatch(r"[a-z_]+-\d{8}-\d{6}", run_id) or d is None:
        raise HTTPException(404, "run not found")
    report = (d / "report.md").read_text() if (d / "report.md").exists() else ""
    return {**_run_summary(d), "report": report,
            "records": [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))]}


# ---- real phone calls (Vapi) ------------------------------------------------------
# Vapi runs the phone line, speech-to-text, and the voice. It sends each caller
# turn here in the OpenAI chat format; this agent stays the brain. Vapi passes the
# secret we gave it as a bearer token. Leave VAPI_SECRET unset to turn phone off.

PHONE_CUSTOMER = os.environ.get("PHONE_CUSTOMER", "ravenswood_clinic")
PHONE_CALLS: dict[str, CallSession] = {}


def _latest_caller_text(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):  # content parts
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return (c or "").strip()
        if m.get("role") == "assistant":
            return ""  # nothing new from the caller since our last reply
    return ""


def _phone_authorized(secret: str, authorization: str | None, x_api_key: str | None) -> bool:
    """Accept the secret however the platform's credential type sends it:
    'Authorization: Bearer <s>', 'Authorization: <s>', or 'X-Api-Key: <s>'."""
    offered = [x_api_key or ""]
    token = (authorization or "").strip()
    while token.lower().startswith("bearer "):
        token = token[7:].strip()
    offered.append(token)
    return any(o and hmac.compare_digest(o, secret) for o in offered)


# Recent voice-platform requests, for diagnosing setup problems from outside.
# Only yes/no facts and timings are kept: never call content, never credentials.
PHONE_REQUESTS: "deque[dict]" = deque(maxlen=20)


def _note_request(**facts):
    PHONE_REQUESTS.append({"at": datetime.now().isoformat(timespec="seconds"), **facts})


@app.get("/api/phone/health")
def phone_health():
    return {"configured": bool(os.environ.get("VAPI_SECRET")), "voice_model": VOICE_MODEL or llm.MODEL,
            "recent_requests": list(PHONE_REQUESTS)}


# Some setups append /chat/completions to a URL that already ends with it; accept both.
@app.post("/vapi/chat/completions/chat/completions", include_in_schema=False)
@app.post("/vapi/chat/completions")
def vapi_turn(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
              x_api_key: str | None = Header(None)):
    secret = os.environ.get("VAPI_SECRET")
    if not secret:
        _note_request(path=request.url.path, result="not configured")
        raise HTTPException(503, "Phone calls are not configured.")
    if not _phone_authorized(secret, authorization, x_api_key):
        _note_request(path=request.url.path, result="rejected: secret did not match",
                      auth_header_present=bool(authorization or x_api_key))
        raise HTTPException(401, "Unauthorized")

    call = body.get("call") or (body.get("metadata") or {}).get("call") or {}
    call_id = re.sub(r"[^A-Za-z0-9_-]", "", str(call.get("id") or ""))[:40]
    if not call_id:
        # Without a call id every call would share one session. Log only field names, never content.
        print(f"phone request without a call id; top-level fields={sorted(body)}", flush=True)
        call_id = "unknown"
    caller = str((call.get("customer") or {}).get("number") or "unknown")[:20]
    session = PHONE_CALLS.get(call_id)
    if session is None:
        lv = sandbox(f"phone-{call_id}", PHONE_CUSTOMER)
        session = CallSession(lv.customer.PLAYBOOK, lv.adapter, Notifier("outbox", lv.outbox),
                              caller, datetime.now(lv.tz))
        session.start()  # the same disclosure Vapi plays as its first message
        PHONE_CALLS[call_id] = session

    text = _latest_caller_text(body.get("messages"))
    turns = sum(1 for x in session.record["transcript"] if x["speaker"] == "caller")
    _note_request(path=request.url.path, result="accepted", has_call_id=call_id != "unknown",
                  call_id_tail=call_id[-6:], has_caller_words=bool(text), stream=body.get("stream", True),
                  fields=sorted(body))
    if not text:
        canned = ""
    elif session.ended:
        canned = "Thanks for calling. Goodbye."
    elif turns >= MAX_TURNS_PER_CALL or budget.over_budget("webapp") or budget.over_budget("phone"):
        canned = ("I'm sorry, this demo line has reached its limit. If this is an emergency, "
                  "please hang up and call 911. Goodbye.")
    else:
        canned = None

    if body.get("stream") is False:
        reply = canned if canned is not None else "".join(_run_turn(session, call_id, text, turns))
        return {"id": f"chatcmpl-{call_id[:24]}", "object": "chat.completion", "created": int(time.time()),
                "model": llm.MODEL, "choices": [{"index": 0, "finish_reason": "stop",
                                                 "message": {"role": "assistant", "content": reply}}]}
    pieces = [canned] if canned is not None else _run_turn(session, call_id, text, turns)
    return StreamingResponse(_sse(call_id, pieces), media_type="text/event-stream")


# Phone timing. Model replies usually take 2-6 s, but spikes of 20-40 s happen, and
# Vapi hangs up if nothing streams within its timeout. So speech is streamed the moment
# it exists, and if nothing is ready yet the agent says "One moment", as a person would.
VOICE_MODEL = os.environ.get("VOICE_MODEL") or None
FILLER_AFTER_S = 4.0
FILLER = "One moment."


def _run_turn(session: CallSession, call_id: str, text: str, turns: int):
    """Run one agent turn in a worker thread, yielding speech as it becomes available."""
    q: queue.Queue = queue.Queue()
    timing = {"started": time.time(), "first": None}

    def work():
        llm.use_model(VOICE_MODEL)
        llm.start_tally("phone")
        session.on_text = q.put
        try:
            session.reply(text[:1000])
        except Exception as e:  # never leave the caller in silence
            _note_request(path="(turn)", result=f"turn failed: {type(e).__name__}", call_id_tail=call_id[-6:])
            q.put("I'm sorry, I'm having trouble right now. If this is an emergency, please call 911.")
        finally:
            session.on_text = None
            took = round(time.time() - timing["started"], 2)
            first = round((timing["first"] or time.time()) - timing["started"], 2)
            session.record.setdefault("latencies_s", []).append(took)
            session.record.setdefault("first_words_s", []).append(first)
            session.record["cost_usd"] = round(session.record.get("cost_usd", 0) + (llm.tally()["cost_usd"] or 0), 4)
            # Content stays out of the logs; timing and cost are what we measure.
            print(f"phone call={call_id} turn={turns + 1} model={llm.current_model()} first_words_s={first} "
                  f"reply_seconds={took} events={[e['type'] for e in session.record['events']]} "
                  f"cost=${session.record['cost_usd']}", flush=True)
            q.put(None)

    threading.Thread(target=work, daemon=True).start()
    said_something = False
    while True:
        try:
            piece = q.get(timeout=FILLER_AFTER_S if not said_something else 120)
        except queue.Empty:
            if said_something:
                break
            piece = FILLER
            session.record.setdefault("fillers", 0)
            session.record["fillers"] += 1
        if piece is None:
            break
        if timing["first"] is None:
            timing["first"] = time.time()
        said_something = True
        yield piece + " "


def _sse(call_id: str, pieces):
    base = {"id": f"chatcmpl-{call_id[:24]}", "object": "chat.completion.chunk",
            "created": int(time.time()), "model": llm.MODEL}
    first = True
    for piece in pieces:
        if not piece:
            continue
        delta = {"role": "assistant", "content": piece} if first else {"content": piece}
        first = False
        yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}) + "\n\n"
    yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
    yield "data: [DONE]\n\n"


@app.get("/api/phone/calls")
def phone_calls(x_admin: str | None = Header(None)):
    """Recent phone calls with timings, for the owner (same secret as Vapi)."""
    secret = os.environ.get("VAPI_SECRET")
    if not secret or not hmac.compare_digest(x_admin or "", secret):
        raise HTTPException(401, "Unauthorized")
    return [{"call": cid, "caller_turns": sum(1 for t in s.record["transcript"] if t["speaker"] == "caller"),
             "latencies_s": s.record.get("latencies_s", []), "events": s.record["events"],
             "transcript": s.record["transcript"], "cost_usd": s.record.get("cost_usd", 0)}
            for cid, s in list(PHONE_CALLS.items())[-10:]]


@app.get("/api/voice/calls/{call_id}")
def voice_call(call_id: str):
    """Live events and staff view for one Vapi call, for the page that started it.
    Call ids are random and unguessable; all data is synthetic."""
    call_id = re.sub(r"[^A-Za-z0-9_-]", "", call_id)[:40]
    session = PHONE_CALLS.get(call_id)
    if session is None:
        return {"found": False}
    lv = sandbox(f"phone-{call_id}", PHONE_CUSTOMER)
    texts = [json.loads(l) for l in lv.outbox.read_text().splitlines() if l.strip()]
    view = _call_view(session)
    view.pop("cost_usd", None); view.pop("spent_today", None); view.pop("daily_budget", None)
    return {"found": True, **view,
            "staff": {"tables": lv.customer.staff_view(lv.adapter), "texts": list(reversed(texts))}}
