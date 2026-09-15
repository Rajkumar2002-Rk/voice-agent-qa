from datetime import date

import pytest

from harness.schema import CallerTurn, Event, Scenario, SlotExpectation

REF = date(2026, 9, 14)  # a Monday — every fixture resolves against this


def ev(role, text="", name=None, args=None, result=None, start_ms=None, end_ms=None):
    return Event(role=role, text=text, name=name, args=args or {},
                 result=result or {}, start_ms=start_ms, end_ms=end_ms)


@pytest.fixture
def base_scenario():
    def _make(**over):
        kw: dict = {
            "id": "t_basic",
            "persona": "happy_path",
            "description": "test",
            "reference_date": REF,
            "turns": [CallerTurn(say="hello")],
            "expected_slots": {
                "patient_name": SlotExpectation(kind="name", expected="John Smith"),
                "date": SlotExpectation(kind="date", expected="next Tuesday"),
                "time": SlotExpectation(kind="time", expected="3pm"),
                "reason": SlotExpectation(
                    kind="reason", accept_any_of=["knee", "leg", "joint"]
                ),
            },
        }
        kw.update(over)
        return Scenario(**kw)
    return _make
