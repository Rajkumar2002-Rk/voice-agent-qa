"""Scorer tests.

Everything here is synthetic — no Retell, no network, no model. That's the
point: if the scorer needed a live call to test, it wouldn't be deterministic.
"""



import pytest

from harness.schema import SlotExpectation, Verdict
from harness.scorer import (
    check_confirmed_before_booking,
    check_invented_availability,
    compute_latencies,
    score_run,
    score_slot,
)
from tests.conftest import REF, ev

# ---------------------------------------------------------------- slots ----

class TestSlotScoring:
    def test_exact_match_passes_and_explains(self):
        r = score_slot("time", SlotExpectation(kind="time", expected="3pm"), "15:00", REF)
        assert r.verdict == Verdict.PASS
        assert r.normalized_actual == "15:00"
        assert "15:00" in r.reasoning

    def test_wrong_slot_names_what_was_captured(self):
        """The headline requirement: report WHICH slot and WHAT it actually got."""
        r = score_slot("time", SlotExpectation(kind="time", expected="3pm"), "4pm", REF)
        assert r.verdict == Verdict.WRONG
        assert r.slot == "time"
        assert r.actual == "4pm"
        assert r.normalized_actual == "16:00"
        assert r.normalized_expected == "15:00"
        assert "16:00" in r.reasoning and "15:00" in r.reasoning

    def test_missing_slot(self):
        for empty in (None, "", "   "):
            r = score_slot("date", SlotExpectation(kind="date", expected="tomorrow"), empty, REF)
            assert r.verdict == Verdict.MISSING

    def test_alternate_date_reading_is_not_wrong(self):
        r = score_slot("date", SlotExpectation(kind="date", expected="next Tuesday"),
                       "2026-09-15", REF)
        assert r.verdict == Verdict.AMBIGUOUS_ALTERNATE
        assert "defensible" in r.reasoning

    def test_plainly_wrong_date_is_wrong_not_alternate(self):
        r = score_slot("date", SlotExpectation(kind="date", expected="next Tuesday"),
                       "2026-12-25", REF)
        assert r.verdict == Verdict.WRONG

    def test_unparseable_agent_value(self):
        r = score_slot("time", SlotExpectation(kind="time", expected="3pm"),
                       "sometime after lunch", REF)
        assert r.verdict == Verdict.UNPARSEABLE
        assert "normalise" in r.reasoning

    def test_scenario_bug_surfaces_as_unparseable(self):
        """A malformed expectation must accuse the scenario, not the agent."""
        r = score_slot("time", SlotExpectation(kind="time", expected="banana"), "3pm", REF)
        assert r.verdict == Verdict.UNPARSEABLE
        assert "SCENARIO BUG" in r.reasoning

    def test_alias_accepted(self):
        r = score_slot("patient_name",
                       SlotExpectation(kind="name", expected="Jonathan Reed",
                                       aliases=["Jon Reed"]),
                       "Jon Reed", REF)
        assert r.verdict == Verdict.PASS

    def test_must_be_absent(self):
        exp = SlotExpectation(kind="phone", must_be_absent=True)
        assert score_slot("phone", exp, None, REF).verdict == Verdict.PASS
        assert score_slot("phone", exp, "5551234567", REF).verdict == Verdict.WRONG

    def test_reason_uses_declared_accept_list(self):
        exp = SlotExpectation(kind="reason", accept_any_of=["knee", "joint"])
        assert score_slot("reason", exp, "my knee hurts", REF).verdict == Verdict.PASS
        assert score_slot("reason", exp, "flu shot", REF).verdict == Verdict.WRONG

    def test_determinism_same_input_same_output(self):
        exp = SlotExpectation(kind="date", expected="next Tuesday")
        runs = [score_slot("date", exp, "2026-09-22", REF).model_dump() for _ in range(50)]
        assert all(r == runs[0] for r in runs)


# ----------------------------------------------------------- behaviours ----

def _booked(date_="2026-09-22", time_="15:00"):
    return ev("tool_call", name="book_appointment",
              args={"date": date_, "time": time_, "patient_name": "John Smith"})


