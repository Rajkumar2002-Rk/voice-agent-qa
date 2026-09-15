# Lab notebook

Running log, appended as work happens. The findings writeup is distilled from this;
this file keeps the stuff that would otherwise get tidied out of memory — including
the mistakes.

---

## Day 1 — design decisions

### D1. Retell already ships a QA layer. The gap is narrower than assumed.

Before writing anything I checked what Retell already has. It has
[LLM Simulation Testing + Batch Testing](https://docs.retellai.com/test/llm-simulation-testing).
It is real and it works. Its properties:

- **text-only** — their docs: "it runs as a text conversation"
- **one LLM verdict per run** — all success criteria "judged together in a single
  pass against the transcript", so you get pass/fail for the whole run, not per-slot
- **explicitly non-deterministic** — their own docs say "rerun a batch before you
  trust a single failure", because both the simulated user and the grader are LLMs

So the honest framing of this project is *not* "Retell has no QA layer." It is:
the layer exists, it's text-only and non-reproducible, and the interesting question
is what you get when you make the primary score deterministic and add the audio
failure modes text can't reach.

That reframing made the project better. It forced the 2x2 (prompt arm × channel)
rather than a single-axis comparison.

### D2. Why the agent gets a real tool server

Retell custom tools are webhooks to a URL you own. That's mildly annoying to set up
(needs a tunnel) and I nearly skipped it by making the agent purely conversational.

Skipping it would have been a mistake. With a real `check_availability` endpoint, the
server's own response log is **ground truth for what was actually offered**. So
"did the agent invent an appointment slot?" becomes a set-difference over canonical
times — a fact — instead of a question for an LLM judge. The tool server is the
oracle that makes the hallucination check deterministic.

It does double duty: `book_appointment`'s arguments *are* the captured slots. No
parsing the agent's prose to guess what it heard. The agent tells us, in structured
form, what it thinks it captured.

### D3. Committing to one reading of "next Tuesday"

"Next Tuesday" genuinely has two defensible readings, and real callers use both:
the Tuesday of the following calendar week, or simply the next Tuesday to occur.

A scorer has to commit to one or it isn't deterministic. We commit to
*following calendar week* — but we also compute the competing reading and score a
match against it as `AMBIGUOUS_ALTERNATE` rather than `WRONG`. That distinction
matters: "the agent picked the other reasonable interpretation" and "the agent got
the date wrong" are different findings and shouldn't collapse into one number.

Related, and deliberate: `normalize_time` **refuses** to resolve a bare "3" with no
am/pm. Guessing pm would manufacture agreement, which is the exact failure this
harness exists to detect. It returns UNPARSEABLE and says why.

---

## Day 1 — bugs in my own harness (running list)

These are logged as they're found, for the "does not flatter the work" section.
Two of three were caught only because the test suite existed; the first was caught
by reading my own docstring back.

### B1. `next Tuesday` from a Saturday resolved 10 days out

The docstring promised "the weekday in the following calendar week." The code
computed "next occurrence, then add 7 if it's less than a week away." Those agree
when the reference day is early in the week and diverge badly later in it: from
Sat 19 Sep, the rule says Tue 22 Sep (3 days), the code said Tue 29 Sep (10 days).

Caught by writing the docstring first and then re-reading it against the
implementation — not by a test. The test came after, and now covers Mon/Sat/Sun
starting days. **Lesson: the parametrised test only existed because the bug made me
go looking for the edge.** If I'd written the obvious test (from a Monday) it would
have passed and shipped the bug.

### B2. `"noon" in s` matched "after**noon**"

`normalize_time("4 in the afternoon")` returned `12:00`. A plain substring check for
"noon" fires on "afternoon", and the early-return meant the "4" and the pm marker
were never even looked at.

This one is nastier than B1 because it fails *silently and plausibly* — 12:00 is a
perfectly reasonable-looking clinic appointment time. Any scenario where a caller
said "afternoon" would have been scored against the wrong expected value, and the
report would have confidently told me which slot was wrong. Fixed with `\bnoon\b`;
regression test added.

### B3. `list.index()` on Pydantic models matches by value, not identity

`check_confirmed_before_booking` located the first `book_appointment` call with
`events.index(first_book)`. Pydantic models compare by field value, so if an agent
called `book_appointment` twice with identical arguments — which is exactly what a
retry or a double-commit looks like — `.index()` returns the *first* one regardless
of which we meant. Replaced with an explicit enumerate scan.

Caught by reading, not by a test. Noting it because the scenario that would have
exposed it (double-booking) is one I hadn't thought to write yet.

### B4. The scorer rejected the exact format its own tool schema demanded

Found by the synthetic-run fixture, which I wrote only to get test coverage on the
report generator. On first render, 30 of 102 runs showed `time: UNPARSEABLE`.

The cause: `book_appointment`'s schema says *"Appointment time as 24-hour HH:MM."*
The agent complies and sends `"09:00"`. `normalize_time` then refuses it, because
hour 9 is ≤ 12 with no am/pm marker, and the rule was "never guess the meridiem."

Both halves were individually correct and together they were wrong. "Never guess"
is right for **speech** — "three" genuinely could be either. It's wrong for a
**structured field whose schema declares 24-hour**, where `09:00` is unambiguous by
contract. Every correct morning appointment was being scored UNPARSEABLE.

Fix: `normalize_time(raw, context=...)`. `spoken` keeps the strict behaviour and is
what `extract_times` uses on transcript text. `structured` reads a colon form as
24-hour and is used for values that came out of tool arguments. A structured value
with *no* colon (`"9"`) is still refused — that's the agent ignoring the schema,
which is a real failure worth surfacing.

Worth recording for the writeup: **I would not have caught this from a real run.**
I'd have seen a pile of UNPARSEABLE time slots, concluded the agent was bad at
times, and written it up as a finding about the agent. The fixture was fake data
with a known-correct answer, which is the only reason the discrepancy was visible.
That is an argument for building the fake-data path *before* spending money on real
calls, and it generalises past this project.

### B5. (open) Known false-positive in the hallucination check

`check_invented_availability` suppresses any utterance matching an opening-hours
pattern (`open`, `hours`, `between`, `from X to Y`). Without that, "we're open
9am to 5pm" reads as two invented slots.

The suppression is a blunt instrument: an agent that says *"I'm open at 2pm"* —
meaning the slot, not the clinic — is now invisible to the check. I don't have a
clean fix that stays deterministic. Logged as a limitation rather than pretended
away; it should be read as "this check under-reports" rather than as a clean signal.

### B6. A "fix" that silently patched nothing

Freezing the synthetic fixture's timestamps took three attempts, and the middle one
is the interesting failure.

The fixture stamped `datetime.now(...)`, so `make synthetic` rewrote all 102
artifacts every run and dirtied the git tree. I patched it by string-replacing
`datetime.now(timezone.utc)` — and the patch matched zero lines, because `ruff --fix`
had earlier rewritten that call to `datetime.now(UTC)`. The constant `FROZEN_TS` got
defined and never referenced. Nothing errored. I committed it, claimed it was fixed,
and only caught it because I re-ran the check instead of trusting the edit.

Two lessons, both general:

- **A string-replacement patch that matches nothing must fail loudly.** The later fix
  asserts the expected number of replacements and raises otherwise.
- **An autoformatter can invalidate a patch you wrote against the pre-format source.**
  Worth re-reading the file after a lint pass rather than patching from memory.

Fixed properly, with a test that regenerates twice and compares file hashes — so a
silent no-op cannot pass as a fix again.

### B7. dotenv keeps inline comments as part of the value

`.env.example` had `JUDGE_PROVIDER=          # one of: anthropic | openai | ...`.
python-dotenv does not strip trailing comments, so that parsed as the literal string
`"# one of: anthropic | openai | gemini | none  (blank = auto-detect)"`.

It happened to *work* — `resolve_provider` didn't recognise it and fell back to
auto-detect — which is the bad kind of working. Someone writing
`JUDGE_PROVIDER=openai  # my choice` would have had their explicit choice silently
ignored and auto-detect used instead, with no error and no log line.

Fixed on both sides: comments moved onto their own lines in the template, and
`resolve_provider` now strips anything after a `#` defensively. Noting it because
"fails open, silently, into a plausible default" is the same failure shape as B2 and
B4 — and it is the shape a QA harness can least afford.

---

## Day 1 — first live runs

Account created, key working, 4 agents provisioned, tunnel up. Both channels now
verified against a live Retell account.

**Text channel worked on the first attempt.** s01 happy path, 4/4 slots, ~13s, $0.01.
Retell reached the clinic tool webhook twice (`check_availability` then
`book_appointment`), which also confirmed the cloudflared tunnel end-to-end — the
one thing I couldn't verify locally.

**Voice channel took three attempts.** Both failures were mine, and both were the
kind you only find by running it.

### B8. The SDK's UMD bundle has externals nobody documents

First voice run died instantly: `Retell SDK global not found on window`.

Two causes stacked. The global is `retellClientJsSdk` (lowercase r), not
`RetellWebClient` as I'd assumed from the docs' code samples. And more importantly,
the UMD declares **eventemitter3 and livekit-client as externals**:

```js
e((t||self).retellClientJsSdk={}, t.eventemitter3, t.livekitClient)
```

It expects both on `window` before it loads, under those exact lowercase names —
which is *not* what either library's own UMD publishes (`EventEmitter3` and
`LivekitClient`). So a single `<script src=retell...>` tag can never work, and no
amount of fixing the global name alone would have helped.

