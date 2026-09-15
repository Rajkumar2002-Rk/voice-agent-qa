# voice-agent-qa

A deterministic QA harness for Retell voice agents: scripted adversarial callers, a
rules-based scorer that tells you **which slot** was wrong and **what the agent
actually captured**, and a controlled ablation across two prompt arms and two
channels.

Built as a working answer to a specific question — *what does it take to
continuously QA a voice agent?* — against Retell's own API.

---

## The design point

**The primary score is reproducible. No LLM grades correctness.**

Each scenario declares its expected slots before the run. The scorer compares
captured vs. expected with explicit rules and records, for every verdict, which
rule fired and why:

```
time  WRONG   agent captured '16:00' -> 16:00, expected '3pm' -> 15:00
date  AMBIGUOUS_ALTERNATE
              agent captured 2026-09-15, which is the other defensible reading of
              'next Tuesday' (harness convention says 2026-09-22)
```

An LLM judge exists, but it is a **separate, clearly-labelled signal** for the fuzzy
parts (tone, graceful recovery). It cannot change a pass/fail verdict. It is also
deliberately asked to grade two checks the rules already cover, so the report can
show how often it agrees with ground truth — the empirical case for the whole design.

### Where the determinism comes from

Three decisions do most of the work:

1. **Scenarios pin a reference date.** "Next Tuesday" is ambiguous relative to *today*
   but fixed relative to a declared `reference_date: 2026-09-14`. The expected answer
   never drifts.
2. **The agent's own tool-call arguments are the captured slots.** `book_appointment`
   receives structured data; we never parse the agent's prose to guess what it heard.
3. **The clinic tool server is the oracle.** It logs exactly which appointment times
   it offered, so "did the agent invent an availability?" is a set difference over
   canonical times, not a judgment call.

---

## Status — what is and isn't verified

Being precise about this, because "runnable" is the whole claim.

| Component | Status |
|---|---|
| Deterministic scorer + normalisation | **Verified.** 188 tests, no network, no API key. |
| Scenario set (10 scenarios, 8 personas) | **Verified.** Self-consistency tested — every scenario is satisfiable by a perfect agent. |
| Clinic tool server | **Verified.** Deterministic availability, exercised in tests. |
| Report generator | **Verified** against a fabricated run fixture. |
| Text channel (Chat API) | **Verified live.** Passed first attempt. |
| Voice channel (WebRTC web call) | **Verified live.** Real audio, real barge-in timing, real turn latency. |
| Findings writeup | **In progress.** Text ablation run; voice ablation pending. |

`runs/_synthetic_example/` contains **fabricated** numbers used only to test the
reporter. It is stamped `SYNTHETIC: true`. Nothing in the findings comes from it.

`runs/_discarded_pilot_scorer_bug/` contains four **invalid** runs, kept deliberately
as evidence. Read its README — it is the concrete case where the scorer confidently
accused the agent of hallucinating times it had read correctly off the tool.

### Known limitations of the scorer itself

Stated here rather than only in the findings, because they change how to read output:

- **The hallucination check under-reports.** It suppresses utterances matching an
  opening-hours pattern, so an agent saying "I'm open at 2pm" (meaning the slot) is
  invisible to it. No deterministic fix found.
- **The scripted caller is open-loop.** It cannot answer an unanticipated question.
  A bounded follow-up ("Yes, that's correct." ×3) keeps this from silently failing
  agents that ask more clarifying questions; `followups_used` is reported per run.
- **A reproducible verdict is not a correct one.** See the discarded pilot.

## What web calls can and cannot test

This is a cost decision with real consequences, so it's stated up front rather than
buried.

**Testable over web calls:** barge-in and interruption handling, turn latency, long
silences, overlapping speech, compound utterances, self-correction, slot extraction
under degraded audio, tool-call discipline.

**Not testable:** real telephony. Web calls are wideband Opus over WebRTC. They do not
reproduce 8 kHz μ-law carrier codecs, PSTN jitter and packet loss, carrier-side echo,
or DTMF. An agent that passes here can still fail on a real phone line, and this
harness will not tell you that.