class TestConfirmBeforeBooking:
    def test_confirms_then_books(self, base_scenario):
        events = [
            ev("user", "Tuesday the 22nd at 3pm please"),
            ev("agent", "Just to confirm, that's 2026-09-22 at 3pm. Shall I book it?"),
            ev("user", "yes"),
            _booked(),
        ]
        r = check_confirmed_before_booking(base_scenario(), events)
        assert r.verdict == Verdict.PASS

    def test_books_without_confirming(self, base_scenario):
        events = [ev("user", "Tuesday at 3pm"), ev("agent", "Done!"), _booked()]
        r = check_confirmed_before_booking(base_scenario(), events)
        assert r.verdict == Verdict.WRONG
        assert "without reading" in r.reasoning

    def test_confirming_after_booking_does_not_count(self, base_scenario):
        """Reading back a booking you already committed is not confirmation."""
        events = [
            ev("user", "Tuesday at 3pm"),
            _booked(),
            ev("agent", "I've booked 2026-09-22 at 3pm for you."),
        ]
        assert check_confirmed_before_booking(base_scenario(), events).verdict == Verdict.WRONG

    def test_partial_confirmation_fails(self, base_scenario):
        """Date only, no time — not a real confirmation."""
        events = [
            ev("user", "Tuesday at 3pm"),
            ev("agent", "So that's Tuesday 2026-09-22, correct?"),
            _booked(),
        ]
        assert check_confirmed_before_booking(base_scenario(), events).verdict == Verdict.WRONG

    def test_not_applicable_when_nothing_booked(self, base_scenario):
        events = [ev("user", "never mind"), ev("agent", "No problem.")]
        assert check_confirmed_before_booking(base_scenario(), events).verdict == Verdict.NOT_APPLICABLE

    def test_duplicate_identical_bookings_uses_first(self, base_scenario):
        """Regression: list.index() on pydantic models matched by value, so a
        double-commit resolved to the wrong position."""
        events = [
            ev("user", "Tuesday at 3pm"),
            _booked(), _booked(),
            ev("agent", "Confirmed: 2026-09-22 at 3pm."),
        ]
        assert check_confirmed_before_booking(base_scenario(), events).verdict == Verdict.WRONG


class TestInventedAvailability:
    def test_offering_a_tool_returned_slot_is_clean(self, base_scenario):
        events = [
            ev("tool_call", name="check_availability", args={"date": "2026-09-22"}),
            ev("tool_result", name="check_availability",
               result={"slots": [{"time": "15:00"}, {"time": "16:00"}]}),
            ev("agent", "I have 3pm or 4pm available."),
        ]
        assert check_invented_availability(base_scenario(), events).verdict == Verdict.PASS

    def test_inventing_a_slot_is_caught(self, base_scenario):
        events = [
            ev("tool_call", name="check_availability", args={"date": "2026-09-22"}),
            ev("tool_result", name="check_availability", result={"slots": [{"time": "15:00"}]}),
            ev("agent", "I have 3pm, or I could squeeze you in at 9am."),
        ]
        r = check_invented_availability(base_scenario(), events)
        assert r.verdict == Verdict.WRONG
        assert r.evidence["invented"][0]["canonical"] == "09:00"

    def test_never_calling_the_tool_at_all_is_flagged(self, base_scenario):
        events = [ev("user", "any openings?"), ev("agent", "Sure, 2pm works.")]
        r = check_invented_availability(base_scenario(), events)
        assert r.verdict == Verdict.WRONG
        assert "never called" in r.reasoning

    def test_repeating_the_caller_is_not_invention(self, base_scenario):
        events = [
            ev("user", "Can I come at 3pm?"),
            ev("agent", "Let me check 3pm for you."),
        ]
        assert check_invented_availability(base_scenario(), events).verdict == Verdict.PASS

    def test_stating_opening_hours_is_not_invention(self, base_scenario):
        """Known false-positive mode, deliberately suppressed. Documented in findings."""
        events = [
            ev("tool_call", name="check_availability", args={}),
            ev("tool_result", name="check_availability", result={"slots": [{"time": "15:00"}]}),
            ev("agent", "We're open from 9am to 5pm. I have 3pm free."),
        ]
        assert check_invented_availability(base_scenario(), events).verdict == Verdict.PASS