Found by reading the minified bundle, not the docs. Now vendored locally with an
alias shim, so runs don't depend on a CDN mid-call.

### B9. The caller talked over the agent on every single turn

Second voice run connected, ran 27 seconds, cost $0.07, and scored 0/4. The
transcript is the whole story:

```
AGENT  Thanks for calling Lakeside Family Clinic, this is Robin. How can I help?
USER   Hi. I'd like to book an appointment, please.
AGENT  Of
USER   My name is Maria Delgado. Tuesday, the twenty second of September.
USER   Three PM works.
```

The agent got one word out before being buried, then never spoke again.

`waitAgentDone` resolved as soon as the agent had been quiet for 600ms — but the
agent is *already quiet* before it starts replying. With LLM+TTS latency of a second
or more, "hasn't started yet" and "has finished" are indistinguishable unless you
track that it started. So the wait returned immediately, every turn.

Fixed by requiring a complete turn: wait for the agent to **start**, then wait for
quiet. Third run passed 4/4 in 67s.

**Worth noting for the writeup:** the audio path was never the problem. STT
transcribed every caller utterance correctly on the failing run, including
"Maria Delgado" and "the twenty second of September". The synthetic-microphone
approach worked first time; what broke was my own turn-taking logic. That is a
reassuring result for the method and an unflattering one for me.

