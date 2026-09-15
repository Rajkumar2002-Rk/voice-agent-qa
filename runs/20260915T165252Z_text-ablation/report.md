# Run report — `20260915T165252Z_text-ablation`

- runs: **42**  (0 errored)
- arms: naive, hardened   channels: text   repeats: 3
- spend: $0.42 / $8.00
- judge: anthropic (claude-sonnet-5)

## Pass rate — prompt arm x channel

Strict: every expected slot correct AND every behavioural check passed.

| channel | naive | hardened |
|---|---|---|
| text | 20/21 (95%) | 20/21 (95%) |

## Pass rate by persona

This is the table the experiment exists to produce: where the hardened prompt helped, and where it didn't.

| persona | naive/text | hardened/text |
|---|---|---|
| ambiguous_date | 5/6 (83%) | 6/6 (100%) |
| compound_utterance | 3/3 (100%) | 3/3 (100%) |
| happy_path | 3/3 (100%) | 3/3 (100%) |
| mind_change | 3/3 (100%) | 3/3 (100%) |
| out_of_scope | 3/3 (100%) | 3/3 (100%) |
| self_correction | 3/3 (100%) | 2/3 (67%) |

## What the prompt could and could not fix

Mechanical classification from the 2x2. A cell counts as passing at >=67%, so one flake cannot flip a verdict.

| persona | naive/text | hard/text | naive/voice | hard/voice | verdict |
|---|---|---|---|---|---|
| ambiguous_date | 83% | 100% | — | — | **TEXT_ONLY_EVIDENCE** |
| compound_utterance | 100% | 100% | — | — | **TEXT_ONLY_EVIDENCE** |
| happy_path | 100% | 100% | — | — | **TEXT_ONLY_EVIDENCE** |
| mind_change | 100% | 100% | — | — | **TEXT_ONLY_EVIDENCE** |
| out_of_scope | 100% | 100% | — | — | **TEXT_ONLY_EVIDENCE** |
| self_correction | 100% | 67% | — | — | **TEXT_ONLY_EVIDENCE** |

- **ambiguous_date** — TEXT_ONLY_EVIDENCE: no voice runs for this persona, so nothing can be said about whether its failures are structural to voice
- **compound_utterance** — TEXT_ONLY_EVIDENCE: no voice runs for this persona, so nothing can be said about whether its failures are structural to voice
- **happy_path** — TEXT_ONLY_EVIDENCE: no voice runs for this persona, so nothing can be said about whether its failures are structural to voice
- **mind_change** — TEXT_ONLY_EVIDENCE: no voice runs for this persona, so nothing can be said about whether its failures are structural to voice
- **out_of_scope** — TEXT_ONLY_EVIDENCE: no voice runs for this persona, so nothing can be said about whether its failures are structural to voice
- **self_correction** — TEXT_ONLY_EVIDENCE: no voice runs for this persona, so nothing can be said about whether its failures are structural to voice

## Which slots failed

| arm | channel | slot | verdict | n | example reasoning |
|---|---|---|---|---|---|
| naive | text | `time` | WRONG | 1 | agent captured '13:30' -> 13:30, expected '2pm' -> 14:00 |
| hardened | text | `phone` | MISSING | 1 | agent never captured this slot |

## Ambiguous-date alternate readings

_None._

## Caller follow-ups needed

The scripted caller is open-loop. If the agent was still asking questions after the script ran out, the caller offered a bounded affirmation. An agent needing more nudges asked more questions — a real cost even when the run ultimately passed.

| arm | channel | runs | used >=1 | mean |
|---|---|---|---|---|
| hardened | text | 21 | 4 | 0.19 |
| naive | text | 21 | 1 | 0.05 |

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
| naive | text | `booked` | 18 | 0 | 0 |
| naive | text | `confirmed_before_booking` | 18 | 0 | 3 |
| naive | text | `denied_available_slot` | 17 | 1 | 3 |
| naive | text | `expect_tool:book_appointment` | 18 | 0 | 0 |
| naive | text | `expect_tool:check_availability` | 18 | 0 | 0 |
| naive | text | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| naive | text | `invented_availability` | 21 | 0 | 0 |
| naive | text | `must_not_book` | 3 | 0 | 0 |

## Turn latency

Voice only. Text-channel numbers are API round-trip and are not conversational latency; they are excluded here.

_No voice runs with usable timestamps._

## LLM judge vs deterministic scorer

The judge grades two checks the rules already cover. Disagreements are listed because they are the evidence for keeping the primary score deterministic.

- agreed: **74/74** (100%)
- disagreed: **0**   judge said 'unclear': **0**