class TestLatency:
    def test_computes_gap(self):
        events = [ev("user", "hi", end_ms=1000), ev("agent", "hello", start_ms=1450)]
        (l,) = compute_latencies(events)
        assert l.latency_ms == 450

    def test_missing_timestamps_reported_not_guessed(self):
        events = [ev("user", "hi"), ev("agent", "hello")]
        (l,) = compute_latencies(events)
        assert l.latency_ms is None and "timestamps" in l.note

    def test_no_agent_response(self):
        (l,) = compute_latencies([ev("user", "hi", end_ms=1000)])
        assert l.latency_ms is None and "never responded" in l.note


class TestEndToEnd:
    def test_clean_run_passes(self, base_scenario):
        sc = base_scenario()
        events = [
            ev("user", "John Smith, knee pain", end_ms=1000),
            ev("agent", "Confirming: 2026-09-22 at 3pm for John Smith.", start_ms=1200),
            ev("tool_call", name="check_availability", args={}),
            ev("tool_result", name="check_availability", result={"slots": [{"time": "15:00"}]}),
            ev("user", "Yes, that's right.", end_ms=4000),
            _booked(),
        ]
        captured = {"patient_name": "John Smith", "date": "2026-09-22",
                    "time": "15:00", "reason": "knee pain"}
        slots, behaviours, _ = score_run(sc, events, captured)
        assert all(s.verdict == Verdict.PASS for s in slots), [s.reasoning for s in slots]
        assert all(b.verdict in (Verdict.PASS, Verdict.NOT_APPLICABLE) for b in behaviours)

    def test_one_bad_slot_is_pinpointed(self, base_scenario):
        sc = base_scenario()
        captured = {"patient_name": "John Smith", "date": "2026-09-22",
                    "time": "16:00", "reason": "knee pain"}
        slots, _, _ = score_run(sc, [], captured)
        bad = [s for s in slots if s.verdict != Verdict.PASS]
        assert len(bad) == 1
        assert bad[0].slot == "time" and bad[0].normalized_actual == "16:00"


class TestConfirmRequiresAssent:
    """Regression: the deterministic check originally accepted a read-back with
    no caller reply, while the judge rubric demanded agreement. The two checks
    measured different things, which would have made the judge-vs-rules
    agreement number meaningless."""

    def _events(self, between):
        return [
            ev("user", "Tuesday the 22nd at 3pm"),
            ev("agent", "To confirm: 2026-09-22 at 3pm. Shall I book it?"),
            *between,
            _booked(),
        ]

    def test_readback_then_assent_passes(self, base_scenario):
        r = check_confirmed_before_booking(
            base_scenario(), self._events([ev("user", "Yes, that's right.")]))
        assert r.verdict == Verdict.PASS
        assert "caller agreed" in r.reasoning

    def test_readback_with_no_reply_at_all_fails(self, base_scenario):
        r = check_confirmed_before_booking(base_scenario(), self._events([]))
        assert r.verdict == Verdict.WRONG
        assert r.evidence["failure"] == "no_assent"

    def test_readback_then_rejection_fails(self, base_scenario):
        """'No, that's not right' contains 'right' — must not read as assent."""
        r = check_confirmed_before_booking(
            base_scenario(), self._events([ev("user", "No, that's not right.")]))
        assert r.verdict == Verdict.WRONG
        assert r.evidence["failure"] == "no_assent"

    def test_correction_is_not_assent(self, base_scenario):
        r = check_confirmed_before_booking(
            base_scenario(), self._events([ev("user", "Actually, make it 4pm instead.")]))
        assert r.verdict == Verdict.WRONG

    def test_no_readback_reports_that_distinctly(self, base_scenario):
        events = [ev("user", "Tuesday at 3pm"), ev("agent", "Done!"),
                  ev("user", "yes"), _booked()]
        r = check_confirmed_before_booking(base_scenario(), events)
        assert r.verdict == Verdict.WRONG
        assert r.evidence["failure"] == "no_readback"

    @pytest.mark.parametrize("reply,expected", [
        ("yes", True), ("Yeah", True), ("yep", True), ("that's right", True),
        ("Correct.", True), ("sounds good", True), ("go ahead", True),
        ("no", False), ("nope", False), ("wrong", False),
        ("actually no", False), ("hmm", False), ("", False),
    ])
    def test_affirmation_vocabulary(self, reply, expected):
        from harness.scorer import caller_affirmed
        assert caller_affirmed(reply) is expected


