"""Cheap sanity checks to run before spending money on a batch.

Written after losing two ablation attempts to setup bugs that produced
confident, well-formatted, entirely invalid results:

  - the agent resolved "Tuesday the twenty-second" to 2024-08-22, because
    nothing ever told it what day it is
  - the tool webhook 404'd silently after the tunnel restarted, so the agent
    lost its tools mid-call and looked like it had simply refused to use them

Both cost a full batch to discover. Both are detectable in one $0.01 chat.

Usage:  python -m harness.preflight
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

from .channels.text import run_text_scenario
from .loader import load_scenario
from .retell_client import RetellClient

ROOT = Path(__file__).resolve().parents[1]
TOOL_LOG = ROOT / "runs" / "_tool_log" / "_all.jsonl"


class Check:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def add(self, ok: bool, name: str, detail: str = "") -> None:
        self.rows.append((ok, name, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n          {detail}" if detail else ""))

    @property
    def failed(self) -> int:
        return sum(1 for ok, _, _ in self.rows if not ok)


def main() -> int:
    load_dotenv(ROOT / ".env")
    import os

    c = Check()
    print("preflight — one cheap text run, then assertions\n")

    # 1. credentials
    try:
        client = RetellClient()
        agents = client.list_agents()
        c.add(True, "RETELL_API_KEY valid", f"{len(agents)} agent(s) on the account")
    except Exception as e:  # noqa: BLE001 - preflight reports, never raises
        c.add(False, "RETELL_API_KEY valid", str(e)[:160])
        return 1

    # 2. agents provisioned
    missing = [k for k in ("RETELL_CHAT_AGENT_ID_NAIVE", "RETELL_CHAT_AGENT_ID_HARDENED",
                           "RETELL_AGENT_ID_NAIVE", "RETELL_AGENT_ID_HARDENED")
               if not os.getenv(k)]
    c.add(not missing, "all four agent ids present",
          f"missing: {', '.join(missing)}" if missing else "")
    if missing:
        return 1

    # 3. the prompt the agent is actually running matches the file on disk
    from agent.provision import _prompt_text
    for arm in ("naive", "hardened"):
        llm_id = os.getenv(f"RETELL_LLM_ID_{arm.upper()}")
        if not llm_id:
            c.add(False, f"{arm}: llm id recorded")
            continue
        live = client._req("GET", f"/get-retell-llm/{llm_id}").get("general_prompt", "")
        want = _prompt_text(arm)
        same = live.strip() == want.strip()
        c.add(same, f"{arm}: live prompt matches agent/prompts/{arm}.md",
              "" if same else "re-run `make provision URL=... UPDATE=1`")
        c.add("{{current_date}}" in live, f"{arm}: prompt carries the date variable",
              "" if "{{current_date}}" in live else "agent will not know what day it is")

    # 4. one real run, then check what the agent actually did
    sc = load_scenario("s01_happy_path")
    # derive from the scenario, never hardcode — the check must follow the
    # scenario if its reference_date or expected date ever changes
    from .normalize import normalize_date
    expect_date = normalize_date(
        sc.expected_slots["date"].expected, sc.reference_date
    ).value
    print("\n  running s01_happy_path once (naive/text) …")
    before = TOOL_LOG.stat().st_size if TOOL_LOG.exists() else 0
    try:
        out = run_text_scenario(client, os.getenv("RETELL_CHAT_AGENT_ID_NAIVE"), sc)
    except Exception as e:  # noqa: BLE001 - preflight reports, never raises
        c.add(False, "test run completed", str(e)[:200])
        return 1
    c.add(True, "test run completed", f"chat {out['call_id']}")

    events = out["events"]
    avail = [e for e in events if e.role == "tool_call" and e.name == "check_availability"]
    book = [e for e in events if e.role == "tool_call" and e.name == "book_appointment"]

    # 5. tools actually reachable — this is the tunnel check
    c.add(bool(avail), "agent called check_availability",
          "" if avail else "agent never used its tool — check the tunnel URL is current")
    grew = TOOL_LOG.exists() and TOOL_LOG.stat().st_size > before
    c.add(grew, "clinic server received the webhook",
          "" if grew else "tunnel is stale or down; re-run provision with the new URL")

    # 6. THE date check — the bug that cost a batch
    if avail:
        got = str(avail[0].args.get("date", ""))
        ok = got == expect_date
        c.add(ok, "agent resolves dates against the scenario reference_date",
              "" if ok else f"agent used {got!r}, expected {expect_date!r} — "
                            f"it does not know what day it is")

    # 7. captured slots land
    c.add(bool(book), "agent completed a booking",
          "" if book else "no book_appointment call")
    if book:
        got = out["captured_slots"]
        c.add(got.get("date") == expect_date, "booked date is correct",
              f"booked {got.get('date')!r}")

    print(f"\n{'ALL CHECKS PASSED' if not c.failed else str(c.failed) + ' CHECK(S) FAILED'}")
    client.close()
    return 1 if c.failed else 0


if __name__ == "__main__":
    sys.exit(main())
