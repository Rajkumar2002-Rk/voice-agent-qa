"""Validate the scenario set itself.

A scenario with an unreachable expectation would produce a confident, wrong
failure report about the agent. These tests check the test cases.
"""

import os
import tempfile

import pytest

os.environ.setdefault("CLINIC_LOG_DIR", tempfile.mkdtemp())

from agent.clinic_server import _deterministic_open_slots
from harness.loader import load_scenarios
from harness.normalize import normalize_date, normalize_time
from harness.schema import Verdict
from harness.scorer import score_slot

SCENARIOS = load_scenarios()
REQUIRED_PERSONAS = {
    "barge_in", "background_noise", "mind_change", "ambiguous_date",
    "long_silence", "out_of_scope", "self_correction", "compound_utterance",
}


def test_all_requested_personas_present():
    assert REQUIRED_PERSONAS <= {s.persona for s in SCENARIOS}


def test_ids_unique():
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.id)
class TestEachScenario:
    def test_expectations_normalise(self, sc):
        """Every declared expected value must be parseable by our own rules."""
        for name, exp in sc.expected_slots.items():
            if exp.must_be_absent or exp.kind == "reason":
                continue
            assert exp.expected, f"{sc.id}.{name} has no expected value"
            if exp.kind == "date":
                n = normalize_date(exp.expected, sc.reference_date)
            elif exp.kind == "time":
                n = normalize_time(exp.expected)
            else:
                continue
            assert n.ok, f"{sc.id}.{name}: {exp.expected!r} -> {n.detail}"

    def test_reason_slots_declare_accept_list(self, sc):
        for name, exp in sc.expected_slots.items():
            if exp.kind == "reason":
                assert exp.accept_any_of, f"{sc.id}.{name} needs accept_any_of"

    def test_expected_time_is_actually_available(self, sc):
        """The clinic must really have the slot the scenario expects, or the
        agent would be correct to refuse and we'd score it as a failure."""
        if sc.must_not_book:
            return
        d = sc.expected_slots.get("date")
        t = sc.expected_slots.get("time")
        if not (d and t) or d.must_be_absent or t.must_be_absent:
            return
        day = normalize_date(d.expected, sc.reference_date)
        tim = normalize_time(t.expected)
        open_slots = _deterministic_open_slots(
            __import__("datetime").date.fromisoformat(day.value)
        )
        assert tim.value in open_slots, (
            f"{sc.id} expects {tim.value} on {day.value} but the clinic only "
            f"has {open_slots}. Scenario is unsatisfiable."
        )

    def test_voice_only_scenarios_explain_themselves(self, sc):
        if sc.channels == ["voice"]:
            assert sc.voice_only_rationale.strip(), (
                f"{sc.id} is voice-only but gives no rationale; silently "
                f"dropping a channel needs a stated reason"
            )

    def test_perfect_capture_scores_clean(self, sc):
        """Feed the scenario its own expected values — everything must PASS.

        This is the scorer's self-consistency check: if a scenario cannot pass
        even with a perfect agent, the scenario is broken.
        """
        for name, exp in sc.expected_slots.items():
            if exp.must_be_absent:
                r = score_slot(name, exp, None, sc.reference_date)
            elif exp.kind == "reason":
                r = score_slot(name, exp, exp.accept_any_of[0], sc.reference_date)
            else:
                r = score_slot(name, exp, exp.expected, sc.reference_date)
            assert r.verdict == Verdict.PASS, f"{sc.id}.{name}: {r.reasoning}"
