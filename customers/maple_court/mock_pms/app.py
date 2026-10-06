"""Mock property management system for Maple Court (the client's software).

Stands in for a real product like Buildium. Field names and endpoint shapes are
modeled on Buildium's public API (developer.buildium.com), simplified. It is NOT
our code in the story: it's the client's system we integrate with, so the agent
talks to it only over HTTP, the same way it would talk to the real thing.

Run:  .venv/bin/uvicorn customers.maple_court.mock_pms.app:app --port 8001
Docs: http://localhost:8001/docs

Evals call create_app() for a fresh copy per test, with a frozen clock so a
scenario can pretend it's 2am in January.
"""

import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .seed import BUILDING, STAFF, build

API_KEY = os.environ.get("PMS_API_KEY", "dev-key")


class NewRequest(BaseModel):
    Title: str
    Description: str
    Category: str
    Priority: Literal["Low", "Normal", "High"]
    UnitId: int | None = None  # None = common area / building-wide
    RequestedByTenantId: int | None = None
    AssignedToUserId: int | None = None


def require_key(x_api_key: str | None = Header(None)):
    # Real Buildium uses a client ID + secret pair. One key keeps the mock simple
    # while still forcing the agent to authenticate.
    if x_api_key != API_KEY:
        raise HTTPException(401, "Invalid API key")


def create_app(clock: Callable[[], datetime] | None = None) -> FastAPI:
    clock = clock or (lambda: datetime.now(timezone.utc))
    units, tenants = build()
    requests: list[dict] = []  # maintenance requests, in memory

    app = FastAPI(title="Maple Court PMS (mock, modeled on Buildium)",
                  dependencies=[Depends(require_key)])

    def find_unit(unit_id: int) -> dict:
        for u in units:
            if u["Id"] == unit_id:
                return u
        raise HTTPException(404, f"Unit {unit_id} not found")

    @app.get("/v1/rentals/1")
    def get_building():
        return BUILDING

    @app.get("/v1/rentals/units")
    def list_units():
        return units

    @app.get("/v1/rentals/tenants")
    def list_tenants(phone: str | None = None):
        # Filtering by phone is a convenience the real API may not offer; without
        # it the agent would have to page through all tenants and match locally.
        if phone is None:
            return tenants
        return [t for t in tenants if any(p["Number"] == phone for p in t["PhoneNumbers"])]

    @app.get("/v1/users")
    def list_staff():
        return STAFF

    @app.get("/v1/tasks/maintenancerequests")
    def list_requests(status: str | None = None):
        if status is None:
            return requests
        return [r for r in requests if r["TaskStatus"] == status]

    @app.post("/v1/tasks/maintenancerequests", status_code=201)
    def create_request(req: NewRequest):
        if req.UnitId is not None:
            find_unit(req.UnitId)
        now = clock().isoformat()
        record = {"Id": len(requests) + 1, **req.model_dump(), "TaskStatus": "New",
                  "CreatedDateTime": now, "UpdatedDateTime": now}
        requests.append(record)
        return record

    @app.get("/v1/tasks/maintenancerequests/{request_id}")
    def get_request(request_id: int):
        for r in requests:
            if r["Id"] == request_id:
                return r
        raise HTTPException(404, f"Maintenance request {request_id} not found")

    return app


app = create_app()