It also means the barge-in scenarios are testing something real — I have now
accidentally demonstrated what uncontrolled barge-in looks like, and the agent
handled it badly (gave up speaking entirely rather than re-asserting).

### Live latency, first real numbers

Happy path, naive arm, voice: median **1289 ms**, max **2981 ms** across 6 turns.
The max lands on the final confirm-and-book turn, which includes a tool round-trip
through the cloudflared tunnel to a laptop — so some of that is my test rig, not
Retell. Worth separating tool-call turns from plain conversational turns before
quoting any latency number as the agent's.

### B10. My two "confirm-back" checks were measuring different things

The most methodologically serious bug so far, and the judge found it for me on the
very first call I made to it.

I hand-built a fixture where the agent clearly confirms before booking, expecting a
clean agreement. The judge said **no**. My scorer said **PASS**.

The judge was right, and the real problem was worse than a wrong verdict. Compare
the two specs I had written:

- **deterministic check:** an agent utterance before `book_appointment` mentions the
  booked date and time.
- **judge rubric:** the agent "read the appointment details back to the caller **and
  waited for agreement**."

Those are different checks. My fixture had a read-back and no caller reply, so each
was correctly reporting its own definition. Which means **the judge-vs-rules
agreement number — the headline evidence for this project's whole design argument —
would have been measuring the gap between two specs I wrote, not the judge's
reliability.** Every disagreement would have been noise I'd have been tempted to
write up as "see, LLM judges are unreliable."