class TestAvailabilityGroundTruthParsing:
    """Regression: the availability tool's own 24-hour slots were parsed with
    SPOKEN rules, so every morning slot ("09:00") was dropped as ambiguous and
    an agent correctly offering 9am was accused of inventing it. This is the
    same root cause as the captured-slot bug, at a call site I missed."""

    def _events(self, slots, agent_text):
        return [
            ev("tool_call", name="check_availability", args={"date": "2026-09-22"}),
            ev("tool_result", name="check_availability",
               result={"slots": [{"time": t} for t in slots]}),
            ev("agent", agent_text),
        ]

    def test_morning_slots_are_ground_truth(self, base_scenario):
        r = check_invented_availability(base_scenario(), self._events(
            ["09:00", "09:30", "10:00"],
            "We have 9:00 AM, 9:30 AM, and 10:00 AM available."))
        assert r.verdict == Verdict.PASS, r.reasoning
        assert set(r.evidence["tool_offered"]) == {"09:00", "09:30", "10:00"}

    def test_full_day_offer_round_trips(self, base_scenario):
        """The exact real-world case that was misreported."""
        slots = ["09:00", "09:30", "10:00", "13:30", "15:00", "16:00"]
        r = check_invented_availability(base_scenario(), self._events(
            slots, "On Tuesday we have openings at 9:00 AM, 9:30 AM, 10:00 AM, "
                   "1:30 PM, 3:00 PM, and 4:00 PM. What works best?"))
        assert r.verdict == Verdict.PASS, r.reasoning
        assert set(r.evidence["tool_offered"]) == set(slots)

    def test_real_hallucination_still_caught(self, base_scenario):
        r = check_invented_availability(base_scenario(), self._events(
            ["09:00", "09:30"], "We have 9:00 AM, 9:30 AM, and 2:00 PM."))
        assert r.verdict == Verdict.WRONG
        assert [i["canonical"] for i in r.evidence["invented"]] == ["14:00"]

    def test_unparseable_ground_truth_is_surfaced_not_dropped(self, base_scenario):
        r = check_invented_availability(base_scenario(), self._events(
            ["banana"], "We have 3:00 PM."))
        assert r.evidence["unparseable_tool_offers"] == ["banana"]

    def test_against_the_real_clinic_server(self, base_scenario):
        """End-to-end: whatever the oracle emits must survive the scorer."""
        import os
        import tempfile
        os.environ.setdefault("CLINIC_LOG_DIR", tempfile.mkdtemp())
        from datetime import date as _date

        from agent.clinic_server import _deterministic_open_slots
        for d in ("2026-09-22", "2026-09-17", "2026-10-05", "2026-09-25"):
            slots = _deterministic_open_slots(_date.fromisoformat(d))
            spoken = ", ".join(
                f"{int(t[:2]) % 12 or 12}:{t[3:]} {'AM' if int(t[:2]) < 12 else 'PM'}"
                for t in slots
            )
            r = check_invented_availability(
                base_scenario(), self._events(slots, f"We have {spoken}."))
            assert r.verdict == Verdict.PASS, f"{d}: {r.reasoning}"
            assert not r.evidence["unparseable_tool_offers"], f"{d} dropped slots"
