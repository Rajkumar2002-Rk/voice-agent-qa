# Run report — `full-2x2`

- runs: **82**  (0 errored)
- arms: hardened, naive   channels: text, voice   repeats: 3
- judge: anthropic (claude-sonnet-5)

## Pass rate — prompt arm x channel

Strict: every expected slot correct AND every behavioural check passed.

| channel | hardened | naive |
|---|---|---|
| text | 20/21 (95%) | 20/21 (95%) |
| voice | 16/20 (80%) | 15/20 (75%) |

## Pass rate by persona

This is the table the experiment exists to produce: where the hardened prompt helped, and where it didn't.

| persona | hardened/text | naive/text | hardened/voice | naive/voice |
|---|---|---|---|---|
| ambiguous_date | 6/6 (100%) | 5/6 (83%) | 4/4 (100%) | 4/4 (100%) |
| background_noise | — | — | 2/2 (100%) | 2/2 (100%) |
| barge_in | — | — | 0/2 (0%) | 0/2 (0%) |
| compound_utterance | 3/3 (100%) | 3/3 (100%) | 2/2 (100%) | 2/2 (100%) |
| happy_path | 3/3 (100%) | 3/3 (100%) | 2/2 (100%) | 2/2 (100%) |
| long_silence | — | — | 2/2 (100%) | 1/2 (50%) |
| mind_change | 3/3 (100%) | 3/3 (100%) | 2/2 (100%) | 2/2 (100%) |
| out_of_scope | 3/3 (100%) | 3/3 (100%) | 2/2 (100%) | 2/2 (100%) |
| self_correction | 2/3 (67%) | 3/3 (100%) | 0/2 (0%) | 0/2 (0%) |

## What the prompt could and could not fix

Mechanical classification from the 2x2. A cell counts as passing at >=67%, so one flake cannot flip a verdict.

| persona | naive/text | hard/text | naive/voice | hard/voice | verdict |
|---|---|---|---|---|---|
| ambiguous_date | 83% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| background_noise | — | — | 100% | 100% | **NOT_A_PROBLEM** |
| barge_in | — | — | 0% | 0% | **NOTHING_FIXED** |
| compound_utterance | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| happy_path | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| long_silence | — | — | 50% | 100% | **FIXED_BY_PROMPT** |
| mind_change | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| out_of_scope | 100% | 100% | 100% | 100% | **NOT_A_PROBLEM** |
| self_correction | 100% | 67% | 0% | 0% | **REGRESSED** |

- **ambiguous_date** — NOT_A_PROBLEM: passes everywhere under both prompts
- **background_noise** — NOT_A_PROBLEM: passes in voice under both prompts
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
| hardened | voice | `patient_name` | WRONG | 2 | agent captured "David O'Connell" -> david oconnell, expected 'David Okonkwo' -> david okonkwo |
| naive | voice | `patient_name` | WRONG | 2 | agent captured "David O'Connell" -> david oconnell, expected 'David Okonkwo' -> david okonkwo |
| hardened | voice | `patient_name` | MISSING | 2 | agent never captured this slot |
| hardened | voice | `date` | MISSING | 2 | agent never captured this slot |
| hardened | voice | `time` | MISSING | 2 | agent never captured this slot |
| hardened | voice | `phone` | MISSING | 2 | agent never captured this slot |
| hardened | voice | `reason` | MISSING | 2 | agent never captured this slot |
| naive | voice | `patient_name` | MISSING | 2 | agent never captured this slot |
| naive | voice | `date` | MISSING | 2 | agent never captured this slot |
| naive | voice | `time` | MISSING | 2 | agent never captured this slot |
| naive | voice | `phone` | MISSING | 2 | agent never captured this slot |
| naive | voice | `reason` | MISSING | 2 | agent never captured this slot |
| naive | text | `time` | WRONG | 1 | agent captured '13:30' -> 13:30, expected '2pm' -> 14:00 |
| hardened | text | `phone` | MISSING | 1 | agent never captured this slot |

## Ambiguous-date alternate readings

_None._

## Caller follow-ups needed

The scripted caller is open-loop. If the agent was still asking questions after the script ran out, the caller offered a bounded affirmation. An agent needing more nudges asked more questions — a real cost even when the run ultimately passed.

