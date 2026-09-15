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

## 4. Text ablation results — the hardened prompt did not help

42 runs, 7 scenarios x 2 arms x 3 repeats, text channel. Raw transcripts committed
under `runs/20260915T165252Z_text-ablation/`. $0.42.

| channel | naive | hardened |
|---|---|---|
| text | **20/21 (95%)** | **20/21 (95%)** |

A dead tie. Not "hardened won narrowly" — literally the same number, arrived at by
failing different things.

| persona | naive | hardened |
|---|---|---|
| ambiguous_date | 5/6 (83%) | 6/6 (100%) |
| self_correction | 3/3 (100%) | 2/3 (67%) |
| happy_path, mind_change, out_of_scope, compound_utterance | 100% | 100% |

The hardened prompt won one run on ambiguous dates and lost one on self-correction.
Net zero.

### The single naive failure is a real bug worth reading

`s06/naive#0` booked 13:30 when the caller asked for 2 PM. The tool had returned
`14:00` as available. The agent said:

> "We don't have a 2:00 PM slot, but we do have 1:30 PM or 2:00 PM is not available.
> Would you like to choose 1:30 PM or 3:00 PM instead?"

It denied an available slot, contradicted itself mid-sentence, and booked the wrong
time. The `time` slot was correctly scored WRONG — but note that the *invention*
check passed, because inventing and wrongly-denying are different failures and only
the first was implemented (see 3.x). This one run is what prompted the new
`denied_available_slot` check.

### The single hardened failure — and why I am not telling a story about it

`s09/hardened#2` dropped the optional `phone` field. The tempting narrative: the
hardened prompt's explicit "**Four fields**, all required" table crowded out a fifth
field the tool schema offered — being more specific made it less complete.

That mechanism is plausible. The evidence is one run. Hardened captured the phone in
the other two; naive captured it in all three. **n=3 cannot distinguish that from
noise**, and writing it up as a finding would be exactly the failure mode this
project is about. Recorded as a hypothesis worth testing at higher n, not a result.

### Most of the difference I expected was my own bugs

Before the harness fixes, the naive arm appeared to fail badly — hallucinated
availability, mangled dates, stalled conversations. Every one of those turned out to
be a defect in the harness (3.1, 3.2, 3.3). With those fixed, on this scenario set,
**a ten-minute first-draft prompt performs identically to a carefully hardened one.**

That is the central negative result, and it is worth more than a clean win would have
been: the measurable gap between a naive and a hardened prompt, at least over text
with `gpt-4.1-mini` at temperature 0, was smaller than the measurement error of my
own instrument.

### What the hardened prompt did cost

| arm | runs needing a caller nudge | mean nudges |
|---|---|---|
| naive | 1/21 | 0.05 |
| hardened | 4/21 | 0.19 |

Roughly four times as many runs where the agent was still asking questions after the
script ran out. Same pass rate, more conversational turns to get there. On a real
phone line that is caller patience and per-minute cost spent for no measured accuracy
gain.

## 5. LLM judge vs. deterministic scorer — the judge was perfect

The judge (`claude-sonnet-5`) graded two checks the rules also cover, on all 42 runs:

- **agreed: 74/74 (100%)**
- disagreed: 0, "unclear": 0

This cuts against the premise I built the project on. I expected to demonstrate judge
unreliability and instead measured perfect agreement.

**The honest reading, which is less flattering to the judge than the number suggests:**
this dataset is easy. 40 of 42 runs pass, the conversations are short, and the two
checks have visually obvious answers in the transcript. Agreement on near-uniform
data is cheap — a grader that simply answered "yes, confirmed / no, not invented"
every time would have scored 73/74. The judge was never required to catch a subtle
failure, because there were almost none to catch.

So this is **not** evidence that an LLM judge is reliable for slot correctness. It is
evidence that on this data it was not the bottleneck, and that my assumption it would
visibly disagree was wrong. The determinism argument now rests on the properties it
actually earned — reproducibility, per-slot attribution, free re-scoring of committed
transcripts (§3.x) — rather than on the judge being bad, which I did not show.

Notably, the judge also agreed with the scorer *during the period the scorer was
wrong*: it said "not invented" on runs where the morning-slot bug was live, because
it was reading the transcript correctly and the agent genuinely had not invented
anything. Ground truth was on the judge's side there, not mine.

## 6. Latency — PENDING

> Voice only. Text-channel timings are API round-trip and are *not* conversational
> latency; they are excluded rather than reported as if comparable.

---

## Caveats — read these before quoting any number above

**Scale.** Three repeats per cell. Enough to see a large effect, not enough for a
small one. No confidence intervals are reported because none would be meaningful at
n=3. Treat every number as directional.

**The prompt is not the only instruction channel — and the arms share the other one.**
Both arms use an identical tool schema, and JSON Schema property descriptions turn
out to function as directives. `s09` captured a phone number correctly, with the
caller's correction applied, even though *neither prompt asks the agent to collect
one* — the `book_appointment` schema simply declares `phone` as "Callback number, if
given." and that was sufficient.

This bounds what a prompt-only ablation can explain. Some share of the behaviour in
both arms is coming from the tool definitions they have in common, not from either
prompt, and this design cannot separate the two. A fuller experiment would vary the
schema as a third axis. Read every "the prompt fixed X" claim as "the prompt fixed X,
given this tool schema."

**One model family.** A single pinned model (`gpt-4.1-mini`, temperature 0) for both
arms. Findings about what a prompt can fix may not transfer to a different model, and
temperature 0 suppresses run-to-run variance that a production deployment would have.

**Web calls, not telephony.** Wideband Opus over WebRTC. No 8 kHz μ-law carrier codec,
no PSTN jitter or packet loss, no carrier echo, no DTMF. An agent that passes here can
still fail on a real phone line. This is the single biggest gap between this harness
and production QA, and it is a deliberate cost trade.

**Determinism stops at the microphone.** The caller audio is byte-identical across
runs by construction, and the scorer is deterministic — but STT is not. The same
committed WAV of "David Okonkwo. O-K-O-N-K-W-O." transcribed as `David O'Connell`
on two runs and `David O'Conk Co` on a third. So a deterministic scorer plus a
deterministic caller does **not** produce a deterministic experiment when the channel
between them is stochastic. Voice results need higher n than text results to mean the
same thing — which is the opposite of what the budget allows, and why the voice arm
runs at n=2 while text runs at n=3.

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
