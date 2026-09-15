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

Nine bugs so far, all mine, and the most serious ones were in the component whose
entire selling point is that it can be trusted. Full detail in [notes.md](notes.md);
the three that matter are below, followed by the pattern they form — which is the
most useful thing this project produced.

### 3.1 The scorer accused the agent of inventing times it had read off the tool

The pilot ablation flagged `s01/naive#2` for stating three appointment times "that
neither the check_availability tool returned nor the caller proposed". The agent had
said:

> "On Tuesday, September 22nd, we have openings at 9:00 AM, 9:30 AM, 10:00 AM,
> 1:30 PM, 3:00 PM, and 4:00 PM."

The clinic server's actual availability: `09:00, 09:30, 10:00, 13:30, 15:00, 16:00`.
**Identical.** The agent was exactly right and the scorer called it a liar.

`check_invented_availability` parsed the tool's own returned slots using rules meant
for *speech*, where a bare `"09:00"` is ambiguous and gets refused. Every morning
slot silently vanished from the ground-truth set; only the afternoon ones survived.
The check was therefore biased toward reporting hallucination **specifically on
morning appointments**.

Had I not opened a transcript, I would have published *"the naive prompt hallucinates
availability roughly 30% of the time"* — a clean, plausible, quotable, entirely
manufactured finding. It would have been perfectly reproducible, because
**reproducible and correct are different properties**. A deterministic scorer that is
wrong is wrong the same way every time, which makes the error look like a signal.

### 3.2 The agent never knew what day it was

The second ablation attempt died at run 7. `s04_mind_change` scored 0/4, and the
tool log said why:

```
USER   I'd like to book for Tuesday the twenty-second.
TOOL   check_availability({"date": "2024-08-22"})
```

August **2024**. The scenario pins 2026-09-14 as "today", so the expected date was
2026-09-22. Nothing in the system had ever told the agent the current date — Retell
does not inject one, the prompts did not mention one, and I passed no dynamic
variables. With no anchor the model used its training-era notion of "now".

The downstream effects were completely convincing as agent failures: the clinic
correctly reported "Friday the 25th" as closed, because 2024-08-25 is a *Sunday*; the
agent looped asking for an exact date because nothing it had cohered. Three scenarios
turn on relative dates and every other scenario touches one.

Worse, I had already *mis-diagnosed this once*. Earlier, the hardened agent kept
asking the caller to confirm the year, and I read that as my disambiguation rule
over-firing into pedantry — so I patched the prompt to say "assume the current year."
The agent was asking because **it genuinely did not know the year**. It was behaving
reasonably given its context, and I suppressed the symptom and moved on. The real bug
survived two more runs.

### 3.3 The harness quietly favoured the arm that asked fewer questions

The scripted caller is open-loop: it reads its lines regardless of what the agent
asks. So when the hardened agent asked an unanticipated question, the caller replied
with the next scripted line — a non-answer — and the agent asked again until the
script ran out and the run failed at 0/4.

That is a structural bias toward **whichever arm asks fewer clarifying questions**,
which is not the same thing as the better arm. An agent that carefully confirms an
ambiguous date was being penalised for it.

Mitigated with a bounded follow-up (the caller offers "Yes, that's correct." up to
three times once the script is exhausted), with `followups_used` recorded per run and
reported — so asking more questions now costs visible efficiency rather than a silent
failure. It is a mitigation, not a fix: a real caller answers the actual question.

### 3.4 The pattern, which is the real finding

Three separate times, a defect of mine arrived wearing the costume of an agent
failure — and each time it came with a specific, well-formatted, entirely plausible
accusation: *the agent hallucinated three times*, *the agent can't handle a date
change*, *the agent asks pointless questions*.

The uncomfortable part is that **the harness's output quality was what made the
errors credible**. A verdict that names the slot, shows the captured value, and cites
the rule that fired reads as authoritative. That authority is exactly what the
project set out to build, and it is what made every one of these bugs land as a
finding instead of as a suspicion.

Three things follow, and they are what I would actually tell a team building this:

1. **When the harness and the agent disagree, the harness is a serious suspect.**
   Not the default explanation, but never below the agent in the ordering.
2. **Read individual transcripts before believing any aggregate.** Every bug here was
   found by opening one conversation. None were visible in a pass-rate table — they
   all *were* the pass-rate table.
3. **Build the fake-data path before spending money on real calls.** The synthetic
   fixture, written only to test the report generator, caught a scorer bug on its
   first render because it was the only place I knew the correct answer in advance.

The tooling response was `make preflight`: one $0.01 conversation that asserts the
live prompt matches the file on disk, the agent actually called its tool, the clinic
server actually received the webhook, and the date the agent resolved matches the
scenario's reference date. Every check exists because its absence already cost a
batch.

### 3.5 An open limitation, not solved

`check_invented_availability` suppresses utterances matching an opening-hours pattern,
because "we're open 9am to 5pm" otherwise reads as two invented slots. The suppression
is blunt: an agent saying *"I'm open at 2pm"* — meaning the slot — is now invisible to
it. No deterministic fix found. **This check under-reports**, and should be read that
way rather than as a clean signal.

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
