"""Re-score completed runs with the current scorer. No API calls, no cost.

This is the dividend of the deterministic design, and it is the direct answer to
the two batches lost today to scorer bugs. Because every run's flattened event
list and the agent's own tool-call arguments are committed, a scorer fix can be
applied retroactively to data already paid for.

    python -m harness.rescore runs/<dir>            # show what would change
    python -m harness.rescore runs/<dir> --write    # rewrite results.jsonl

The original results.jsonl is preserved as results.jsonl.bak-<n> so a rescore is
never destructive — a scorer "fix" that is itself wrong must be reversible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .loader import load_scenarios
from .schema import Event, RunResult
from .scorer import score_run


def rescore_dir(run_dir: Path, write: bool = False) -> int:
    path = run_dir / "results.jsonl"
    if not path.exists():
        raise SystemExit(f"no results.jsonl in {run_dir}")

    scenarios = {s.id: s for s in load_scenarios()}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    changed: list[tuple[str, str, str]] = []
    out_rows: list[dict] = []

    for row in rows:
        old = RunResult(**row)
        sc = scenarios.get(old.scenario_id)
        if sc is None or old.error:
            out_rows.append(row)
            continue

        events = [Event(**e) for e in old.transcript]
        slots, behaviours, latencies = score_run(sc, events, old.captured_slots)
        new = old.model_copy(update={"slots": slots, "behaviours": behaviours,
                                     "latencies": latencies})

        label = f"{old.scenario_id}/{old.arm}/{old.channel}#{old.run_index}"
        if old.passed != new.passed:
            changed.append((label, "PASS" if old.passed else "FAIL",
                            "PASS" if new.passed else "FAIL"))
        else:
            # Compare BY NAME, never by position. A scorer change that adds or
            # reorders a check shifts the lists, and positional zip then reports
            # a pile of spurious "changes" that are really different checks being
            # compared to each other — which is exactly what happened the first
            # time this ran.
            old_s = {x.slot: x.verdict for x in old.slots}
            new_s = {x.slot: x.verdict for x in new.slots}
            for name in sorted(old_s.keys() | new_s.keys()):
                a, b = old_s.get(name), new_s.get(name)
                if a != b:
                    changed.append((f"{label} [{name}]",
                                    a.value if a else "(absent)",
                                    b.value if b else "(absent)"))

            old_b = {x.check: x.verdict for x in old.behaviours}
            new_b = {x.check: x.verdict for x in new.behaviours}
            for name in sorted(old_b.keys() | new_b.keys()):
                a, b = old_b.get(name), new_b.get(name)
                if a != b:
                    changed.append((f"{label} [{name}]",
                                    a.value if a else "(new check)",
                                    b.value if b else "(removed)"))

        out_rows.append(new.model_dump(mode="json"))

    print(f"{len(rows)} runs re-scored against the current scorer")
    if not changed:
        print("no verdicts changed — the stored results already reflect this scorer")
    else:
        print(f"{len(changed)} verdict(s) would change:\n")
        for label, before, after in changed:
            print(f"  {label:52} {before:20} -> {after}")

    if write and changed:
        n = 1
        while (bak := run_dir / f"results.jsonl.bak-{n}").exists():
            n += 1
        bak.write_text(path.read_text())
        path.write_text("\n".join(json.dumps(r) for r in out_rows) + "\n")
        print(f"\nwrote {path}\noriginal preserved at {bak}")
    elif changed:
        print("\n(dry run — pass --write to apply)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="harness.rescore")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    return rescore_dir(a.run_dir, a.write)


if __name__ == "__main__":
    raise SystemExit(main())
