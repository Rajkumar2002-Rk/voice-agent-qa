"""Shared conversion from Retell payloads to the scorer's Event list.

Both channels go through here, so the scorer stays ignorant of Retell and the
two arms of the channel comparison are parsed by identical code — which matters,
because a parsing difference between channels would look exactly like a finding.
"""

from __future__ import annotations

import json
from typing import Any

from ..schema import Event

BOOK_TOOL = "book_appointment"


def _json_or_empty(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {"value": v}
    except json.JSONDecodeError:
        return {"raw": raw}


def flatten_transcript(entries: list[dict[str, Any]]) -> list[Event]:
    """Retell `transcript_with_tool_calls` (or chat `messages`) -> Events.

    Tool *results* carry only a tool_call_id, not a name, so we thread names
    through from the matching invocation.
    """
    events: list[Event] = []
    names_by_id: dict[str, str] = {}

    for e in entries or []:
        role = e.get("role")

        if role in ("agent", "user"):
            words = e.get("words") or []
            start = end = None
            if words:
                try:
                    start = int(float(words[0].get("start", 0)) * 1000)
                    end = int(float(words[-1].get("end", 0)) * 1000)
                except (TypeError, ValueError):
                    start = end = None
            if start is None and e.get("created_timestamp") is not None:
                # chat messages have no word timings, only a wall-clock stamp
                start = end = int(e["created_timestamp"])
            events.append(Event(role=role, text=e.get("content") or "",
                                start_ms=start, end_ms=end))

        elif role == "tool_call_invocation":
            name = e.get("name") or ""
            tcid = e.get("tool_call_id") or ""
            if tcid:
                names_by_id[tcid] = name
            events.append(Event(role="tool_call", name=name,
                                args=_json_or_empty(e.get("arguments"))))

        elif role == "tool_call_result":
            tcid = e.get("tool_call_id") or ""
            events.append(Event(role="tool_result",
                                name=names_by_id.get(tcid),
                                result=_json_or_empty(e.get("content"))))

        # node_transition / state_transition / dtmf / sms are not scored
    return events


def captured_slots_from_events(events: list[Event]) -> dict[str, Any]:
    """The agent's own structured commitment is the captured slot set.

    Last booking wins: if the agent booked twice, the final call is what the
    caller actually ends up with.
    """
    books = [e for e in events if e.role == "tool_call" and e.name == BOOK_TOOL]
    if not books:
        return {}
    return {k: v for k, v in books[-1].args.items() if v not in (None, "")}
