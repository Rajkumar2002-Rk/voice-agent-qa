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
