"""Text channel — Retell Chat API.

The control arm. Same prompt, same tools, same model; no audio. Anything that
fails here as well as in voice is a reasoning/prompt problem. Anything that
fails only in voice is a candidate structural-to-voice finding.

The comparison is cleaner than expected: `create-chat-agent` accepts the same
`llm_id` as `create-agent`, so both channels are backed by the *same Retell LLM
object* — one prompt, one tool set, one model, one temperature. The chat agent
is a second transport onto identical config, not a re-implementation. What still
differs is everything downstream of the LLM: no STT, no TTS, no turn-taking, no
clock.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from ..retell_client import RetellClient
from ..schema import CallerTurn, Event, Scenario
from .base import captured_slots_from_events, dynamic_variables, flatten_transcript


def _speakable(turns: list[CallerTurn]) -> list[CallerTurn]:
    """Silence has no text analogue; drop those turns rather than fake them."""
    return [t for t in turns if t.say]


def run_text_scenario(
    client: RetellClient, agent_id: str, scenario: Scenario
) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    chat = client.create_chat(
        agent_id, retell_llm_dynamic_variables=dynamic_variables(scenario)
    )
    chat_id = chat["chat_id"]

    turn_timings: list[dict[str, Any]] = []
    try:
        for turn in _speakable(scenario.turns):
            t0 = time.perf_counter()
            client.chat_completion(chat_id, turn.say or "")
            turn_timings.append({
                "said": turn.say,
                "api_round_trip_ms": int((time.perf_counter() - t0) * 1000),
            })
        # bounded follow-ups: only if the agent hasn't committed yet
        followups = 0
        for _ in range(scenario.max_followups):
            snap = client.get_chat(chat_id)
            entries = snap.get("message_with_tool_calls") or snap.get("messages") or []
            if any(e.get("role") == "tool_call_invocation"
                   and e.get("name") == "book_appointment" for e in entries):
                break
            if scenario.must_not_book:
                break
            followups += 1
            client.chat_completion(chat_id, scenario.followup_reply)

        final = client.get_chat(chat_id)
    finally:
        try:
            client.end_chat(chat_id)
        except Exception:  # noqa: BLE001,S110 - best-effort cleanup; a chat that
            pass           # cannot be closed must not lose the run's results

    entries = final.get("message_with_tool_calls") or final.get("messages") or []
    events: list[Event] = flatten_transcript(entries)

    return {
        "channel": "text",
        "call_id": chat_id,
        "started_at": started,
        "ended_at": datetime.now(UTC).isoformat(),
        "events": events,
        "captured_slots": captured_slots_from_events(events),
        "raw": final,
        "turn_timings": turn_timings,
        "followups_used": followups,
    }
