"""Orchestrate the ablation and commit every raw transcript.

Grid: scenario x prompt arm x channel x repeat. Everything except the prompt
arm and the channel is held fixed, and the pinned config is copied into each
run directory so a result can never be silently compared against a different
setup.

Usage:
    python -m harness.runner --arms naive hardened --channels text --repeats 3
    python -m harness.runner --channels voice text --repeats 3
    python -m harness.runner --scenario s05_ambiguous_next_tuesday --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .judge import judge_run, judge_vs_rules, resolve_provider
from .loader import load_scenarios
from .retell_client import RetellClient
from .schema import Channel, RunResult, Scenario
from .scorer import score_run

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"

# Retell voice pricing is roughly $0.07-0.31/min depending on model+voice.
# We estimate pessimistically so the guard trips early rather than late.
VOICE_USD_PER_MIN = float(os.getenv("VOICE_USD_PER_MIN", "0.16"))
TEXT_USD_PER_RUN = float(os.getenv("TEXT_USD_PER_RUN", "0.01"))


class BudgetExceeded(RuntimeError):
    pass


LEDGER = RUNS / "_spend_ledger.jsonl"


def lifetime_spend() -> float:
    """Everything this harness has ever charged, across all runs.

    Read from an append-only ledger rather than by summing spend.json files,
    because those are only written when a run *finishes* — three runs were
    killed mid-batch today and their cost vanished from the accounting
    entirely, which is how a $10 credit ran out while the tracker read $8.
    """
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    for line in LEDGER.read_text().splitlines():
        if line.strip():
            try:
                total += json.loads(line).get("usd", 0.0)
            except json.JSONDecodeError:
                continue
    return total


class Budget:
    def __init__(self, limit_usd: float):
        self.limit = limit_usd
        self.spent = 0.0
        self.detail: list[dict[str, Any]] = []
        LEDGER.parent.mkdir(parents=True, exist_ok=True)

    def estimate(self, voice_runs: int, text_runs: int, avg_call_s: float) -> float:
        return voice_runs * (avg_call_s / 60) * VOICE_USD_PER_MIN + text_runs * TEXT_USD_PER_RUN

    def charge(self, kind: str, seconds: float, label: str) -> None:
        cost = (seconds / 60) * VOICE_USD_PER_MIN if kind == "voice" else TEXT_USD_PER_RUN
        self.spent += cost
        rec = {"label": label, "kind": kind, "seconds": round(seconds, 1),
               "usd": round(cost, 4), "cumulative_usd": round(self.spent, 4)}
        self.detail.append(rec)
        # append immediately: a killed run must not erase what it already spent
        with LEDGER.open("a") as fh:
            fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), **rec}) + "\n")
        if self.spent > self.limit:
            raise BudgetExceeded(
                f"spend ${self.spent:.2f} exceeded MAX_SPEND_USD=${self.limit:.2f} "
                f"after {label}. Partial results are saved."
            )


def _agent_id(arm: str, channel: Channel) -> str:
    key = (f"RETELL_AGENT_ID_{arm.upper()}" if channel == "voice"
           else f"RETELL_CHAT_AGENT_ID_{arm.upper()}")
    v = os.getenv(key)
    if not v:
        raise RuntimeError(
            f"{key} is not set. Run `python -m agent.provision --tool-url ...` first "
            f"(see docs/retell-setup.md)."
        )
    return v


def _run_one(client: RetellClient, scenario: Scenario, arm: str, channel: Channel,
             run_index: int, max_call_seconds: int) -> tuple[RunResult, float, dict]:
    started = datetime.now(UTC).isoformat()
    t0 = time.perf_counter()
    try:
        if channel == "text":
            from .channels.text import run_text_scenario
            out = run_text_scenario(client, _agent_id(arm, channel), scenario)
        else:
            from .channels.audio import run_voice_scenario
            out = run_voice_scenario(client, _agent_id(arm, channel), scenario,
                                     max_call_seconds=max_call_seconds)
    except Exception as e:  # noqa: BLE001 - one bad run must not abort the
        # grid; the error is recorded on the result and reported as such
        elapsed = time.perf_counter() - t0
        return (RunResult(scenario_id=scenario.id, persona=scenario.persona,
                          channel=channel, arm=arm, run_index=run_index,
                          started_at=started,
                          ended_at=datetime.now(UTC).isoformat(),
                          error=f"{type(e).__name__}: {e}"), elapsed, {})

    elapsed = time.perf_counter() - t0
    events = out["events"]
    slots, behaviours, latencies = score_run(scenario, events, out["captured_slots"])

    judge_signals = judge_run(scenario, events)
    agreement = judge_vs_rules(judge_signals, behaviours)

    result = RunResult(
        scenario_id=scenario.id, persona=scenario.persona, channel=channel, arm=arm,
        run_index=run_index, call_id=out.get("call_id"), started_at=started,
        ended_at=out.get("ended_at"), slots=slots, behaviours=behaviours,
        latencies=latencies, judge=judge_signals,
        transcript=[e.model_dump() for e in events],
        tool_calls=[e.model_dump() for e in events if e.role in ("tool_call", "tool_result")],
        captured_slots=out["captured_slots"],
        followups_used=out.get("followups_used", 0),
    )
    return result, elapsed, {"raw": out.get("raw"), "driver_log": out.get("driver_log"),
                             "judge_agreement": agreement,
                             "retell_latency": out.get("retell_latency"),
                             "turn_timings": out.get("turn_timings")}


def main() -> int:
    ap = argparse.ArgumentParser(prog="harness.runner")
    ap.add_argument("--arms", nargs="+", default=["naive", "hardened"])
    ap.add_argument("--channels", nargs="+", default=["text"], choices=["text", "voice"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--scenario", action="append", help="limit to these scenario ids")
    ap.add_argument("--dry-run", action="store_true", help="print the grid and cost estimate only")
    ap.add_argument("--label", default="", help="name for this run directory")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    max_spend = float(os.getenv("MAX_SPEND_USD", "8.00"))
    max_call_s = int(os.getenv("MAX_CALL_SECONDS", "120"))

    scenarios = load_scenarios()
    if args.scenario:
        scenarios = [s for s in scenarios if s.id in set(args.scenario)]
        if not scenarios:
            print("no scenarios matched")
            return 1

    grid = [
        (sc, arm, ch, i)
        for sc in scenarios
        for arm in args.arms
        for ch in args.channels
        if ch in sc.channels
        for i in range(args.repeats)
    ]
    skipped = [
        (sc.id, ch) for sc in scenarios for ch in args.channels if ch not in sc.channels
    ]

    n_voice = sum(1 for g in grid if g[2] == "voice")
    n_text = len(grid) - n_voice
    budget = Budget(max_spend)
    est = budget.estimate(n_voice, n_text, avg_call_s=min(max_call_s, 90))

    provider, model = resolve_provider()
    print(f"grid: {len(grid)} runs  ({n_voice} voice, {n_text} text)")
    print(f"      {len(scenarios)} scenarios x {len(args.arms)} arms x "
          f"{len(args.channels)} channels x {args.repeats} repeats")
    if skipped:
        print(f"skipped (channel not meaningful for scenario): "
              f"{', '.join(f'{a}/{b}' for a, b in sorted(set(skipped)))}")
    lifetime = lifetime_spend()
    print(f"estimated spend: ${est:.2f}  (guard at ${max_spend:.2f})")
    print(f"lifetime spend by this harness: ${lifetime:.2f}"
          + (f"  [+ ${est:.2f} would be ${lifetime + est:.2f}]" if est else ""))
    print(f"judge: {provider or 'disabled'}{'/' + model if model else ''}")

    if est > max_spend:
        print(f"\nREFUSING TO START: estimate ${est:.2f} exceeds MAX_SPEND_USD "
              f"${max_spend:.2f}. Lower --repeats, or raise the guard in .env.")
        return 2
    if args.dry_run:
        for sc, arm, ch, i in grid:
            print(f"  {sc.id:32} {arm:9} {ch:6} #{i}")
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    outdir = RUNS / (f"{stamp}_{args.label}" if args.label else stamp)
    (outdir / "raw").mkdir(parents=True, exist_ok=True)

    manifest = {
        "started_at": datetime.now(UTC).isoformat(),
        "arms": args.arms, "channels": args.channels, "repeats": args.repeats,
        "scenarios": [s.id for s in scenarios],
        "judge": {"provider": provider, "model": model},
        "skipped_channel_pairs": sorted(set(skipped)),
        "estimated_usd": round(est, 4),
    }
    agent_manifest = RUNS / "agent_manifest.json"
    if agent_manifest.exists():
        manifest["agent_config"] = json.loads(agent_manifest.read_text())
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    client = RetellClient()
    results_path = outdir / "results.jsonl"
    aborted = None

    with results_path.open("w") as fh:
        for n, (sc, arm, ch, i) in enumerate(grid, 1):
            label = f"{sc.id}/{arm}/{ch}#{i}"
            print(f"[{n}/{len(grid)}] {label} … ", end="", flush=True)
            result, elapsed, extra = _run_one(client, sc, arm, ch, i, max_call_s)

            fh.write(json.dumps(result.model_dump(mode="json")) + "\n")
            fh.flush()
            (outdir / "raw" / f"{sc.id}__{arm}__{ch}__{i}.json").write_text(
                json.dumps({"result": result.model_dump(mode="json"), **extra},
                           indent=2, default=str))

            if result.error:
                print(f"ERROR  {result.error[:80]}")
            else:
                p, t = result.slot_score
                print(f"{'PASS' if result.passed else 'FAIL'}  slots {p}/{t}  ({elapsed:.1f}s)")

            try:
                budget.charge(ch, elapsed, label)
            except BudgetExceeded as e:
                print(f"\n{e}")
                aborted = str(e)
                break

    (outdir / "spend.json").write_text(json.dumps(
        {"limit_usd": max_spend, "spent_usd": round(budget.spent, 4),
         "aborted": aborted, "detail": budget.detail}, indent=2))
    client.close()

    print(f"\nspend: ${budget.spent:.2f} / ${max_spend:.2f}")
    print(f"results: {results_path}")
    print(f"next:    python -m harness.report {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
