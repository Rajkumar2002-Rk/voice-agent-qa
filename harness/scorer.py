"""The deterministic scorer.

Rules, not models.  Given a scenario and the flattened event list from a run,
this produces the same verdicts every time, on any machine, forever.  An LLM is
never consulted here — `harness.judge` is a separate, clearly-labelled signal
that cannot change any verdict in this file.

Every verdict carries `rule` (which comparison fired) and `reasoning` (why),
because "the agent got the date wrong" is useless without "it captured
2026-09-15, expected 2026-09-22".
"""

from __future__ import annotations

import re
from datetime import date

from .extract import extract_dates, extract_times
from .normalize import (
    Norm,
    alternate_date_reading,
    normalize_date,
    normalize_name,
    normalize_phone,
    normalize_reason,
    normalize_time,
    reason_matches,
)
from .schema import (
    BehaviourResult,
    Event,
    Scenario,
    SlotExpectation,
    SlotResult,
    TurnLatency,
    Verdict,
)

BOOK_TOOL = "book_appointment"
AVAILABILITY_TOOL = "check_availability"

# Declared up front so "did the caller agree?" stays a lookup, not a judgement.
# Deliberately conservative: a hedge ("I guess", "maybe") is NOT assent, because
# booking on a hedge is exactly the behaviour worth catching.
AFFIRMATIONS = (
    "yes", "yeah", "yep", "yup", "correct", "that's right", "thats right",
    "right", "sure", "ok", "okay", "sounds good", "perfect", "exactly",
    "please do", "go ahead", "that works", "confirmed", "affirmative",
)

_AFFIRM_RE = re.compile(
    r"\b(" + "|".join(a.replace("'", "'?") for a in AFFIRMATIONS) + r")\b",
    re.IGNORECASE,
)


def caller_affirmed(text: str) -> bool:
    """True if a caller utterance reads as agreement.

    Negations are checked first: "no, that's not right" contains "right" and
    would otherwise score as assent.
    """
    if not text:
        return False
    if re.search(r"\b(no|nope|not|wrong|incorrect|actually|change|instead)\b",
                 text, re.IGNORECASE):
        return False
    return bool(_AFFIRM_RE.search(text))


# --------------------------------------------------------------------------
# slots
# --------------------------------------------------------------------------


def _normalize_for(kind: str, raw: str | None, reference: date,
                   context: str = "spoken") -> Norm:
    if kind == "name":
        return normalize_name(raw)
    if kind == "date":
        return normalize_date(raw, reference)
    if kind == "time":
        return normalize_time(raw, context=context)
    if kind == "phone":
        return normalize_phone(raw)
    if kind == "reason":
        return normalize_reason(raw)
    raise ValueError(f"unknown slot kind {kind!r}")


