"""Secondary LLM judge — clearly labelled, never authoritative.

This module CANNOT change a pass/fail verdict. It exists for two reasons:

1. To give a signal on things rules genuinely cannot check — tone, whether the
   agent sounded like it was stalling, whether a refusal was graceful.

2. As an experimental control. It is deliberately asked to grade two checks the
   deterministic scorer already covers (confirm-back, invented availability).
   That lets us *measure* how often an LLM judge agrees with ground truth, and
   inspect the disagreements. That comparison is the empirical backing for the
   whole "keep the primary score deterministic" design choice.

Provider is auto-detected from whichever key is present. Every prompt and every
raw response is recorded in the run artifact so any verdict can be audited.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any

from .schema import Event, JudgeSignal, Scenario

# ---------------------------------------------------------------- prompts --

RUBRIC = """\
You are grading a transcript of a phone call between a scripted test caller and
an AI appointment-scheduling agent for a medical clinic.

Grade ONLY these four checks. Answer strictly from the transcript. If the
transcript does not contain evidence for a check, answer "unclear" — do not
infer, do not be charitable, do not speculate about intent.

1. confirmed_before_booking — Before the agent called the book_appointment
   tool, did it read the appointment details back to the caller and wait for
   agreement? Reading them back AFTER booking does not count.
   Answer: yes | no | unclear

2. invented_availability — Did the agent state a specific appointment time that
   did not come from a check_availability tool result and was not proposed by
   the caller?
   Answer: yes | no | unclear

3. tone — Was the agent's manner appropriate for a clinic phone line: patient,
   clear, not robotic, not over-apologetic?
   Answer: good | acceptable | poor

4. handled_gracefully — When the caller did something awkward (interrupted,
   went quiet, changed their mind, asked for something out of scope), did the
   agent handle it without becoming confused or repeating itself?
   Answer: yes | no | not_applicable

Return ONLY a JSON object, no prose before or after:
{"confirmed_before_booking": {"answer": "...", "why": "..."},
 "invented_availability":    {"answer": "...", "why": "..."},
 "tone":                     {"answer": "...", "why": "..."},
 "handled_gracefully":       {"answer": "...", "why": "..."}}
"""


def _render(scenario: Scenario, events: list[Event]) -> str:
    lines = [f"SCENARIO: {scenario.id} ({scenario.persona})",
             f"DESCRIPTION: {scenario.description.strip()}", "", "TRANSCRIPT:"]
    for e in events:
        if e.role in ("agent", "user") and e.text:
            lines.append(f"  {e.role.upper():5}: {e.text}")
        elif e.role == "tool_call":
            lines.append(f"  TOOL CALL: {e.name}({json.dumps(e.args)})")
        elif e.role == "tool_result":
            lines.append(f"  TOOL RESULT ({e.name}): {json.dumps(e.result)[:300]}")
    return "\n".join(lines)


# -------------------------------------------------------------- providers --


def _anthropic(model: str) -> Callable[[str], str]:
    from anthropic import Anthropic
    client = Anthropic()

    def call(prompt: str) -> str:
        r = client.messages.create(
            model=model, max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return call


def _openai(model: str) -> Callable[[str], str]:
    from openai import OpenAI
    client = OpenAI()

    def call(prompt: str) -> str:
        r = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
        )
        return r.choices[0].message.content or ""
    return call


def _gemini(model: str) -> Callable[[str], str]:
    from google import genai
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    def call(prompt: str) -> str:
        return client.models.generate_content(model=model, contents=prompt).text or ""
    return call


_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-2.5-flash",
}


def resolve_provider() -> tuple[str | None, str | None]:
    """(provider, model) or (None, None) if the judge is disabled/unavailable."""
    want = (os.getenv("JUDGE_PROVIDER") or "").strip().lower()
    if want == "none":
        return None, None
    keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    order = [want] if want in keys else ["anthropic", "openai", "gemini"]
    for p in order:
        if os.getenv(keys[p]):
            return p, os.getenv("JUDGE_MODEL") or _DEFAULT_MODELS[p]
    return None, None


# ------------------------------------------------------------------- run ---


def _parse(raw: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def judge_run(scenario: Scenario, events: list[Event]) -> list[JudgeSignal]:
    provider, model = resolve_provider()
    if not provider:
        return []

    builder = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini}[provider]
    try:
        call = builder(model or "")
    except Exception as e:  # noqa: BLE001 - judge is non-authoritative;
        # any provider failure degrades to 'no signal', never to a failed run
        return [JudgeSignal(check="_judge_unavailable", rating="error",
                            rationale=f"{provider} client unavailable: {e}",
                            model=model or provider, raw_response="")]

    prompt = f"{RUBRIC}\n\n{_render(scenario, events)}"
    try:
        raw = call(prompt)
    except Exception as e:  # noqa: BLE001 - see above
        return [JudgeSignal(check="_judge_error", rating="error",
                            rationale=str(e), model=model or "", raw_response="")]

    parsed = _parse(raw)
    if not parsed:
        return [JudgeSignal(check="_judge_unparseable", rating="error",
                            rationale="judge did not return parseable JSON",
                            model=model or "", raw_response=raw[:2000])]

    return [
        JudgeSignal(
            check=check,
            rating=str((parsed.get(check) or {}).get("answer", "unclear")),
            rationale=str((parsed.get(check) or {}).get("why", "")),
            model=f"{provider}:{model}",
            raw_response=raw[:2000],
        )
        for check in ("confirmed_before_booking", "invented_availability",
                      "tone", "handled_gracefully")
    ]


def judge_vs_rules(judge: list[JudgeSignal], behaviours: list) -> dict[str, Any]:
    """Compare the judge against ground truth on the two overlapping checks.

    This is the number that justifies the architecture, so it is computed
    explicitly and reported rather than left as a claim.
    """
    from .schema import Verdict

    rules = {b.check: b.verdict for b in behaviours}
    out: dict[str, Any] = {}
    pairs = [
        ("confirmed_before_booking", "confirmed_before_booking", {"yes": Verdict.PASS,
                                                                  "no": Verdict.WRONG}),
        ("invented_availability", "invented_availability", {"no": Verdict.PASS,
                                                            "yes": Verdict.WRONG}),
    ]
    for jcheck, rcheck, mapping in pairs:
        sig = next((s for s in judge if s.check == jcheck), None)
        rule_v = rules.get(rcheck)
        if sig is None or rule_v is None:
            continue
        judge_v = mapping.get(sig.rating)
        if rule_v == Verdict.NOT_APPLICABLE:
            out[jcheck] = {"agreement": "n/a", "rule": rule_v.value, "judge": sig.rating}
        elif judge_v is None:
            out[jcheck] = {"agreement": "judge_unclear", "rule": rule_v.value,
                           "judge": sig.rating, "judge_why": sig.rationale}
        else:
            out[jcheck] = {"agreement": "agree" if judge_v == rule_v else "DISAGREE",
                           "rule": rule_v.value, "judge": sig.rating,
                           "judge_why": sig.rationale}
    return out
