# Run report — `final-2x2`

- runs: **102**  (0 errored)
- arms: hardened, naive   channels: text, voice   repeats: 3
- judge: anthropic (claude-sonnet-5)

## Pass rate — prompt arm x channel

Strict: every expected slot correct AND every behavioural check passed.

| channel | hardened | naive |
|---|---|---|
| text | 20/21 (95%) | 20/21 (95%) |
| voice | 22/30 (73%) | 20/30 (67%) |

## Pass rate by persona

This is the table the experiment exists to produce: where the hardened prompt helped, and where it didn't.

| persona | hardened/text | naive/text | hardened/voice | naive/voice |
|---|---|---|---|---|
| ambiguous_date | 6/6 (100%) | 5/6 (83%) | 5/6 (83%) | 6/6 (100%) |
| background_noise | — | — | 2/3 (67%) | 0/3 (0%) |
| barge_in | — | — | 0/3 (0%) | 0/3 (0%) |
| compound_utterance | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |
| happy_path | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |
| long_silence | — | — | 3/3 (100%) | 2/3 (67%) |
| mind_change | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |
| out_of_scope | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |
| self_correction | 2/3 (67%) | 3/3 (100%) | 0/3 (0%) | 0/3 (0%) |

## What the prompt could and could not fix

Mechanical classification from the 2x2. A cell counts as passing at >=67%, so one flake cannot flip a verdict.

| persona | naive/text | hard/text | naive/voice | hard/voice | verdict |
|---|---|---|---|---|---|
| ambiguous_date | 83% | 100% | 100% | 83% | **NOT_A_PROBLEM** |
| background_noise | — | — | 0% | 67% | **NOTHING_FIXED** |
| barge_in | — | — | 0% | 0% | **NOTHING_FIXED** |
| compound_utterance | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| happy_path | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| long_silence | — | — | 67% | 100% | **FIXED_BY_PROMPT** |
| mind_change | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| out_of_scope | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| self_correction | 100% | 67% | 0% | 0% | **REGRESSED** |

- **ambiguous_date** — NOT_A_PROBLEM: passes everywhere under both prompts
- **background_noise** — NOTHING_FIXED: fails in voice under both prompts
- **barge_in** — NOTHING_FIXED: fails in voice under both prompts
- **compound_utterance** — NOT_A_PROBLEM: passes everywhere under both prompts
- **happy_path** — NOT_A_PROBLEM: passes everywhere under both prompts
- **long_silence** — FIXED_BY_PROMPT: voice-only persona: fails naive, passes hardened. No text control exists, so 'structural' cannot be ruled out — only that the prompt moved it
- **mind_change** — NOT_A_PROBLEM: passes everywhere under both prompts
- **out_of_scope** — NOT_A_PROBLEM: passes everywhere under both prompts
- **self_correction** — REGRESSED: the hardened prompt made this persona worse

## Which slots failed

| arm | channel | slot | verdict | n | example reasoning |
|---|---|---|---|---|---|
| naive | voice | `patient_name` | WRONG | 9 | agent captured 'Dave O' -> dave o, expected 'David Okonkwo' -> david okonkwo |
| hardened | voice | `patient_name` | MISSING | 6 | agent never captured this slot |
| hardened | voice | `date` | MISSING | 6 | agent never captured this slot |
| hardened | voice | `time` | MISSING | 6 | agent never captured this slot |
| hardened | voice | `reason` | MISSING | 6 | agent never captured this slot |
| hardened | voice | `phone` | MISSING | 3 | agent never captured this slot |
| hardened | voice | `patient_name` | WRONG | 2 | agent captured 'Dave O and KWO' -> dave o and kwo, expected 'David Okonkwo' -> david okonkwo |
| naive | text | `time` | WRONG | 1 | agent captured '13:30' -> 13:30, expected '2pm' -> 14:00 |
| naive | voice | `time` | WRONG | 1 | agent captured '09:30' -> 09:30, expected '1:30pm' -> 13:30 |
| hardened | text | `phone` | MISSING | 1 | agent never captured this slot |
| naive | voice | `phone` | UNPARSEABLE | 1 | agent captured '555123568', which no rule could normalise ('555123568' -> 9 digits, expected 10) |

## Ambiguous-date alternate readings

_None._

## What kind of wrong

Pass/fail collapses two opposite behaviours. An agent that books a garbled patient name and one that refuses to book because it could not confirm the name both score zero — but for a clinic the second is the correct outcome. These labels never affect pass/fail.

| arm | channel | correct | safe_refusal | unsafe_commit | stalled |
|---|---|---|---|---|---|
| hardened | text | 20 | 0 | 1 | 0 |
| hardened | voice | 22 | 5 | 2 | 1 |
| naive | text | 20 | 0 | 1 | 0 |
| naive | voice | 20 | 0 | 10 | 0 |

`unsafe_commit` is the number that should worry a clinic: the agent told the caller their appointment was booked, with wrong data.

## Caller follow-ups needed

The scripted caller is open-loop. If the agent was still asking questions after the script ran out, the caller offered a bounded affirmation. An agent needing more nudges asked more questions — a real cost even when the run ultimately passed.

| arm | channel | runs | used >=1 | mean |
|---|---|---|---|---|
| hardened | text | 21 | 4 | 0.19 |
| hardened | voice | 30 | 9 | 0.57 |
| naive | text | 21 | 1 | 0.05 |
| naive | voice | 30 | 1 | 0.03 |

## Behavioural checks

