# Findings

> **STATUS: partial.** Sections 1–3 are complete — they are findings about the
> problem and about the harness, and they do not depend on live runs. Sections 4–6
> are the ablation results and are **pending execution against a live Retell
> account**; their tables are stubbed with the exact shape they will take. Nothing
> here is filled in from the synthetic fixture.
>
> This file will lie about nothing. Where a number is missing, it says so.

---

## 1. The premise needed correcting first

The project started from "Retell's 2026 vision describes AI workers acting as QA
analysts, and that layer doesn't exist yet."

That is not accurate, and checking it first changed the design. Retell ships
[LLM Simulation Testing and Batch Testing](https://docs.retellai.com/test/llm-simulation-testing)
today. It works. Its properties, from their own documentation:

- **Text-only.** "It runs as a text conversation." No audio path at all.
- **One LLM verdict per run.** All success criteria are "judged together in a single
  pass against the transcript" — you get pass/fail for the whole run, not per-slot.
- **Non-deterministic, and they say so.** "Rerun a batch before you trust a single
  failure," because both the simulated caller and the grader are LLMs.

So the gap is narrower and more specific than "there's nothing there":

| | Retell native | this harness |
|---|---|---|
| channel | text only | text **and** real WebRTC audio |
| primary verdict | LLM judge | deterministic rules |
| granularity | one verdict per run | per-slot, with the captured value |
| reproducible | no (stated) | yes |
| caller | LLM-improvised | fixed WAV fixtures, byte-identical every run |
| hallucination check | judge's opinion | set difference against the tool server's log |

**Finding:** the interesting contribution is not "build a QA layer." It is "make the
primary score reproducible, and reach the failure modes text cannot." That reframing
is what produced the 2×2 design (prompt arm × channel) instead of a single comparison.

---

## 2. Three design decisions that made determinism possible

These are the load-bearing choices. Each removes a place where a judgment call
would otherwise have crept into the primary score.

**Scenarios pin a reference date.** "Next Tuesday" is ambiguous relative to *today*
and fixed relative to a declared `reference_date`. Without this, the same scenario
silently changes meaning depending on when it runs, and the expected answer drifts.

**The agent's tool-call arguments are the captured slots.** `book_appointment`
receives structured data. We never parse the agent's prose to infer what it heard —
which would have meant writing a second, worse NLU and then trusting it to grade the
first one.

**The tool server is the oracle.** Giving the agent a real `check_availability`
webhook costs a tunnel and some setup. In exchange, the server's own response log
records exactly which times were offered, so "did the agent invent an availability?"
becomes a set difference over canonical times — a fact. Without the tool there is no
ground truth and the only option is to ask a model to guess.

**A fourth, smaller one:** where a value genuinely cannot be resolved, the scorer
*refuses* rather than guessing. `normalize_time("three")` returns UNPARSEABLE with a
reason, instead of assuming pm. Manufacturing agreement is the exact failure being
hunted, and a scorer that does it is worse than no scorer.

### Ambiguity is reported, not collapsed

"Next Tuesday" has two defensible readings and real callers use both. The harness
commits to one (the following calendar week) so it can be deterministic, but it also
computes the competing reading and scores a match against it as
`AMBIGUOUS_ALTERNATE`, not `WRONG`. It counts as a miss in the strict headline number
and is listed separately in the report.

"The agent picked the other reasonable interpretation" and "the agent got the date
wrong" are different findings. Collapsing them into one percentage destroys the
information you actually wanted.

---

## 3. Findings that do not flatter the work

Four bugs, all mine, all in the component whose entire selling point is that it is
trustworthy. Full detail in [notes.md](notes.md).

### 3.1 The scorer rejected the exact format its own tool schema demanded

The worst one, and the most instructive.

`book_appointment`'s schema says *"Appointment time as 24-hour HH:MM."* The agent
complies and sends `"09:00"`. `normalize_time` then refused it — hour 9, no am/pm
marker, and the rule was "never guess the meridiem."

Both halves were individually correct. "Never guess" is right for **speech**, where
"three" genuinely could be either. It is wrong for a **structured field whose schema
declares 24-hour**, where `09:00` is unambiguous by contract. The result: every
correct morning appointment scored UNPARSEABLE.

**I would not have caught this from a real run.** I would have seen a pile of
UNPARSEABLE time slots, concluded the agent was bad at times, and written that up as
a finding *about the agent*. It was caught only because a fabricated fixture with
known-correct answers made the discrepancy visible. Build the fake-data path before
spending money on real calls.

### 3.2 A silent, plausible mis-parse: `"noon" in s` matches "after**noon**"

`normalize_time("4 in the afternoon")` returned `12:00`. A substring check for "noon"
fires on "afternoon", and the early return meant the "4" was never examined.

Nastier than an obvious crash, because 12:00 is a perfectly plausible clinic
appointment. Any scenario where a caller said "afternoon" would have been scored
against the wrong value, and the report would have confidently named the wrong slot.

### 3.3 The obvious test would have passed and shipped the bug

`normalize_date("next Tuesday", ...)` resolved to 10 days out when the reference date
was a Saturday. The docstring promised "the weekday in the following calendar week";
the code computed "next occurrence, then add 7 if it's under a week away." Those
agree when the reference day is early in the week and diverge badly later in it.

Caught by re-reading my own docstring against the implementation — not by a test. The
test I would naturally have written (from a Monday) passes on the buggy code. The
parametrised Mon/Sat/Sun test exists only *because* the bug sent me looking.

### 3.4 An open limitation I have not solved

`check_invented_availability` suppresses utterances matching an opening-hours pattern,
because "we're open 9am to 5pm" otherwise reads as two invented slots. The suppression
is blunt: an agent saying *"I'm open at 2pm"* — meaning the slot, not the clinic — is
now invisible to the check.

I don't have a fix that stays deterministic. **This check under-reports**, and should
be read that way rather than as a clean signal.

---

## 4. Which failures the hardened prompt fixed — PENDING

> Requires live runs. Table shape below; `make run-full` then `make report`.

| persona | naive/text | hardened/text | naive/voice | hardened/voice | reading |
|---|---|---|---|---|---|
| barge_in | n/a | n/a | — | — | |
| background_noise | n/a | n/a | — | — | |
| mind_change | — | — | — | — | |
| ambiguous_date | — | — | — | — | |
| long_silence | n/a | n/a | — | — | |
| out_of_scope | — | — | — | — | |
| self_correction | — | — | — | — | |
| compound_utterance | — | — | — | — | |

The classification this table is designed to produce:

- **Fixable by prompt** — fails naive, passes hardened, in *both* channels.
- **Structural to voice** — passes text in both arms, fails voice in both arms. The
  prompt is not the lever; this needs a config knob, a different model, or is
  inherent to the audio pipeline.
- **Fixed by prompt, voice only** — a voice-specific failure the prompt did reach.
- **Nothing fixed it** — fails everywhere in both arms.

## 5. LLM judge vs. deterministic scorer — PENDING

> The judge grades two checks the rules already cover (`confirmed_before_booking`,
> `invented_availability`), so agreement is measurable rather than asserted.
> Reported automatically by `harness.report`.

- agreement rate: **—**
- disagreements: **—**
- of the disagreements, how many were the judge being wrong: **—**

## 6. Latency — PENDING

> Voice only. Text-channel timings are API round-trip and are *not* conversational
> latency; they are excluded rather than reported as if comparable.

---

## Caveats — read these before quoting any number above

**Scale.** Three repeats per cell. Enough to see a large effect, not enough for a
small one. No confidence intervals are reported because none would be meaningful at
n=3. Treat every number as directional.

**One model family.** A single pinned model (`gpt-4.1-mini`, temperature 0) for both
arms. Findings about what a prompt can fix may not transfer to a different model, and
temperature 0 suppresses run-to-run variance that a production deployment would have.

**Web calls, not telephony.** Wideband Opus over WebRTC. No 8 kHz μ-law carrier codec,
no PSTN jitter or packet loss, no carrier echo, no DTMF. An agent that passes here can
still fail on a real phone line. This is the single biggest gap between this harness
and production QA, and it is a deliberate cost trade.

**Scripted callers, not humans.** Fixed TTS fixtures, byte-identical every run. That
buys reproducibility and costs realism: one synthetic voice, consistent prosody, no
accents, no real disfluency. Real callers fail in ways this cannot generate. The
noise beds are *procedurally generated* — filtered pink and brown noise, not
recordings of real cafes or real overlapping speech. They degrade the signal
reproducibly; they do not reproduce how real room noise defeats real STT.

**Open-loop barge-in timing.** Interruptions fire a fixed number of milliseconds after
the agent starts speaking. A real interrupter is cued by *meaning* — they cut in when
they've heard enough. Timing-based barge-in tests whether the agent yields the floor,
not whether it yields at a natural point.

**Possible overfitting of the hardened prompt.** It was written against general voice
failure modes, and I deliberately did not consult scenario expectations while writing
it. Two scenarios (`s07`, `s08`) are marked held-out. That is a **weak** control: I
wrote both the prompt and the scenarios, and could not fully unsee one while writing
the other. Read the hardened arm's margin as an optimistic bound.

**The text channel is not a perfect control.** It shares the same Retell LLM object —
same prompt, tools, model, temperature — which is cleaner than expected. But
everything downstream differs: no STT, no TTS, no turn-taking, no clock. A failure
appearing only in voice implicates *the audio pipeline*, which is a broader category
than "voice reasoning."

**Single account, single region, one point in time.** No claim about variance across
Retell infrastructure, time of day, or platform versions.
