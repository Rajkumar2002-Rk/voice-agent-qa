"""The clinic's booking backend — and the harness's ground-truth oracle.

Retell calls custom tools as webhooks, so this has to be a real HTTP service on
a public URL. That's a setup cost, and it buys two things that make the whole
experiment work:

1. `check_availability` responses are *recorded*, so "did the agent invent an
   appointment slot?" is a set-difference, not an opinion.
2. `book_appointment` arguments *are* the captured slots. The agent hands us
   structured data about what it believes it heard; we never parse its prose.

Availability is deterministic: seeded from the requested date, so the same date
always returns the same slots, on any machine, forever.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel

LOG_DIR = Path(os.getenv("CLINIC_LOG_DIR", "runs/_tool_log"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()

app = FastAPI(title="Clinic booking backend (test double)")

# The clinic's whole world. Small on purpose — the agent is the subject of the
# experiment, not this.
OPEN_SLOTS = ["09:00", "09:30", "10:00", "11:00", "13:30", "14:00", "15:00", "16:00"]
CLOSED_WEEKDAYS = {5, 6}   # Sat, Sun


def _deterministic_open_slots(day: date) -> list[str]:
    """Same date -> same availability, always. No clock, no randomness."""
    if day.weekday() in CLOSED_WEEKDAYS:
        return []
    seed = int(hashlib.sha256(day.isoformat().encode()).hexdigest()[:8], 16)
    # keep a stable, date-dependent subset so different days look different
    return [s for i, s in enumerate(OPEN_SLOTS) if (seed >> i) & 1] or [OPEN_SLOTS[0]]


def _log(kind: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
    """Append-only tool log. The harness reads this as ground truth."""
    call_id = (
        (payload.get("call") or {}).get("call_id")
        or payload.get("call_id")
        or "unknown"
    )
    rec = {
        "ts": datetime.now(UTC).isoformat(),
        "tool": kind,
        "call_id": call_id,
        "args": payload.get("args", payload),
        "response": response,
    }
    with _lock:
        with (LOG_DIR / f"{call_id}.jsonl").open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        with (LOG_DIR / "_all.jsonl").open("a") as fh:
            fh.write(json.dumps(rec) + "\n")


def _args(payload: dict[str, Any]) -> dict[str, Any]:
    """Retell nests tool arguments under `args`; be tolerant of both shapes."""
    a = payload.get("args")
    return a if isinstance(a, dict) else payload


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/check_availability")
async def check_availability(request: Request) -> dict[str, Any]:
    payload = await request.json()
    args = _args(payload)
    raw = str(args.get("date", "")).strip()

    try:
        day = date.fromisoformat(raw)
    except ValueError:
        resp = {
            "ok": False,
            "error": "date must be an ISO date (YYYY-MM-DD)",
            "received": raw,
            "slots": [],
        }
        _log("check_availability", payload, resp)
        return resp

    slots = _deterministic_open_slots(day)
    resp = {
        "ok": True,
        "date": day.isoformat(),
        "slots": [{"time": s} for s in slots],
        "message": (
            f"{len(slots)} opening(s) on {day.isoformat()}"
            if slots else f"The clinic is closed on {day.strftime('%A')}."
        ),
    }
    _log("check_availability", payload, resp)
    return resp


class Booking(BaseModel):
    patient_name: str | None = None
    date: str | None = None
    time: str | None = None
    reason: str | None = None
    phone: str | None = None


@app.post("/book_appointment")
async def book_appointment(request: Request) -> dict[str, Any]:
    payload = await request.json()
    args = _args(payload)
    booking = Booking(**{k: args.get(k) for k in Booking.model_fields})

    # The server deliberately does NOT validate the booking against real
    # availability. If it rejected bad bookings, the agent could lean on it to
    # catch its own mistakes and we'd be measuring the server, not the agent.
    # Accept everything; let the scorer judge.
    resp = {
        "ok": True,
        "confirmation_number": "CLN-"
        + hashlib.sha256(
            f"{booking.patient_name}{booking.date}{booking.time}".encode()
        ).hexdigest()[:6].upper(),
        "booked": booking.model_dump(),
    }
    _log("book_appointment", payload, resp)
    return resp


@app.post("/_reset")
async def reset() -> dict[str, str]:
    with _lock:
        for f in LOG_DIR.glob("*.jsonl"):
            f.unlink()
    return {"status": "cleared"}