Fixed by making the deterministic check match its stated meaning: it now requires a
read-back *and* a caller affirmation before the booking, using a declared
affirmation list. Negations are screened first, because "no, that's not right"
contains "right". The judge rubric was reworded to the identical definition.

Also worth saying plainly: the stricter check is the *correct* one. Reading details
back and then booking without waiting for a reply is not confirmation, it's
narration — and it is exactly the failure a clinic would care about.

**Lesson:** when you compare two graders, the comparison is only meaningful if both
are grading the same proposition. I would not have caught this from aggregate
numbers; it took one hand-made example where I was confident of the answer.

### B11. `tts.py` could not see `.env`

`harness/tts.py` never called `load_dotenv()`. `TTS_PROVIDER` and `OPENAI_API_KEY`
were therefore invisible to it, so it fell through to its default provider and
failed with "OPENAI_API_KEY not set" even though the key was sitting in `.env`.

The fixtures on disk stayed as the earlier macOS `say` renders while the manifest
happily reported success, so a run would have used the robotic voice while I
believed it was using OpenAI TTS — a silent confound in the experiment, not just an
inconvenience.

Compounding it, I ran the build piped to `tail`, so the shell reported *tail's*
exit status and the failure looked like a clean exit 0. Two independent things
hiding the same error. Every entrypoint now loads `.env`; the audit is in the commit.

---

## Day 1 — pilot run, stopped after 4 of 42

Started the text ablation and killed it four runs in. Two things surfaced, one a
harness bug and one a genuine result. Both were only visible because I looked at an
individual transcript instead of waiting for the aggregate.

### B12. The hallucination check accused the agent of inventing times it read off the tool

`s01/naive#2` was flagged for stating three times "that neither the
check_availability tool returned nor the caller proposed". The agent had said:

> "On Tuesday, September 22nd, we have openings at 9:00 AM, 9:30 AM, 10:00 AM,
> 1:30 PM, 3:00 PM, and 4:00 PM."

The clinic server's actual availability for that date:
`['09:00', '09:30', '10:00', '13:30', '15:00', '16:00']`. **Identical.** The agent
was perfectly correct and my scorer called it a liar.

Cause: `check_invented_availability` parsed the tool's own returned slots with
`normalize_time(...)` at its **spoken** default. Under spoken rules `"09:00"` is
ambiguous (hour ≤ 12, no meridiem) and gets refused — so every morning slot silently
vanished from the ground-truth set, and only `13:30/15:00/16:00` survived. Any agent
correctly offering a morning appointment was reported as hallucinating.

This is **B4 all over again, at a call site I missed when I fixed B4.** Same root
cause: structured data parsed with rules meant for speech. I fixed the one place the
synthetic fixture happened to exercise and assumed I was done, rather than auditing
every call site. The audit took one grep and would have found it.

Two changes: the tool-result path now uses `context="structured"`, and a slot the
oracle emits that *won't* parse is recorded in `unparseable_tool_offers` rather than
silently dropped — ground truth should never disappear quietly. Five regression
tests, including one that pushes the real clinic server's output for four different
dates through the check.

**For the writeup:** the check was biased toward reporting hallucination on morning
appointments specifically. Had I not read a transcript, I'd have published "the naive
prompt hallucinates availability ~30% of the time" — a clean, plausible, entirely
manufactured finding. The deterministic scorer being reproducible does not make it
*correct*; it just means it's wrong the same way every time.

### F1. The hardened prompt made the agent pedantic — a real result

`s01/hardened#0` scored 0/4 and never booked. Transcript:

> AGENT: Just so I have it right — that's Tuesday the 22nd of September, 2026?
> Could you please confirm the year?
> USER: Three PM works.
> AGENT: I want to make sure I have the date right first. You said Tuesday the
> 22nd of September. Could you please confirm the year for that date?

My hardened rule "resolve relative dates explicitly, never silently pick an
interpretation" over-fired into demanding the *year*. No clinic scheduler asks that.
It cost two turns and the booking never happened.

This is exactly the failure mode the harness exists to find, and it's evidence
against a naive reading of "hardening helps" — a stricter prompt bought correctness
on ambiguity and paid for it in conversational efficiency.

