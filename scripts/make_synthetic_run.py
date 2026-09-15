"""Fabricate a run directory so the reporter can be exercised without an API key.

!!! THE NUMBERS THIS PRODUCES ARE INVENTED. !!!

It exists so that (a) `harness.report` is covered by a test, and (b) someone
cloning this repo without a Retell account can see what the output looks like.
Every artifact it writes is stamped synthetic:true and lands in a directory
named `_synthetic_*`. Nothing in docs/findings.md is derived from it.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.loader import load_scenarios
from harness.schema import Event
from harness.scorer import score_run

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "_synthetic_example"

# Frozen so regenerating produces byte-identical files. A wall-clock stamp here
# rewrote all 102 artifacts on every run and dirtied the git tree for nothing.
FROZEN_TS = "2026-09-15T00:00:00+00:00"


def fake_events(sc, arm: str, rng: random.Random) -> tuple[list[Event], dict]:
    """Build a plausible conversation. The hardened arm behaves better on
    purpose — this is a rendering fixture, not evidence."""
    good = arm == "hardened" or rng.random() < 0.45

    exp = sc.expected_slots
    want_date = exp.get("date").expected if "date" in exp else None
    want_time = exp.get("time").expected if "time" in exp else None
    name = exp.get("patient_name").expected if "patient_name" in exp else None

    from harness.normalize import normalize_date, normalize_time
    d = normalize_date(want_date, sc.reference_date).value if want_date else None
    t = normalize_time(want_time).value if want_time else None

    ev: list[Event] = [Event(role="agent", text="Thanks for calling Lakeside.",
                             start_ms=0, end_ms=1500)]
    clock = 2000
    for turn in sc.turns:
        if not turn.say:
            continue
        ev.append(Event(role="user", text=turn.say, start_ms=clock, end_ms=clock + 1200))
        clock += 1200
        gap = rng.randint(380, 900) if arm == "hardened" else rng.randint(450, 1600)
        ev.append(Event(role="agent", text="Okay.", start_ms=clock + gap,
                        end_ms=clock + gap + 900))
        clock += gap + 900

    if sc.must_not_book:
        ev.append(Event(role="agent", text="I can't help with that, I only book "
                                           "appointments.", start_ms=clock, end_ms=clock + 1500))
        return ev, {}

    if d:
        ev.append(Event(role="tool_call", name="check_availability", args={"date": d}))
        ev.append(Event(role="tool_result", name="check_availability",
                        result={"slots": [{"time": t}] if t else []}))
    if good and d and t:
        ev.append(Event(role="agent",
                        text=f"Confirming: {d} at {t} for {name}. Correct?",
                        start_ms=clock, end_ms=clock + 2000))
        # the caller has to actually agree — confirm-back requires assent
        ev.append(Event(role="user", text="Yes, that's correct.",
                        start_ms=clock + 2200, end_ms=clock + 3000))
    captured = {"patient_name": name, "date": d, "time": t,
                "reason": (exp["reason"].accept_any_of[0] if "reason" in exp else None)}
    if "phone" in exp:
        captured["phone"] = exp["phone"].expected if good else "5551234567"
    if not good:
        # inject a realistic-looking failure
        mode = rng.choice(["wrong_time", "drop_name", "no_confirm"])
        if mode == "wrong_time" and t:
            hh, mm = t.split(":")
            captured["time"] = f"{(int(hh)+1)%24:02d}:{mm}"
        elif mode == "drop_name":
            captured["patient_name"] = None
    ev.append(Event(role="tool_call", name="book_appointment",
                    args={k: v for k, v in captured.items() if v}))
    return ev, {k: v for k, v in captured.items() if v}


def main() -> int:
    rng = random.Random(20260915)
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    scenarios = load_scenarios()
    arms, channels, repeats = ["naive", "hardened"], ["voice", "text"], 3

    rows = []
    for sc in scenarios:
        for arm in arms:
            for ch in channels:
                if ch not in sc.channels:
                    continue
                for i in range(repeats):
                    ev, captured = fake_events(sc, arm, rng)
                    slots, behaviours, lat = score_run(sc, ev, captured)
                    r = {
                        "scenario_id": sc.id, "persona": sc.persona, "channel": ch,
                        "arm": arm, "run_index": i, "call_id": f"SYNTHETIC-{sc.id}-{arm}-{ch}-{i}",
                        "started_at": FROZEN_TS,
                        "ended_at": FROZEN_TS,
                        "slots": [s.model_dump(mode="json") for s in slots],
                        "behaviours": [b.model_dump(mode="json") for b in behaviours],
                        "latencies": [l.model_dump(mode="json") for l in lat] if ch == "voice" else [],
                        "judge": [], "transcript": [e.model_dump(mode="json") for e in ev],
                        "tool_calls": [], "captured_slots": captured, "error": None,
                    }
                    rows.append(r)
                    (OUT / "raw" / f"{sc.id}__{arm}__{ch}__{i}.json").write_text(
                        json.dumps({"synthetic": True, "result": r,
                                    "judge_agreement": {}}, indent=2, default=str))

    (OUT / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (OUT / "manifest.json").write_text(json.dumps({
        "SYNTHETIC": True,
        "warning": "FABRICATED DATA — generated by scripts/make_synthetic_run.py to "
                   "exercise the reporter. Not a real experiment. Not used in findings.",
        "arms": arms, "channels": channels, "repeats": repeats,
        "scenarios": [s.id for s in scenarios],
        "judge": {"provider": None, "model": None},
    }, indent=2))
    (OUT / "README.md").write_text(
        "# SYNTHETIC EXAMPLE RUN\n\n"
        "**The numbers in this directory are fabricated.** They were generated by\n"
        "`scripts/make_synthetic_run.py` so the report generator has test coverage and\n"
        "so the repo shows what output looks like without a Retell account.\n\n"
        "No claim in `docs/findings.md` is based on anything in here.\n"
    )
    print(f"wrote {len(rows)} synthetic runs to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
