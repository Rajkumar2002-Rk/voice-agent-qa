"""Classify each persona as prompt-fixable or structural to voice.

This is the question the experiment exists to answer, so the reasoning is
mechanical and inspectable rather than a judgement call written up afterwards.

The 2x2 (prompt arm x channel) gives four pass rates per persona, and the
pattern across them is what carries the meaning:

    text naive  text hard   voice naive  voice hard   -> reading
    ----------  ---------   -----------  ----------
    fail        pass        fail         pass            FIXED_BY_PROMPT
    pass        pass        fail         fail            STRUCTURAL_TO_VOICE
    pass        pass        fail         pass            PROMPT_FIXED_VOICE_ONLY
    fail        fail        fail         fail            NOTHING_FIXED
    pass        pass        pass         pass            NOT_A_PROBLEM

A persona that only fails in voice regardless of prompt is not something a
prompt can reach: the lever is elsewhere (endpointing config, model, or the
audio pipeline itself).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .schema import RunResult

# A cell counts as "passing" only if it passes comfortably. With n=2..3 a single
# flake would otherwise flip a persona's classification.
PASS_THRESHOLD = 0.67


@dataclass
class PersonaVerdict:
    persona: str
    rates: dict[tuple[str, str], float | None]   # (arm, channel) -> pass rate
    label: str
    reasoning: str


def _rate(rs: list[RunResult]) -> float | None:
    return sum(r.passed for r in rs) / len(rs) if rs else None


def classify(results: list[RunResult]) -> list[PersonaVerdict]:
    by: dict[str, list[RunResult]] = defaultdict(list)
    for r in results:
        by[r.persona].append(r)

    out: list[PersonaVerdict] = []
    for persona, rs in sorted(by.items()):
        rates = {
            (arm, ch): _rate([r for r in rs if r.arm == arm and r.channel == ch])
            for arm in ("naive", "hardened")
            for ch in ("text", "voice")
        }
        tn, th = rates[("naive", "text")], rates[("hardened", "text")]
        vn, vh = rates[("naive", "voice")], rates[("hardened", "voice")]

        def ok(x: float | None) -> bool | None:
            return None if x is None else x >= PASS_THRESHOLD

        tn_, th_, vn_, vh_ = ok(tn), ok(th), ok(vn), ok(vh)

        if vn_ is None and vh_ is None:
            label = "TEXT_ONLY_EVIDENCE"
            why = ("no voice runs for this persona, so nothing can be said about "
                   "whether its failures are structural to voice")
        elif tn_ is None and th_ is None:
            if vn_ and vh_:
                label, why = "NOT_A_PROBLEM", "passes in voice under both prompts"
            elif not vn_ and vh_:
                label, why = "FIXED_BY_PROMPT", ("voice-only persona: fails naive, "
                                                 "passes hardened. No text control "
                                                 "exists, so 'structural' cannot be "
                                                 "ruled out — only that the prompt "
                                                 "moved it")
            elif not vn_ and not vh_:
                label, why = "NOTHING_FIXED", "fails in voice under both prompts"
            else:
                label, why = "MIXED", "hardened did worse than naive in voice"
        elif all(v for v in (tn_, th_, vn_, vh_)):
            label, why = "NOT_A_PROBLEM", "passes everywhere under both prompts"
        elif tn_ and th_ and not vn_ and not vh_:
            label, why = "STRUCTURAL_TO_VOICE", (
                "passes in text under both prompts and fails in voice under both — "
                "the prompt is not the lever")
        elif tn_ and th_ and not vn_ and vh_:
            label, why = "PROMPT_FIXED_VOICE_ONLY", (
                "text was never broken; voice was, and the hardened prompt reached it")
        elif not tn_ and th_ and not vn_ and vh_:
            label, why = "FIXED_BY_PROMPT", (
                "fails naive and passes hardened in BOTH channels — a reasoning/"
                "instruction problem, not a voice problem")
        elif not tn_ and not th_ and not vn_ and not vh_:
            label, why = "NOTHING_FIXED", "fails everywhere under both prompts"
        elif not th_ and tn_ or (vh_ is False and vn_ is True):
            label, why = "REGRESSED", "the hardened prompt made this persona worse"
        else:
            label, why = "MIXED", "no clean pattern across the 2x2"

        out.append(PersonaVerdict(persona, rates, label, why))
    return out


def render(verdicts: list[PersonaVerdict]) -> str:
    def cell(v: float | None) -> str:
        return "—" if v is None else f"{100 * v:.0f}%"

    blurb = (
        "Mechanical classification from the 2x2. A cell counts as passing at "
        f">={100 * PASS_THRESHOLD:.0f}%, so one flake cannot flip a verdict.\n"
    )
    L = ["## What the prompt could and could not fix\n", blurb,
         "| persona | naive/text | hard/text | naive/voice | hard/voice | verdict |",
         "|---|---|---|---|---|---|"]
    for v in verdicts:
        L.append(
            f"| {v.persona} | {cell(v.rates[('naive','text')])} | "
            f"{cell(v.rates[('hardened','text')])} | "
            f"{cell(v.rates[('naive','voice')])} | "
            f"{cell(v.rates[('hardened','voice')])} | **{v.label}** |"
        )
    L.append("")
    for v in verdicts:
        L.append(f"- **{v.persona}** — {v.label}: {v.reasoning}")
    L.append("")
    return "\n".join(L)