| arm | channel | runs | used >=1 | mean |
|---|---|---|---|---|
| hardened | text | 21 | 4 | 0.19 |
| hardened | voice | 20 | 6 | 0.40 |
| naive | text | 21 | 1 | 0.05 |
| naive | voice | 20 | 4 | 0.20 |

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
| hardened | voice | `booked` | 16 | 2 | 0 |
| hardened | voice | `confirmed_before_booking` | 16 | 0 | 4 |
| hardened | voice | `denied_available_slot` | 18 | 0 | 2 |
| hardened | voice | `expect_tool:book_appointment` | 16 | 2 | 0 |
| hardened | voice | `expect_tool:check_availability` | 18 | 0 | 0 |
| hardened | voice | `forbid_tool:book_appointment` | 2 | 0 | 0 |
| hardened | voice | `invented_availability` | 20 | 0 | 0 |
| hardened | voice | `must_not_book` | 2 | 0 | 0 |
| naive | text | `booked` | 18 | 0 | 0 |
| naive | text | `confirmed_before_booking` | 18 | 0 | 3 |
| naive | text | `denied_available_slot` | 17 | 1 | 3 |
| naive | text | `expect_tool:book_appointment` | 18 | 0 | 0 |
| naive | text | `expect_tool:check_availability` | 18 | 0 | 0 |
| naive | text | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| naive | text | `invented_availability` | 21 | 0 | 0 |
| naive | text | `must_not_book` | 3 | 0 | 0 |
| naive | voice | `booked` | 16 | 2 | 0 |
| naive | voice | `confirmed_before_booking` | 16 | 0 | 4 |
| naive | voice | `denied_available_slot` | 17 | 1 | 2 |
| naive | voice | `expect_tool:book_appointment` | 16 | 2 | 0 |
| naive | voice | `expect_tool:check_availability` | 18 | 0 | 0 |
| naive | voice | `forbid_tool:book_appointment` | 2 | 0 | 0 |
| naive | voice | `invented_availability` | 20 | 0 | 0 |
| naive | voice | `must_not_book` | 2 | 0 | 0 |

## Turn latency

Voice only. Text-channel numbers are API round-trip and are not conversational latency; they are excluded here.

Turns are split by whether a tool call happened inside them. A tool turn includes a webhook round-trip to the clinic server — over a tunnel to a laptop here — which is test rig, not agent. Quoting the combined number as the agent's response time would overstate it.

**Conversational turns (no tool call)**

| arm | persona | n | median ms | p90 ms | max ms |
|---|---|---|---|---|---|
| hardened | ambiguous_date | 21 | 1273 | 2360 | 3024 |
| hardened | background_noise | 12 | 1240 | 2981 | 2988 |
| hardened | barge_in | 8 | 1040 | 3612 | 3612 |
| hardened | compound_utterance | 2 | 2084 | 2432 | 2432 |
| hardened | happy_path | 8 | 1369 | 2229 | 2229 |
| hardened | long_silence | 10 | 1320 | 1983 | 1983 |
| hardened | mind_change | 10 | 1427 | 3702 | 3702 |
| hardened | out_of_scope | 9 | 1103 | 2317 | 2317 |
| hardened | self_correction | 18 | 1132 | 3795 | 7527 |
| naive | ambiguous_date | 18 | 1636 | 2938 | 3066 |
| naive | background_noise | 12 | 1790 | 2658 | 3616 |
| naive | barge_in | 9 | 1667 | 5116 | 5116 |
| naive | compound_utterance | 2 | 2148 | 2565 | 2565 |
| naive | happy_path | 8 | 1322 | 3931 | 3931 |
| naive | long_silence | 10 | 1245 | 4472 | 4472 |
| naive | mind_change | 10 | 1556 | 3694 | 3694 |
| naive | out_of_scope | 8 | 1179 | 3582 | 3582 |
| naive | self_correction | 16 | 1257 | 3961 | 4706 |

**Turns with a tool call**

| arm | persona | n | median ms | p90 ms | max ms |
|---|---|---|---|---|---|
| hardened | ambiguous_date | 9 | 2530 | 3241 | 3241 |
| hardened | background_noise | 4 | 2290 | 2911 | 2911 |
| hardened | barge_in | 6 | 3106 | 3703 | 3703 |
| hardened | compound_utterance | 4 | 2149 | 2992 | 2992 |
| hardened | happy_path | 4 | 1958 | 2666 | 2666 |
| hardened | long_silence | 4 | 2328 | 3581 | 3581 |
| hardened | mind_change | 4 | 2697 | 3176 | 3176 |
| hardened | self_correction | 2 | 1400 | 1476 | 1476 |
| naive | ambiguous_date | 8 | 2844 | 3983 | 3983 |
| naive | background_noise | 4 | 1961 | 6257 | 6257 |
| naive | barge_in | 4 | 2720 | 3709 | 3709 |
| naive | compound_utterance | 4 | 2786 | 3340 | 3340 |
| naive | happy_path | 4 | 2058 | 2965 | 2965 |
| naive | long_silence | 4 | 2820 | 2903 | 2903 |
| naive | mind_change | 5 | 3636 | 4300 | 4300 |
| naive | self_correction | 2 | 2960 | 3194 | 3194 |

Median conversational turn: **1331 ms** (n=191).  Median turn containing a tool call: **2635 ms** (n=72).

## LLM judge vs deterministic scorer

The judge grades two checks the rules already cover. Disagreements are listed because they are the evidence for keeping the primary score deterministic.

- agreed: **146/146** (100%)
- disagreed: **0**   judge said 'unclear': **0**

