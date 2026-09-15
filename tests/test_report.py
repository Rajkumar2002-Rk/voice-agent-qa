"""The reporter must survive real shapes: empty runs, errors, pipes in text."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.report import build

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def synthetic_dir() -> Path:
    d = ROOT / "runs" / "_synthetic_example"
    if not (d / "results.jsonl").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_synthetic_run.py")],
                       check=True, cwd=ROOT)
    return d


def test_renders_synthetic_run(synthetic_dir):
    md = build(synthetic_dir)
    for heading in ("# Run report", "## Pass rate — prompt arm x channel",
                    "## Pass rate by persona", "## Which slots failed",
                    "## Behavioural checks", "## LLM judge vs deterministic scorer"):
        assert heading in md, f"missing section: {heading}"


def test_synthetic_run_is_labelled_fabricated(synthetic_dir):
    """Guard against fake numbers ever being mistaken for results."""
    manifest = json.loads((synthetic_dir / "manifest.json").read_text())
    assert manifest.get("SYNTHETIC") is True
    assert "FABRICATED" in manifest["warning"]
    assert (synthetic_dir / "README.md").exists()


def test_handles_errored_runs(tmp_path):
    row = {
        "scenario_id": "s01_happy_path", "persona": "happy_path", "channel": "text",
        "arm": "naive", "run_index": 0, "started_at": "2026-09-15T00:00:00Z",
        "ended_at": None, "slots": [], "behaviours": [], "latencies": [], "judge": [],
        "transcript": [], "tool_calls": [], "captured_slots": {},
        "error": "RetellError: boom | with a pipe",
    }
    (tmp_path / "results.jsonl").write_text(json.dumps(row) + "\n")
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"arms": ["naive"], "channels": ["text"], "repeats": 1}))
    md = build(tmp_path)
    assert "## Harness errors" in md
    # a pipe in an error must not break the markdown table
    assert "boom &#124; with a pipe" in md


def test_missing_results_file_errors_clearly(tmp_path):
    with pytest.raises(SystemExit, match="no results.jsonl"):
        build(tmp_path)


def test_synthetic_generation_is_byte_stable(tmp_path):
    """Regenerating the fixture must not churn the git tree.

    Regression: the generator stamped wall-clock times, so `make synthetic`
    rewrote 102 files every run. The first fix silently did nothing because
    ruff had rewritten `datetime.now(timezone.utc)` to `datetime.now(UTC)`
    and the patch matched no lines. Hence this test rather than a re-read.
    """
    import hashlib

    def snapshot() -> dict[str, str]:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_synthetic_run.py")],
                       check=True, cwd=ROOT, capture_output=True)
        d = ROOT / "runs" / "_synthetic_example"
        return {
            f.relative_to(d).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(d.rglob("*.json"))
        }

    assert snapshot() == snapshot(), "regenerating the fixture is not deterministic"
