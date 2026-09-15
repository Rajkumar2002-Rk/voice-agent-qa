"""Typed definitions for scenarios, runs and verdicts.

A Scenario is a *contract written before the run*: what the caller will say,
and what the agent must end up with.  Nothing here is decided after seeing the
agent's output.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Persona = Literal[
    "barge_in",          # interrupts the agent mid-sentence
    "background_noise",  # noise / a second voice talking over
    "mind_change",       # changes their mind halfway through
    "ambiguous_date",    # "next Tuesday", "the 3rd"
    "long_silence",      # goes quiet for a long stretch
    "out_of_scope",      # asks for something the agent has no tool for
    "self_correction",   # says a number/date wrong, then corrects it
    "compound_utterance",# two pieces of info in one breath
    "happy_path",        # control
]

Channel = Literal["voice", "text"]
Arm = Literal["naive", "hardened"]


class Verdict(str, Enum):
    PASS = "PASS"
    WRONG = "WRONG"
    MISSING = "MISSING"
    UNPARSEABLE = "UNPARSEABLE"
    AMBIGUOUS_ALTERNATE = "AMBIGUOUS_ALTERNATE"   # defensible competing reading
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SlotExpectation(BaseModel):
    """What one slot must contain, declared up front."""

    kind: Literal["name", "date", "time", "phone", "reason"]
    expected: str | None = None
    # `reason` is fuzzy, so the scenario declares the accept-list in advance
    accept_any_of: list[str] = Field(default_factory=list)
    # extra literal spellings that count as correct (STT variants, nicknames)
    aliases: list[str] = Field(default_factory=list)
    # some scenarios assert a slot must NOT be filled (e.g. agent should refuse)
    must_be_absent: bool = False


class CallerTurn(BaseModel):
    """One thing the scripted caller does."""

    say: str | None = None
    # voice-channel behaviour directives, ignored by the text channel
    wait_for_agent: bool = True
    # interrupt the agent this many ms after it starts speaking (barge-in)
    interrupt_after_ms: int | None = None
    # stay silent for this long instead of speaking
    silence_ms: int | None = None
    # mix a noise fixture under this utterance
    noise: str | None = None
    # pre-rendered audio fixture; filled in by `harness.tts build`
    audio_file: str | None = None
    note: str = ""


class Scenario(BaseModel):
    id: str
    persona: Persona
    description: str
    # pinned "today" — makes every relative date in this scenario reproducible
    reference_date: date
    turns: list[CallerTurn]
    expected_slots: dict[str, SlotExpectation] = Field(default_factory=dict)

    # behavioural expectations, checked deterministically against tool logs
    must_confirm_before_booking: bool = True
    must_not_book: bool = False          # e.g. out-of-scope scenarios
    expect_tool_calls: list[str] = Field(default_factory=list)
    forbid_tool_calls: list[str] = Field(default_factory=list)

    # channels this scenario is meaningful on.  A barge-in has no text analogue;
    # saying otherwise would be dishonest, so it is declared here and the runner
    # skips it rather than pretending.
    channels: list[Channel] = Field(default_factory=lambda: ["voice", "text"])
    voice_only_rationale: str = ""

    @field_validator("turns")
    @classmethod
    def _non_empty(cls, v: list[CallerTurn]) -> list[CallerTurn]:
        if not v:
            raise ValueError("scenario needs at least one caller turn")
        return v


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


class SlotResult(BaseModel):
    slot: str
    verdict: Verdict
    expected: str | None
    actual: str | None                 # exactly what the agent captured, verbatim
    normalized_expected: str | None
    normalized_actual: str | None
    rule: str                          # which normalisation rule fired
    reasoning: str                     # why this verdict, in words


class BehaviourResult(BaseModel):
    check: str
    verdict: Verdict
    reasoning: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class TurnLatency(BaseModel):
    turn_index: int
    caller_utterance_end_ms: int | None
    agent_response_start_ms: int | None
    latency_ms: int | None
    note: str = ""


class JudgeSignal(BaseModel):
    """Secondary, non-authoritative.  Never contributes to pass/fail."""

    check: str
    rating: str
    rationale: str
    model: str
    raw_response: str


class RunResult(BaseModel):
    scenario_id: str
    persona: Persona
    channel: Channel
    arm: Arm
    run_index: int
    call_id: str | None = None
    started_at: str
    ended_at: str | None = None

    slots: list[SlotResult] = Field(default_factory=list)
    behaviours: list[BehaviourResult] = Field(default_factory=list)
    latencies: list[TurnLatency] = Field(default_factory=list)
    judge: list[JudgeSignal] = Field(default_factory=list)

    transcript: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    captured_slots: dict[str, Any] = Field(default_factory=dict)

    error: str | None = None

    # ---- derived, deterministic -------------------------------------------

    @property
    def slot_score(self) -> tuple[int, int]:
        """(passed, total). AMBIGUOUS_ALTERNATE counts as a miss for the strict
        headline number but is reported separately so it can be read either way."""
        scored = [s for s in self.slots if s.verdict != Verdict.NOT_APPLICABLE]
        return sum(s.verdict == Verdict.PASS for s in scored), len(scored)

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        p, t = self.slot_score
        slots_ok = t > 0 and p == t
        behaviours_ok = all(
            b.verdict in (Verdict.PASS, Verdict.NOT_APPLICABLE) for b in self.behaviours
        )
        return slots_ok and behaviours_ok


class Event(BaseModel):
    """Channel-independent conversation event.

    Both the voice and text adapters flatten Retell's payloads into this, so
    the scorer never imports anything Retell-specific and the tests can build
    conversations by hand.
    """

    role: Literal["agent", "user", "tool_call", "tool_result", "system"]
    text: str = ""
    name: str | None = None                # tool name
    args: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    start_ms: int | None = None
    end_ms: int | None = None
