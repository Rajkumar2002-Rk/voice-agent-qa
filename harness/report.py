"""Aggregate a run directory into a markdown report.

Reports the strict headline number and the things that qualify it — alternate
date readings, harness errors, judge disagreements — rather than a single
percentage that hides them.

Usage:  python -m harness.report runs/<dir>  [--out report.md]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from .schema import RunResult, Verdict


def load_results(run_dir: Path) -> list[RunResult]:
    p = run_dir / "results.jsonl"
    if not p.exists():
        raise SystemExit(f"no results.jsonl in {run_dir}")
    return [RunResult(**json.loads(line)) for line in p.read_text().splitlines() if line.strip()]


def _rate(passed: int, total: int) -> str:
    return f"{passed}/{total} ({100 * passed / total:.0f}%)" if total else "—"


def _cell(rs: list[RunResult]) -> str:
    return _rate(sum(r.passed for r in rs), len(rs)) if rs else "—"


def build(run_dir: Path) -> str:
    results = load_results(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text()) if (run_dir / "manifest.json").exists() else {}
    spend = json.loads((run_dir / "spend.json").read_text()) if (run_dir / "spend.json").exists() else {}

    arms = manifest.get("arms") or sorted({r.arm for r in results})
    channels = manifest.get("channels") or sorted({r.channel for r in results})

    L: list[str] = []
    add = L.append

    add(f"# Run report — `{run_dir.name}`\n")
    add(f"- runs: **{len(results)}**  ({sum(1 for r in results if r.error)} errored)")
    add(f"- arms: {', '.join(arms)}   channels: {', '.join(channels)}   "
        f"repeats: {manifest.get('repeats', '?')}")
    if spend:
        add(f"- spend: ${spend.get('spent_usd', 0):.2f} / ${spend.get('limit_usd', 0):.2f}"
            + ("  **ABORTED ON BUDGET**" if spend.get("aborted") else ""))
    j = manifest.get("judge") or {}
    add(f"- judge: {j.get('provider') or 'disabled'}"
        + (f" ({j.get('model')})" if j.get("model") else ""))
    add("")

    # ---------------- headline grid ----------------
    add("## Pass rate — prompt arm x channel\n")
    add("Strict: every expected slot correct AND every behavioural check passed.\n")
    add("| channel | " + " | ".join(arms) + " |")
    add("|---|" + "---|" * len(arms))
    for ch in channels:
        row = [_cell([r for r in results if r.arm == a and r.channel == ch]) for a in arms]
        add(f"| {ch} | " + " | ".join(row) + " |")
    add("")

    # ---------------- per-persona ----------------
    add("## Pass rate by persona\n")
    add("This is the table the experiment exists to produce: where the hardened "
        "prompt helped, and where it didn't.\n")
    personas = sorted({r.persona for r in results})
    header = ["persona"] + [f"{a}/{c}" for c in channels for a in arms]
    add("| " + " | ".join(header) + " |")
    add("|" + "---|" * len(header))
    for p in personas:
        row = [p]
        for c in channels:
            for a in arms:
                row.append(_cell([r for r in results
                                  if r.persona == p and r.arm == a and r.channel == c]))
        add("| " + " | ".join(row) + " |")
    add("")

    # ---------------- slot failures ----------------
    add("## Which slots failed\n")
    counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
    examples: dict[tuple[str, str, str, str], str] = {}
    for r in results:
        for s in r.slots:
            if s.verdict == Verdict.PASS:
                continue
            k = (r.arm, r.channel, s.slot, s.verdict.value)
            counts[k] += 1
            examples.setdefault(k, s.reasoning)
    if counts:
        add("| arm | channel | slot | verdict | n | example reasoning |")
        add("|---|---|---|---|---|---|")
        for k in sorted(counts, key=lambda x: -counts[x]):
            arm, ch, slot, v = k
            ex = examples[k].replace("|", "\\|")
            add(f"| {arm} | {ch} | `{slot}` | {v} | {counts[k]} | {ex[:150]} |")
    else:
        add("_No slot failures._")
    add("")

    # ---------------- ambiguity, separated out ----------------
    alts = [(r, s) for r in results for s in r.slots
            if s.verdict == Verdict.AMBIGUOUS_ALTERNATE]
    add("## Ambiguous-date alternate readings\n")
    if alts:
        add(f"{len(alts)} run(s) resolved an ambiguous date to the *other* defensible "
            f"reading. These count as failures in the strict number above; listing "
            f"them separately so they aren't mistaken for the agent being wrong.\n")
        add("| scenario | arm | channel | captured | harness convention |")
        add("|---|---|---|---|---|")
        for r, s in alts:
            add(f"| {r.scenario_id} | {r.arm} | {r.channel} | "
                f"{s.normalized_actual} | {s.normalized_expected} |")
    else:
        add("_None._")
    add("")

    # ---------------- follow-ups ----------------
    add("## Caller follow-ups needed\n")
    add("The scripted caller is open-loop. If the agent was still asking questions "
        "after the script ran out, the caller offered a bounded affirmation. An "
        "agent needing more nudges asked more questions — a real cost even when "
        "the run ultimately passed.\n")
    fu: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in results:
        fu[(r.arm, r.channel)].append(getattr(r, "followups_used", 0) or 0)
    if any(any(v) for v in fu.values()):
        add("| arm | channel | runs | used >=1 | mean |")
        add("|---|---|---|---|---|")
        for (arm, ch), vals in sorted(fu.items()):
            add(f"| {arm} | {ch} | {len(vals)} | {sum(1 for v in vals if v)} | "
                f"{sum(vals)/len(vals):.2f} |")
    else:
        add("_No run needed a follow-up._")
    add("")

    # ---------------- behaviours ----------------
    add("## Behavioural checks\n")
    bstats: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for r in results:
        for b in r.behaviours:
            bstats[(r.arm, r.channel, b.check)].append(b.verdict.value)
    add("| arm | channel | check | pass | fail | n/a |")
    add("|---|---|---|---|---|---|")
    for (arm, ch, check), vs in sorted(bstats.items()):
        add(f"| {arm} | {ch} | `{check}` | {vs.count('PASS')} | "
            f"{sum(1 for v in vs if v in ('WRONG', 'MISSING'))} | "
            f"{vs.count('NOT_APPLICABLE')} |")
    add("")

    # ---------------- latency ----------------
    add("## Turn latency\n")
    add("Voice only. Text-channel numbers are API round-trip and are not "
        "conversational latency; they are excluded here.\n")
    lat: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in results:
        if r.channel != "voice":
            continue
        for t in r.latencies:
            if t.latency_ms is not None:
                lat[(r.arm, r.persona)].append(t.latency_ms)
    if lat:
        add("| arm | persona | n | median ms | p90 ms | max ms |")
        add("|---|---|---|---|---|---|")
        for (arm, p), vals in sorted(lat.items()):
            vs = sorted(vals)
            p90 = vs[min(len(vs) - 1, int(0.9 * len(vs)))]
            add(f"| {arm} | {p} | {len(vs)} | {statistics.median(vs):.0f} | {p90} | {max(vs)} |")
    else:
        add("_No voice runs with usable timestamps._")
    add("")

    # ---------------- judge vs rules ----------------
    add("## LLM judge vs deterministic scorer\n")
    add("The judge grades two checks the rules already cover. Disagreements are "
        "listed because they are the evidence for keeping the primary score "
        "deterministic.\n")
    agree = disagree = unclear = 0
    rows: list[str] = []
    for raw in sorted((run_dir / "raw").glob("*.json")) if (run_dir / "raw").exists() else []:
        d = json.loads(raw.read_text())
        for check, info in (d.get("judge_agreement") or {}).items():
            a = info.get("agreement")
            if a == "agree":
                agree += 1
            elif a == "DISAGREE":
                disagree += 1
                why = str(info.get("judge_why", ""))[:120].replace("|", "&#124;")
                rows.append(
                    f"| {raw.stem} | `{check}` | rules: **{info['rule']}** | "
                    f"judge: **{info['judge']}** | {why} |"
                )
            elif a == "judge_unclear":
                unclear += 1
    total_cmp = agree + disagree + unclear
    if total_cmp:
        add(f"- agreed: **{agree}/{total_cmp}** ({100*agree/total_cmp:.0f}%)")
        add(f"- disagreed: **{disagree}**   judge said 'unclear': **{unclear}**\n")
        if rows:
            add("| run | check | deterministic | judge | judge's reason |")
            add("|---|---|---|---|---|")
            L.extend(rows)
    else:
        add("_Judge disabled or no overlapping checks recorded._")
    add("")

    # ---------------- errors ----------------
    errs = [r for r in results if r.error]
    if errs:
        add("## Harness errors\n")
        add("Runs that failed for harness/infrastructure reasons, not agent behaviour. "
            "Counted as failures above; listed so the distinction stays visible.\n")
        add("| scenario | arm | channel | error |")
        add("|---|---|---|---|")
        for r in errs:
            msg = (r.error or "")[:160].replace("|", "&#124;")
            add(f"| {r.scenario_id} | {r.arm} | {r.channel} | {msg} |")
        add("")

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(prog="harness.report")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    md = build(a.run_dir)
    out = a.out or (a.run_dir / "report.md")
    out.write_text(md)
    print(md)
    print(f"\n--- written to {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