def score_slot(
    slot: str,
    exp: SlotExpectation,
    actual_raw: str | None,
    reference: date,
) -> SlotResult:
    """Compare one captured slot against its declared expectation."""

    def result(v: Verdict, rule: str, reasoning: str, ne=None, na=None) -> SlotResult:
        return SlotResult(
            slot=slot, verdict=v, expected=exp.expected, actual=actual_raw,
            normalized_expected=ne, normalized_actual=na, rule=rule,
            reasoning=reasoning,
        )

    # --- slots the agent was supposed to leave alone -----------------------
    if exp.must_be_absent:
        if actual_raw is None or not str(actual_raw).strip():
            return result(Verdict.PASS, f"{exp.kind}.absent_as_required",
                          "slot correctly left empty")
        return result(Verdict.WRONG, f"{exp.kind}.should_be_absent",
                      f"expected no value, agent captured {actual_raw!r}")

    # --- nothing captured --------------------------------------------------
    if actual_raw is None or not str(actual_raw).strip():
        return result(Verdict.MISSING, f"{exp.kind}.not_captured",
                      "agent never captured this slot")

    # --- free-text reason: declared accept-list ----------------------------
    if exp.kind == "reason":
        n = normalize_reason(actual_raw)
        if not n.ok:
            return result(Verdict.UNPARSEABLE, n.rule, n.detail)
        ok, why = reason_matches(n.value or "", exp.accept_any_of)
        return result(
            Verdict.PASS if ok else Verdict.WRONG,
            "reason.accept_list",
            f"{why} (accept-list declared before the run)",
            ne="|".join(exp.accept_any_of), na=n.value,
        )

    # --- literal aliases short-circuit the normaliser ----------------------
    raw_s = str(actual_raw).strip().lower()
    if any(raw_s == a.strip().lower() for a in exp.aliases):
        return result(Verdict.PASS, f"{exp.kind}.alias",
                      f"{actual_raw!r} is a declared alias of {exp.expected!r}",
                      ne=exp.expected, na=raw_s)

    # the agent's value came out of a tool argument whose schema declares the
    # format; the scenario's expected value is authored by a human in prose
    got = _normalize_for(exp.kind, actual_raw, reference, context="structured")
    want = _normalize_for(exp.kind, exp.expected, reference, context="spoken")

    if not want.ok:
        return result(Verdict.UNPARSEABLE, want.rule,
                      f"SCENARIO BUG: expected value {exp.expected!r} does not "
                      f"normalise ({want.detail})")
    if not got.ok:
        return result(Verdict.UNPARSEABLE, got.rule,
                      f"agent captured {actual_raw!r}, which no rule could "
                      f"normalise ({got.detail})", ne=want.value)

    if got.value == want.value:
        return result(Verdict.PASS, got.rule,
                      f"{actual_raw!r} -> {got.value} matches expected "
                      f"{exp.expected!r} -> {want.value}",
                      ne=want.value, na=got.value)

    # a defensible competing reading of an ambiguous date is not the same
    # failure as getting it plainly wrong
    if exp.kind == "date":
        alt = alternate_date_reading(exp.expected, reference)
        if alt and alt.value == got.value:
            return result(
                Verdict.AMBIGUOUS_ALTERNATE, "date.alternate_reading",
                f"agent captured {got.value}, which is the other defensible "
                f"reading of {exp.expected!r} (harness convention says "
                f"{want.value}). Counted as a miss in the strict score and "
                f"reported separately.",
                ne=want.value, na=got.value,
            )

    return result(Verdict.WRONG, got.rule,
                  f"agent captured {actual_raw!r} -> {got.value}, expected "
                  f"{exp.expected!r} -> {want.value}",
                  ne=want.value, na=got.value)


def score_slots(
    scenario: Scenario, captured: dict[str, object]
) -> list[SlotResult]:
    return [
        score_slot(name, exp, _get(captured, name), scenario.reference_date)
        for name, exp in scenario.expected_slots.items()
    ]


def _get(d: dict[str, object], key: str) -> str | None:
    v = d.get(key)
    return None if v is None else str(v)


# --------------------------------------------------------------------------
# behaviours
# --------------------------------------------------------------------------


def _tool_calls(events: list[Event], name: str) -> list[Event]:
    return [e for e in events if e.role == "tool_call" and e.name == name]


def check_booking_discipline(scenario: Scenario, events: list[Event]) -> BehaviourResult:
    """Did the agent book when it should / refrain when it shouldn't?"""
    booked = _tool_calls(events, BOOK_TOOL)
    if scenario.must_not_book:
        if booked:
            return BehaviourResult(
                check="must_not_book", verdict=Verdict.WRONG,
                reasoning=f"agent called {BOOK_TOOL} {len(booked)}x though this "
                          f"scenario requires it not to book",
                evidence={"calls": [b.args for b in booked]},
            )
        return BehaviourResult(
            check="must_not_book", verdict=Verdict.PASS,
            reasoning="agent correctly did not book",
        )
    if not booked:
        return BehaviourResult(
            check="booked", verdict=Verdict.MISSING,
            reasoning=f"agent never called {BOOK_TOOL}; the appointment was "
                      f"never actually committed",
        )
    return BehaviourResult(
        check="booked", verdict=Verdict.PASS,
        reasoning=f"agent called {BOOK_TOOL}",
        evidence={"args": booked[-1].args},
    )


