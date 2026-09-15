"""Standalone audibility check over every committed caller fixture.

Exists because two silent renders reached live calls and scored as agent
failures. Wired into CI so a bad fixture can never be committed again.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "audio"
MIN_PEAK_DBFS = -20.0


def peak_dbfs(path: Path) -> float:
    r = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else -999.0


def main() -> int:
    if not FIXTURES.exists():
        print("no fixtures directory — nothing to check")
        return 0
    bad = []
    n = 0
    for f in sorted(FIXTURES.glob("*.wav")):
        if f.name.startswith("noise_"):
            continue
        n += 1
        p = peak_dbfs(f)
        if p < MIN_PEAK_DBFS:
            bad.append((f.name, p))
    print(f"{n} caller fixtures checked")
    for name, p in bad:
        print(f"  SILENT  {name}  peak {p:.1f} dBFS")
    if bad:
        print(f"\n{len(bad)} fixture(s) are effectively silent. Re-render with:")
        print("  python -m harness.tts build --force")
        return 1
    print("all fixtures audible")
    return 0


if __name__ == "__main__":
    sys.exit(main())
