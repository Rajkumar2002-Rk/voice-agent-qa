"""Merge run directories into one, for reporting across batches.

Needed because the voice ablation had to be split: s01-s03 completed before a
silent-fixture bug was found, s04-s10 were re-run after fixing it. Both halves
are valid; they just live in different directories.

Refuses to merge two runs of the same (scenario, arm, channel, repeat) unless
--prefer-latest is given, so a stale batch cannot silently shadow a re-run.

    python scripts/merge_runs.py OUT_DIR SRC_DIR [SRC_DIR ...] [--prefer-latest]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("src", nargs="+")
    ap.add_argument("--prefer-latest", action="store_true",
                    help="on a duplicate key, keep the one from the LAST source listed")
    ap.add_argument("--exclude", action="append", default=[],
                    metavar="SRC:SCENARIO_ID",
                    help="drop a scenario from one source, e.g. "
                         "'20260915T171735Z_voice-ablation:s04_mind_change'. Use this "
                         "rather than --prefer-latest when a batch is known invalid, "
                         "so the exclusion is explicit in the command and the manifest.")
    a = ap.parse_args()

    out = Path(a.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)

    drop: set[tuple[str, str]] = set()
    for spec in a.exclude:
        if ":" not in spec:
            raise SystemExit(f"--exclude needs SRC:SCENARIO_ID, got {spec!r}")
        src_name, scen = spec.split(":", 1)
        drop.add((src_name, scen))

    merged: dict[tuple, dict] = {}
    provenance: dict[str, str] = {}
    manifests: list[dict] = []
    conflicts: list[str] = []

    for src_name in a.src:
        src = Path(src_name)
        rp = src / "results.jsonl"
        if not rp.exists():
            raise SystemExit(f"{src} has no results.jsonl")
        mf = src / "manifest.json"
        if mf.exists():
            manifests.append({"source": src.name, **json.loads(mf.read_text())})

        for line in rp.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if (src.name, r["scenario_id"]) in drop:
                continue
            key = (r["scenario_id"], r["arm"], r["channel"], r["run_index"])
            if key in merged and not a.prefer_latest:
                conflicts.append(f"{key} in both {provenance[str(key)]} and {src.name}")
                continue
            merged[key] = r
            provenance[str(key)] = src.name

        for f in (src / "raw").glob("*.json") if (src / "raw").exists() else []:
            shutil.copy2(f, out / "raw" / f.name)

    if conflicts:
        print("REFUSING TO MERGE — duplicate runs found:", file=sys.stderr)
        for c in conflicts:
            print(f"  {c}", file=sys.stderr)
        print("\nPass --prefer-latest to keep the last source's copy.", file=sys.stderr)
        return 1

    rows = [merged[k] for k in sorted(merged)]
    (out / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (out / "manifest.json").write_text(json.dumps({
        "merged_from": a.src,
        "excluded": a.exclude,
        "note": "Merged across batches. See docs/notes.md B18 for why the voice "
                "ablation was split: s01-s03 ran before a silent-fixture bug was "
                "found, s04-s10 after it was fixed.",
        "arms": sorted({r["arm"] for r in rows}),
        "channels": sorted({r["channel"] for r in rows}),
        "repeats": max((r["run_index"] for r in rows), default=0) + 1,
        "scenarios": sorted({r["scenario_id"] for r in rows}),
        "judge": (manifests[0].get("judge") if manifests else None),
        "source_manifests": manifests,
    }, indent=2))

    print(f"merged {len(rows)} runs from {len(a.src)} source(s) -> {out}")
    by_src: dict[str, int] = {}
    for k in merged:
        by_src[provenance[str(k)]] = by_src.get(provenance[str(k)], 0) + 1
    for s, n in sorted(by_src.items()):
        print(f"  {n:3} from {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