def check_confirmed_before_booking(
    scenario: Scenario, events: list[Event]
) -> BehaviourResult:
    """Did the agent read the details back *before* committing?

    Deterministic definition: some agent utterance strictly before the first
    book_appointment call must mention both the booked date and the booked
    time, as canonical values.  Mentioning them after the fact does not count —
    confirming a booking you already made is not confirmation.
    """
    if not scenario.must_confirm_before_booking:
        return BehaviourResult(
            check="confirmed_before_booking", verdict=Verdict.NOT_APPLICABLE,
            reasoning="scenario does not require confirm-back",
        )

    booked = _tool_calls(events, BOOK_TOOL)
    if not booked:
        return BehaviourResult(
            check="confirmed_before_booking", verdict=Verdict.NOT_APPLICABLE,
            reasoning="no booking was made, so there was nothing to confirm",
        )

    idx = next(
        i for i, e in enumerate(events)
        if e.role == "tool_call" and e.name == BOOK_TOOL
    )
    first_book = events[idx]
    booked_date = normalize_date(str(first_book.args.get("date", "")), scenario.reference_date)
    booked_time = normalize_time(str(first_book.args.get("time", "")),
                                 context="structured")

    # Walk the pre-booking window looking for a read-back, then for the caller
    # agreeing to it. Both are required: reading details back and then booking
    # without waiting is not confirmation, it is narration.
    confirm_at: int | None = None
    confirm_text = ""
    for i, e in enumerate(events[:idx]):
        if e.role != "agent" or not e.text:
            continue
        said_times = {t for _, t in extract_times(e.text, skip_hours_context=False)}
        said_dates = {d for _, d in extract_dates(e.text, scenario.reference_date)}
        if (booked_date.ok and booked_date.value in said_dates
                and booked_time.ok and booked_time.value in said_times):
            confirm_at, confirm_text = i, e.text
            break

    prior_agent = [e for e in events[:idx] if e.role == "agent" and e.text]

    if confirm_at is None:
        return BehaviourResult(
            check="confirmed_before_booking", verdict=Verdict.WRONG,
            reasoning=f"no agent utterance before {BOOK_TOOL} mentioned both the "
                      f"booked date ({booked_date.value}) and time "
                      f"({booked_time.value}); agent committed without reading "
                      f"the details back",
            evidence={"agent_utterances_before_booking": [e.text for e in prior_agent],
                      "failure": "no_readback"},
        )

    assent = next(
        (e for e in events[confirm_at + 1:idx]
         if e.role == "user" and caller_affirmed(e.text)),
        None,
    )
    if assent is None:
        heard = [e.text for e in events[confirm_at + 1:idx] if e.role == "user" and e.text]
        return BehaviourResult(
            check="confirmed_before_booking", verdict=Verdict.WRONG,
            reasoning=f"agent read the details back ({confirm_text[:90]!r}) but "
                      f"booked without the caller agreeing; caller said "
                      f"{heard if heard else 'nothing'} in between",
            evidence={"readback": confirm_text, "caller_turns_after_readback": heard,
                      "failure": "no_assent"},
        )

    return BehaviourResult(
        check="confirmed_before_booking", verdict=Verdict.PASS,
        reasoning=f"agent read back both date and time, then the caller agreed "
                  f"({assent.text[:60]!r}), then it booked",
        evidence={"readback": confirm_text, "assent": assent.text,
                  "date": booked_date.value, "time": booked_time.value},
    )


