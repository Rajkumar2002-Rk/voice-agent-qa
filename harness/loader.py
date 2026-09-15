"""Load scenario YAML into validated Scenario objects."""

from __future__ import annotations

from pathlib import Path

import yaml

from .schema import Scenario

SCENARIO_DIR = Path(__file__).parent / "scenarios"


def load_scenarios(directory: Path | None = None) -> list[Scenario]:
    d = directory or SCENARIO_DIR
    out = [Scenario(**yaml.safe_load(p.read_text())) for p in sorted(d.glob("*.yaml"))]
    ids = [s.id for s in out]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate scenario ids: {ids}")
    return out


def load_scenario(scenario_id: str) -> Scenario:
    for s in load_scenarios():
        if s.id == scenario_id:
            return s
    raise KeyError(scenario_id)