Retell web calls also have no documented server-side join path — `create-web-call`
returns a token for a browser, and signalling goes through an internal WebRTC gateway.
So the voice channel drives **real headless Chromium running the real Retell SDK**,
with `navigator.mediaDevices.getUserMedia` patched to return a synthetic audio stream
we control. That uses only public API surface, and it's what makes closed-loop
barge-in possible: the caller can start speaking *while the agent is still talking*.

---

## Setup

Full account walkthrough: **[docs/retell-setup.md](docs/retell-setup.md)**.

```bash
make install                 # venv + deps
cp .env.example .env         # then fill in RETELL_API_KEY
make check-key               # verify it works
```

For the voice channel:

```bash
make install-audio           # playwright + chromium
```

The agent uses tools, and Retell calls tools as webhooks, so the clinic server needs a
public URL:

```bash
make serve                   # terminal 1 — clinic server on :8000
make tunnel                  # terminal 2 — prints https://xxx.trycloudflare.com
make provision URL=https://xxx.trycloudflare.com   # terminal 3
```

That creates four agents — two prompt arms x two channels — and writes their IDs into
`.env`. Both channels of a given arm are backed by the **same Retell LLM object**, so
the prompt really is the only thing that varies.

> The tunnel URL changes whenever cloudflared restarts. Re-run with
> `make provision URL=... UPDATE=1` or the tools will 404.

## Running

```bash
make test                    # scorer suite — no API key needed
make synthetic               # see example report output — no API key needed

make preflight               # cheap setup checks — RUN THIS BEFORE ANY BATCH

make smoke                   # one cheap text run
make smoke-voice             # one real web call

make run-text                # full text ablation
make run-full                # full 2x2 — costs real credits

make report DIR=runs/<dir>
```

The runner estimates spend before starting and **refuses to run** if the estimate
exceeds `MAX_SPEND_USD`, then tracks actual spend and aborts mid-batch if it's
crossed. Partial results are always saved.

```
grid: 68 runs  (40 voice, 28 text)
skipped (channel not meaningful for scenario): s02_barge_in/text, ...
estimated spend: $9.88  (guard at $8.00)
REFUSING TO START: estimate $9.88 exceeds MAX_SPEND_USD $8.00.
```

## The scenarios

Ten scenarios covering eight adversarial personas. Scenarios declare which channels
they're meaningful on — barge-in, background noise and long silence are **voice-only**,
and the runner skips them on text rather than pretending a text run tested them.

| scenario | persona | channels |
|---|---|---|
| `s01_happy_path` | control | voice, text |
| `s02_barge_in` | interrupts mid-sentence | voice |
| `s03_background_noise` | noise / talking over | voice |
| `s04_mind_change` | changes their mind halfway | voice, text |
| `s05_ambiguous_next_tuesday` | "next Tuesday" | voice, text |
| `s06_ambiguous_third_closed` | "the 3rd" — lands on a closed Saturday | voice, text |
| `s07_long_silence` | goes quiet for 12s | voice |
| `s08_out_of_scope` | asks for something with no tool | voice, text |
| `s09_self_correction` | says a number wrong, corrects it | voice, text |
| `s10_compound_utterance` | two facts in one breath | voice, text |

## Layout

```
agent/
  prompts/{naive,hardened}.md   the ablation's independent variable
  clinic_server.py              tool backend + ground-truth oracle
  provision.py                  creates the 4 agents, pins shared config
harness/
  normalize.py                  pure, total slot normalisation
  scorer.py                     the deterministic scorer
  judge.py                      secondary LLM signal (never authoritative)
  channels/{text,audio}.py      Chat API / WebRTC web call
  runner.py                     grid + budget guard
  report.py                     markdown aggregation
docs/
  retell-setup.md               account walkthrough
  notes.md                      lab notebook, including my own bugs
  findings.md                   the writeup
```

## License

MIT