def check_invented_availability(
    scenario: Scenario, events: list[Event]
) -> BehaviourResult:
    """Did the agent state a specific time the availability tool never returned?

    Ground truth comes from the clinic tool server's own responses, which is
    why the agent has a real tool at all.  Times the *caller* proposed are
    excluded — repeating the caller back is not invention.
    """
    offered: set[str] = set()
    unparseable_offers: list[str] = []
    for e in events:
        if e.role == "tool_result" and e.name == AVAILABILITY_TOOL:
            for slot in e.result.get("slots", []) or []:
                # context="structured": these are the TOOL's own 24-hour values,
                # not speech. Parsing them as speech silently dropped every
                # morning slot ("09:00" reads as ambiguous), so an agent that
                # correctly offered a 9am opening was accused of inventing it.
                n = normalize_time(str(slot.get("time", slot)), context="structured")
                if n.ok and n.value:
                    offered.add(n.value)
                else:
                    # never silently drop ground truth — if the oracle's own
                    # value won't parse, that's a harness bug worth surfacing
                    unparseable_offers.append(str(slot.get("time", slot)))

    caller_times: set[str] = set()
    for e in events:
        if e.role == "user" and e.text:
            caller_times |= {t for _, t in extract_times(e.text, skip_hours_context=False)}

    invented: list[dict[str, object]] = []
    for e in events:
        if e.role != "agent" or not e.text:
            continue
        for raw, canon in extract_times(e.text):
            if canon not in offered and canon not in caller_times:
                invented.append({"said": raw, "canonical": canon, "utterance": e.text})

    called_tool = bool(_tool_calls(events, AVAILABILITY_TOOL))
    if invented:
        return BehaviourResult(
            check="invented_availability", verdict=Verdict.WRONG,
            reasoning=f"agent stated {len(invented)} time(s) that neither the "
                      f"{AVAILABILITY_TOOL} tool returned nor the caller "
                      f"proposed"
                      + ("" if called_tool else f"; it never called {AVAILABILITY_TOOL} at all"),
            evidence={"invented": invented, "tool_offered": sorted(offered),
                      "caller_proposed": sorted(caller_times),
                      "called_availability_tool": called_tool,
                      "unparseable_tool_offers": unparseable_offers},
        )
    return BehaviourResult(
        check="invented_availability", verdict=Verdict.PASS,
        reasoning="every specific time the agent stated came from the "
                  "availability tool or from the caller",
        evidence={"tool_offered": sorted(offered),
                  "caller_proposed": sorted(caller_times),
                  "called_availability_tool": called_tool,
                  "unparseable_tool_offers": unparseable_offers},
    )


# Negation cues that turn "2:00 PM" into "we don't have 2:00 PM". Deliberately
# narrow: this check is heuristic, and a false accusation is worse than a miss.
_DENIAL_RE = re.compile(
    r"\b(?:do\s?n[o']t have|does\s?n[o']t have|not available|isn[o']?t available|"
    r"no (?:openings?|slots?|availability)|unavailable|already booked|fully booked)\b",
    re.IGNORECASE,
)


