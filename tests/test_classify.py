"""The classifier encodes the experiment's central claim, so it gets tested
against hand-built 2x2 patterns rather than only against real data."""

import pytest

from harness.classify import classify
from harness.schema import RunResult


def _runs(pattern: dict[tuple[str, str], bool], persona="mind_change", n=3):
    """pattern: (arm, channel) -> should the runs pass?"""
    out = []
    for (arm, ch), should_pass in pattern.items():
        for i in range(n):
            r = RunResult(scenario_id="s", persona=persona, channel=ch, arm=arm,
                          run_index=i, started_at="t")
            # `passed` is derived; fake it by monkeypatching the instance
            object.__setattr__(r, "_forced", should_pass)
            out.append(r)
    return out


@pytest.fixture(autouse=True)
def _force_passed(monkeypatch):
    monkeypatch.setattr(RunResult, "passed",
                        property(lambda self: getattr(self, "_forced", False)))


ALL = [("naive", "text"), ("hardened", "text"), ("naive", "voice"), ("hardened", "voice")]


def test_fixed_by_prompt_in_both_channels():
    v = classify(_runs({ALL[0]: False, ALL[1]: True, ALL[2]: False, ALL[3]: True}))[0]
    assert v.label == "FIXED_BY_PROMPT"


def test_structural_to_voice():
    v = classify(_runs({ALL[0]: True, ALL[1]: True, ALL[2]: False, ALL[3]: False}))[0]
    assert v.label == "STRUCTURAL_TO_VOICE"
    assert "not the lever" in v.reasoning


def test_prompt_fixed_voice_only():
    v = classify(_runs({ALL[0]: True, ALL[1]: True, ALL[2]: False, ALL[3]: True}))[0]
    assert v.label == "PROMPT_FIXED_VOICE_ONLY"


def test_nothing_fixed():
    v = classify(_runs({k: False for k in ALL}))[0]
    assert v.label == "NOTHING_FIXED"


def test_not_a_problem():
    v = classify(_runs({k: True for k in ALL}))[0]
    assert v.label == "NOT_A_PROBLEM"


def test_text_only_evidence_is_not_overclaimed():
    """Text-only data must never yield a 'structural to voice' verdict."""
    v = classify(_runs({ALL[0]: False, ALL[1]: True}))[0]
    assert v.label == "TEXT_ONLY_EVIDENCE"
    assert "nothing can be said" in v.reasoning


def test_voice_only_persona_does_not_claim_structural():
    """barge_in has no text control, so 'structural' can't be ruled out."""
    v = classify(_runs({ALL[2]: False, ALL[3]: True}, persona="barge_in"))[0]
    assert v.label == "FIXED_BY_PROMPT"
    assert "cannot be ruled out" in v.reasoning


def test_one_flake_does_not_flip_a_verdict():
    runs = _runs({ALL[0]: True, ALL[1]: True, ALL[2]: False, ALL[3]: False})
    for r in runs:
        if (r.arm, r.channel) == ("hardened", "voice") and r.run_index == 0:
            object.__setattr__(r, "_forced", True)   # 1 of 3 passes = 33%
    assert classify(runs)[0].label == "STRUCTURAL_TO_VOICE"