### B13. The open-loop caller systematically penalises agents that ask more questions

F1 was *amplified* by a harness flaw. The scripted caller reads its lines regardless
of what the agent asks. When the hardened agent asked an unanticipated question, the
caller replied with the next scripted line — a non-answer — and the agent kept
asking. A real caller would have said "yes, 2026" and moved on.

So the harness had a built-in bias **favouring the arm that asks fewer questions**,
which is not the same as the arm that performs better. Fixed with a bounded
follow-up: once the script is exhausted and nothing is booked, the caller offers
"Yes, that's correct." up to 3 times. `followups_used` is recorded per run and
reported, so a pass that needed three nudges is visibly different from a clean one.

### Threat to validity: the hardened arm has been iterated, the naive arm has not

I changed `hardened.md` after seeing F1 — adding "assume the current year, don't ask
for it, ask about the date once." That is a legitimate prompt fix, and it is also
**one round of debugging the naive arm never received**, by construction: the naive
arm is defined as an un-iterated first draft.

This asymmetry favours the hardened arm and cannot be designed away without
abandoning the "first draft vs hardened" framing. It must be stated plainly in the
findings rather than buried, and the honest reading of any hardened-arm margin is:
*this is what a prompt looks like after one round of looking at failures.*

### B14. The agent was never told what day it is — every date was ~2 years off

Killed the second ablation attempt at run 7. `s04_mind_change/naive#0` scored 0/4,
and the tool log showed why:

```
USER   I'd like to book for Tuesday the twenty-second.
TOOL   check_availability({"date": "2024-08-22"})
```

**August 2024.** The scenario's `reference_date` is 2026-09-14, so the expected date
was 2026-09-22. The agent was out by two years and a month.

Cause: nothing in the system ever told the agent the current date. Retell does not
inject one, my prompts did not mention one, and I passed no dynamic variables. With
no anchor, the model fell back on its training-era notion of "now" — 2024 — and
resolved every relative and partial date against that.

The knock-on effects were entirely convincing as agent failures:
- the clinic reported Friday the 25th as closed, because 2024-08-25 is a *Sunday*
- the agent looped asking for "the exact date" because nothing it had made sense
- three scenarios turn on relative dates and all of them were quietly invalid

**Scope: this invalidated the entire date dimension of the experiment**, which is
the dimension three scenarios are built on and every other scenario touches.

Fixed by making the scenario's `reference_date` the single source of truth for the
agent as well as the scorer: both prompts carry an identical `## Today's date` block
using `{{current_day}}` / `{{current_date}}`, and both channels pass
`retell_llm_dynamic_variables` built from `reference_date`. A test asserts the block
is byte-identical across arms, since a difference there would be a confound rather
than hardening. Verified: the agent now calls `check_availability` with 2026-09-22.

**The part worth writing up.** Earlier I "fixed" the hardened agent demanding the
caller confirm the year (F1) by adding "assume the current year" to the prompt. That
was treating a symptom. The agent asked for the year because *it genuinely did not
know what year it was* — the most reasonable thing it could have done with the
context it had. I read a sensible question as pedantry, patched the prompt to
suppress it, and moved on. The underlying bug was mine and sat undetected for two
more runs.

That is the third time in this project a real defect wore the costume of an agent
failure (see also B12, B13). The pattern is consistent enough to be the spine of the
findings: **when your harness and the agent disagree, the harness is a serious
suspect — and a confident, well-formatted failure report is exactly what a harness
bug looks like from the outside.**

### Tooling: `make preflight`

Two ablation attempts died to setup bugs that produced confident, well-formatted,
entirely invalid results. Both were detectable in a single $0.01 chat. So that is
now a command.

`make preflight` runs one cheap text conversation and then asserts:

- the API key works and all four agent ids are present
- **the live prompt on Retell matches the file on disk** — I had already been caught
  once analysing results from a prompt I'd edited but not re-pushed
- both prompts carry `{{current_date}}`
- the agent called `check_availability` at all (if not, the tunnel is stale — the
  webhook 404s silently and looks like the agent refusing to use its tools)