| arm | channel | check | pass | fail | n/a |
|---|---|---|---|---|---|
| hardened | text | `booked` | 18 | 0 | 0 |
| hardened | text | `confirmed_before_booking` | 18 | 0 | 3 |
| hardened | text | `denied_available_slot` | 18 | 0 | 3 |
| hardened | text | `expect_tool:book_appointment` | 18 | 0 | 0 |
| hardened | text | `expect_tool:check_availability` | 18 | 0 | 0 |
| hardened | text | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| hardened | text | `invented_availability` | 21 | 0 | 0 |
| hardened | text | `must_not_book` | 3 | 0 | 0 |
| hardened | text | `risk_class` | 0 | 0 | 21 |
| hardened | voice | `booked` | 21 | 6 | 0 |
| hardened | voice | `confirmed_before_booking` | 21 | 0 | 9 |
| hardened | voice | `denied_available_slot` | 24 | 0 | 6 |
| hardened | voice | `expect_tool:book_appointment` | 21 | 6 | 0 |
| hardened | voice | `expect_tool:check_availability` | 25 | 2 | 0 |
| hardened | voice | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| hardened | voice | `invented_availability` | 30 | 0 | 0 |
| hardened | voice | `must_not_book` | 3 | 0 | 0 |
| hardened | voice | `risk_class` | 0 | 0 | 30 |
| naive | text | `booked` | 18 | 0 | 0 |
| naive | text | `confirmed_before_booking` | 18 | 0 | 3 |
| naive | text | `denied_available_slot` | 17 | 1 | 3 |
| naive | text | `expect_tool:book_appointment` | 18 | 0 | 0 |
| naive | text | `expect_tool:check_availability` | 18 | 0 | 0 |
| naive | text | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| naive | text | `invented_availability` | 21 | 0 | 0 |
| naive | text | `must_not_book` | 3 | 0 | 0 |
| naive | text | `risk_class` | 0 | 0 | 21 |
| naive | voice | `booked` | 27 | 0 | 0 |
| naive | voice | `confirmed_before_booking` | 27 | 0 | 3 |
| naive | voice | `denied_available_slot` | 26 | 1 | 3 |
| naive | voice | `expect_tool:book_appointment` | 27 | 0 | 0 |
| naive | voice | `expect_tool:check_availability` | 27 | 0 | 0 |
| naive | voice | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| naive | voice | `invented_availability` | 30 | 0 | 0 |
| naive | voice | `must_not_book` | 3 | 0 | 0 |
| naive | voice | `risk_class` | 0 | 0 | 30 |

## Turn latency

Voice only. Text-channel numbers are API round-trip and are not conversational latency; they are excluded here.

Turns are split by whether a tool call happened inside them. A tool turn includes a webhook round-trip to the clinic server — over a tunnel to a laptop here — which is test rig, not agent. Quoting the combined number as the agent's response time would overstate it.

**Conversational turns (no tool call)**

| arm | persona | n | median ms | p90 ms | max ms |
|---|---|---|---|---|---|
| hardened | ambiguous_date | 31 | 1112 | 2148 | 2716 |
| hardened | background_noise | 18 | 1197 | 2651 | 2810 |
| hardened | barge_in | 20 | 1294 | 2798 | 2957 |
| hardened | compound_utterance | 5 | 1732 | 2120 | 2120 |
| hardened | happy_path | 12 | 958 | 1130 | 1230 |
| hardened | long_silence | 12 | 1115 | 3310 | 3935 |
| hardened | mind_change | 16 | 1027 | 2185 | 3272 |
| hardened | out_of_scope | 12 | 821 | 1056 | 1124 |
| hardened | self_correction | 27 | 986 | 2698 | 3155 |
| naive | ambiguous_date | 27 | 1797 | 2869 | 5092 |
| naive | background_noise | 18 | 1262 | 3056 | 3090 |
| naive | barge_in | 11 | 1141 | 2250 | 2253 |
| naive | compound_utterance | 3 | 1819 | 2088 | 2088 |
| naive | happy_path | 13 | 989 | 2098 | 3188 |
| naive | long_silence | 13 | 1117 | 1831 | 2322 |
| naive | mind_change | 16 | 1200 | 2711 | 2737 |
| naive | out_of_scope | 12 | 992 | 1244 | 1437 |
| naive | self_correction | 19 | 1093 | 3111 | 3238 |

**Turns with a tool call**

| arm | persona | n | median ms | p90 ms | max ms |
|---|---|---|---|---|---|
| hardened | ambiguous_date | 12 | 2412 | 3496 | 4305 |
| hardened | background_noise | 6 | 1518 | 2321 | 2321 |
| hardened | barge_in | 3 | 2142 | 2259 | 2259 |
| hardened | compound_utterance | 7 | 1980 | 2732 | 2732 |
| hardened | happy_path | 6 | 1677 | 2443 | 2443 |
| hardened | long_silence | 7 | 1881 | 2586 | 2586 |
| hardened | mind_change | 6 | 2102 | 2913 | 2913 |
| hardened | self_correction | 2 | 2623 | 3364 | 3364 |
| naive | ambiguous_date | 12 | 2275 | 2597 | 3007 |
| naive | background_noise | 6 | 1786 | 3167 | 3167 |
| naive | barge_in | 7 | 2087 | 2545 | 2545 |
| naive | compound_utterance | 6 | 2216 | 2618 | 2618 |
| naive | happy_path | 6 | 2940 | 3894 | 3894 |
| naive | long_silence | 6 | 2064 | 2347 | 2347 |
| naive | mind_change | 8 | 2724 | 3685 | 3685 |
| naive | self_correction | 5 | 3000 | 3635 | 3635 |

Median conversational turn: **1138 ms** (n=285).  Median turn containing a tool call: **2093 ms** (n=105).

## LLM judge vs deterministic scorer

The judge grades two checks the rules already cover. Disagreements are listed because they are the evidence for keeping the primary score deterministic.

- agreed: **177/177** (100%)
- disagreed: **0**   judge said 'unclear': **0**