def check_denied_available_slot(
    scenario: Scenario, events: list[Event]
) -> BehaviourResult:
    """Did the agent tell the caller a time was unavailable that the tool offered?

    The mirror image of invented_availability, and it was missing. A clinic agent
    that refuses bookings it could have taken is arguably worse for the business
    than one that invents them, and the invention check is blind to it by
    construction: it only looks at times the agent states that the tool did NOT
    return.

    Heuristic, and labelled as such: it requires a negation cue in the SAME
    utterance as a time the tool returned. That misses denials split across
    sentences and can fire on "2 PM is not available, but 2:30 is" phrasing where
    both times appear. Evidence carries the full utterance so every hit is
    auditable.
    """
    offered: set[str] = set()
    for e in events:
        if e.role == "tool_result" and e.name == AVAILABILITY_TOOL:
            for slot in e.result.get("slots", []) or []:
                n = normalize_time(str(slot.get("time", slot)), context="structured")
                if n.ok and n.value:
                    offered.add(n.value)

    if not offered:
        return BehaviourResult(
            check="denied_available_slot", verdict=Verdict.NOT_APPLICABLE,
            reasoning="the availability tool never returned any slots",
        )

    denials: list[dict[str, object]] = []
    for e in events:
        if e.role != "agent" or not e.text or not _DENIAL_RE.search(e.text):
            continue
        for raw, canon in extract_times(e.text, skip_hours_context=False):
            if canon in offered:
                denials.append({"said": raw, "canonical": canon, "utterance": e.text})

    if denials:
        return BehaviourResult(
            check="denied_available_slot", verdict=Verdict.WRONG,
            reasoning=f"agent told the caller {len(denials)} time(s) were "
                      f"unavailable that {AVAILABILITY_TOOL} had returned as open "
                      f"(heuristic check — see evidence)",
            evidence={"denied": denials, "tool_offered": sorted(offered)},
        )
    return BehaviourResult(
        check="denied_available_slot", verdict=Verdict.PASS,
        reasoning="agent never denied a slot the tool had offered",
        evidence={"tool_offered": sorted(offered)},
    )


def check_tool_expectations(scenario: Scenario, events: list[Event]) -> list[BehaviourResult]:
    out: list[BehaviourResult] = []
    called = {e.name for e in events if e.role == "tool_call" and e.name}
    for want in scenario.expect_tool_calls:
        out.append(BehaviourResult(
            check=f"expect_tool:{want}",
            verdict=Verdict.PASS if want in called else Verdict.MISSING,
            reasoning=f"{want} {'was' if want in called else 'was never'} called",
            evidence={"tools_called": sorted(called)},
        ))
    for forbid in scenario.forbid_tool_calls:
        out.append(BehaviourResult(
            check=f"forbid_tool:{forbid}",
            verdict=Verdict.WRONG if forbid in called else Verdict.PASS,
            reasoning=f"{forbid} {'was called but is forbidden' if forbid in called else 'correctly not called'}",
            evidence={"tools_called": sorted(called)},
        ))
    return out


# --------------------------------------------------------------------------
# latency
# --------------------------------------------------------------------------


def compute_latencies(events: list[Event]) -> list[TurnLatency]:
    """Gap between the caller finishing and the agent starting to respond.

    Only meaningful on the voice channel; the text channel has no notion of a
    caller "finishing speaking", and its numbers are reported separately as
    API round-trip, not conversational latency.
    """
    out: list[TurnLatency] = []
    turn = 0
    for i, e in enumerate(events):
        if e.role != "user":
            continue
        nxt = next((n for n in events[i + 1:] if n.role == "agent"), None)
        if nxt is None:
            out.append(TurnLatency(turn_index=turn, caller_utterance_end_ms=e.end_ms,
                                   agent_response_start_ms=None, latency_ms=None,
                                   note="agent never responded to this turn"))
        elif e.end_ms is None or nxt.start_ms is None:
            out.append(TurnLatency(turn_index=turn, caller_utterance_end_ms=e.end_ms,
                                   agent_response_start_ms=nxt.start_ms,
                                   latency_ms=None,
                                   note="channel did not supply timestamps"))
        else:
            out.append(TurnLatency(turn_index=turn, caller_utterance_end_ms=e.end_ms,
                                   agent_response_start_ms=nxt.start_ms,
                                   latency_ms=nxt.start_ms - e.end_ms))
        turn += 1
    return out


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def score_run(
    scenario: Scenario, events: list[Event], captured: dict[str, object]
) -> tuple[list[SlotResult], list[BehaviourResult], list[TurnLatency]]:
    slots = score_slots(scenario, captured)
    behaviours = [
        check_booking_discipline(scenario, events),
        check_confirmed_before_booking(scenario, events),
        check_invented_availability(scenario, events),
        check_denied_available_slot(scenario, events),
        *check_tool_expectations(scenario, events),
    ]
    return slots, behaviours, compute_latencies(events)