- **the clinic server actually received the webhook**, by watching the tool log grow
- **the date the agent resolved matches the scenario's `reference_date`** — the B14
  check, derived from the scenario rather than hardcoded
- a booking completed and the booked date is right

The general lesson, which outlived the specific bugs: *the expensive part of an
eval harness is not the scoring, it's establishing that the thing you measured was
the thing you meant to measure.* Every check above exists because its absence
already cost a batch.

### B15. The two channels' follow-up logic diverged, making the metric incomparable

The bounded follow-up (B13's mitigation) was implemented twice, and the two copies
did not agree. The text channel re-reads the chat and stops as soon as
`book_appointment` appears. The audio channel had no equivalent check — it looped
`max_followups` times unconditionally, breaking only if the call had already ended.

Two consequences, one measurement and one financial:

- **`followups_used` was not comparable across channels.** Voice runs reported 3
  almost every time regardless of how the agent performed, so the metric said
  nothing — while looking like it said something. Any cross-channel comparison of
  "efficiency" would have been an artifact of my loop, not of the agent.
- Every voice call carried ~3 wasted turns. Across a 40-call voice ablation that is
  real money and several minutes of latency, for no information.

Mid-call we cannot read Retell's transcript, but the clinic tool server is ours and
logs every webhook keyed by `call_id` — so the voice channel now checks its own
ground-truth log to decide whether the agent has committed. Four tests, including a
corrupt-log case, since a half-written JSON line must never crash a live call.

**The general shape:** a mitigation implemented once per channel will drift, and the
drift shows up as a plausible cross-channel difference. Anything compared across
arms or channels should share one implementation — the same reason both channels
already flatten transcripts through one function.

### F2 / B16. The hallucination check was one-directional — it missed the opposite failure

`s06_ambiguous_third_closed/naive#0`. The tool returned availability for 2026-10-05:
`['09:00','09:30','10:00','13:30','14:00','15:00','16:00']` — **including 14:00**.
The agent then said:

> "We don't have a 2:00 PM slot, but we do have 1:30 PM or 2:00 PM is not available.
> Would you like to choose 1:30 PM or 3:00 PM instead?"

It denied a slot the tool had just returned — and the sentence is incoherent on top
of that. It then booked 13:30 instead of the expected 14:00, so the `time` slot was
correctly scored WRONG.

But `invented_availability` returned **PASS**, and correctly so by its own
definition: it only looks for times the agent states that the tool did *not* return.
Stating that an offered time is unavailable is the mirror-image failure, and the
check was blind to it by construction.

This matters commercially more than invention does. An agent that invents a slot
creates a scheduling conflict someone notices. An agent that refuses bookings it
could have taken loses revenue silently — nobody files a ticket for an appointment
they didn't make.

Added `check_denied_available_slot`. It is explicitly **heuristic** — it needs a
negation cue in the same utterance as an offered time — and one of its tests asserts
a known false positive ("2 PM is not available, but 3 PM is") so the weakness is
visible in the suite rather than discovered later by someone trusting the number.

**The generalisable bit:** every check I wrote asks "did the agent say something
untrue?" None asked "did the agent fail to say something true?" Omission is harder
to detect and, in a booking flow, more expensive. Worth a deliberate pass over any
eval suite asking which half of that pair each check covers.

### Tooling: `make rescore`

Today cost two batches to scorer bugs, and the fix each time meant re-running calls.
It shouldn't have. Every run commits its flattened event list and the agent's own
tool-call arguments, so a scorer fix can be applied to data already paid for:

    make rescore DIR=runs/<dir>            # dry run, shows every verdict that moves
    make rescore DIR=runs/<dir> WRITE=1    # applies, keeping a .bak

This is the actual dividend of keeping the primary score deterministic and the
transcripts committed. An LLM-judged suite cannot do it — re-grading means paying
for inference again and getting different answers. A rules-based one re-derives the
same verdicts for free, and a *fixed* scorer re-derives better ones.

It also makes scorer fixes safe to make late: the denial check above was added after
the run started, and the completed runs can be brought up to it without spending a
cent.

### B17. s09 expects a field neither prompt asks the agent to collect

Spotted while s09 was still queued, so this is a **prediction recorded before the
result**, which makes it a real test of the reasoning rather than a
post-hoc explanation.

`s09_self_correction` declares an expected `phone` slot (`5551234568`, after the
caller misspeaks and corrects it). But:

- neither prompt mentions collecting a phone number — both list name, date, time,
  reason and nothing else
- `book_appointment` accepts `phone` but does **not** list it in `required`

So the agent has no instruction to capture it and no schema pressure to. Predicted
outcome: `phone` comes back MISSING for most or all six s09 runs, in **both** arms.

Two things follow:

1. **It does not bias the ablation.** Both arms are handicapped identically, so the
   naive-vs-hardened comparison on s09 stays valid. What it distorts is s09's
   *absolute* pass rate, which will read as an agent failure when it is a
   specification failure.
2. **It is a scenario bug, not an agent finding.** A caller volunteering a phone
   number and the agent dropping it is a real-world failure worth testing — but you
   cannot test it against an agent you never told to collect one, and then report
   the result as though you had.

The fix is to add an optional phone field to **both** prompts identically (so it
stays context, not hardening) and re-run s09 alone. Deferred until the current run
finishes, because changing a prompt mid-batch would mean s09 ran against a different
agent than s01–s08 — which is exactly the kind of silent inconsistency this harness
exists to prevent.

Logged now so that, whichever way it lands, the record shows the expectation was
identified as mis-specified before the number arrived.

### B17 — RESOLVED, and the prediction was wrong

`s09_self_correction/naive#0` captured:

```json
{"patient_name": "Grace Lindqvist", "date": "2026-09-29", "time": "16:00",
 "reason": "Annual physical", "phone": "5551234568"}
```

`phone` **PASS** — and with the *corrected* digits (…4568, not the misspoken …4567).
All five slots passed. My prediction that it would come back MISSING was wrong.

Why it was wrong, and this is the useful part: I analysed the prompts and concluded
the agent had no instruction to collect a phone number. But `book_appointment`'s
schema declares `phone` with the description *"Callback number, if given."* **The
tool schema was the instruction.** The field existed, it was described in plain
language, the caller volunteered a number, and the model filled it — with no prompt
support and no `required` pressure.

So the prompt is not the only instruction channel, and for structured capture it may
not even be the main one. A JSON Schema property description is a directive the model
follows. That reframes the ablation slightly: the two arms differ in prompt, but they
share an identical tool schema, and **some of the behaviour I would have attributed
to prompt quality is actually coming from the schema both arms share.** That is a
real limit on how much any prompt-only ablation can explain, and it belongs in the
caveats.

It also means s09 is **not** mis-specified and needs no fix. I was wrong twice over:
wrong that the agent would fail, and wrong that the scenario was buggy.

Two things worth keeping from this:

- **Recording the prediction before the result was what made this useful.** Had I
  looked at the passing result first, I would have moved on and never noticed that my
  model of *why* it should work was broken. The falsified prediction is the finding.
- **It goes in the "expected to matter, didn't" column.** I expected prompt coverage
  of a field to be necessary for capture. It wasn't.

### Retell API asymmetry: chat tool webhooks carry no call_id

The clinic tool log accumulated 97 entries under `unknown.jsonl` and only a handful
under real `call_*.jsonl` files. Cause: **voice** calls post the tool webhook with a
`call` object containing `call_id`; **chat** posts the arguments at the top level
with no call wrapper and no identifier.

Consequences, both benign here but worth knowing:

- Text-run tool calls cannot be attributed to a specific chat from the server log
  alone. Not a problem for scoring, which reads tool calls out of the transcript, but
  it would break any per-conversation analysis built on the tool log.
- The voice channel's `_has_booked()` — which decides whether to keep offering
  follow-ups — relies on that `call_id`. It works, because voice supplies one. Had
  the asymmetry run the other way, the follow-up fix would have silently never fired
  and I'd have been back to three wasted turns per call while believing it fixed.

Checked rather than assumed, which is the only reason I know. The general habit worth
keeping: when two channels share a helper, verify the data it depends on exists on
both paths, not just the one you tested.
