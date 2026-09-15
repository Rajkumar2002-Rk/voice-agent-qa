# Run report — `_synthetic_example`

- runs: **102**  (0 errored)
- arms: naive, hardened   channels: voice, text   repeats: 3
- judge: disabled

## Pass rate — prompt arm x channel

Strict: every expected slot correct AND every behavioural check passed.

| channel | naive | hardened |
|---|---|---|
| voice | 13/30 (43%) | 21/30 (70%) |
| text | 12/21 (57%) | 15/21 (71%) |

## Pass rate by persona

This is the table the experiment exists to produce: where the hardened prompt helped, and where it didn't.

| persona | naive/voice | hardened/voice | naive/text | hardened/text |
|---|---|---|---|---|
| ambiguous_date | 3/6 (50%) | 6/6 (100%) | 3/6 (50%) | 6/6 (100%) |
| background_noise | 2/3 (67%) | 3/3 (100%) | — | — |
| barge_in | 0/3 (0%) | 0/3 (0%) | — | — |
| compound_utterance | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| happy_path | 2/3 (67%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |
| long_silence | 2/3 (67%) | 3/3 (100%) | — | — |
| mind_change | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) | 0/3 (0%) |
| out_of_scope | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |
| self_correction | 1/3 (33%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |

## Which slots failed

| arm | channel | slot | verdict | n | example reasoning |
|---|---|---|---|---|---|
| naive | voice | `time` | WRONG | 4 | agent captured '11:00' -> 11:00, expected '10am' -> 10:00 |
| naive | text | `patient_name` | MISSING | 3 | agent never captured this slot |
| naive | voice | `phone` | WRONG | 2 | agent captured '5551234567' -> 5551234567, expected '5551234568' -> 5551234568 |
| naive | voice | `patient_name` | MISSING | 1 | agent never captured this slot |

## Ambiguous-date alternate readings

_None._

## Behavioural checks

| arm | channel | check | pass | fail | n/a |
|---|---|---|---|---|---|
| hardened | text | `booked` | 18 | 0 | 0 |
| hardened | text | `confirmed_before_booking` | 12 | 6 | 3 |
| hardened | text | `expect_tool:book_appointment` | 18 | 0 | 0 |
| hardened | text | `expect_tool:check_availability` | 18 | 0 | 0 |
| hardened | text | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| hardened | text | `invented_availability` | 21 | 0 | 0 |
| hardened | text | `must_not_book` | 3 | 0 | 0 |
| hardened | voice | `booked` | 27 | 0 | 0 |
| hardened | voice | `confirmed_before_booking` | 18 | 9 | 3 |
| hardened | voice | `expect_tool:book_appointment` | 27 | 0 | 0 |
| hardened | voice | `expect_tool:check_availability` | 27 | 0 | 0 |
| hardened | voice | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| hardened | voice | `invented_availability` | 30 | 0 | 0 |
| hardened | voice | `must_not_book` | 3 | 0 | 0 |
| naive | text | `booked` | 18 | 0 | 0 |
| naive | text | `confirmed_before_booking` | 9 | 9 | 3 |
| naive | text | `expect_tool:book_appointment` | 18 | 0 | 0 |
| naive | text | `expect_tool:check_availability` | 18 | 0 | 0 |
| naive | text | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| naive | text | `invented_availability` | 21 | 0 | 0 |
| naive | text | `must_not_book` | 3 | 0 | 0 |
| naive | voice | `booked` | 27 | 0 | 0 |
| naive | voice | `confirmed_before_booking` | 10 | 17 | 3 |
| naive | voice | `expect_tool:book_appointment` | 27 | 0 | 0 |
| naive | voice | `expect_tool:check_availability` | 27 | 0 | 0 |
| naive | voice | `forbid_tool:book_appointment` | 3 | 0 | 0 |
| naive | voice | `invented_availability` | 30 | 0 | 0 |
| naive | voice | `must_not_book` | 3 | 0 | 0 |

## Turn latency

Voice only. Text-channel numbers are API round-trip and are not conversational latency; they are excluded here.

| arm | persona | n | median ms | p90 ms | max ms |
|---|---|---|---|---|---|
| hardened | ambiguous_date | 39 | 659 | 873 | 900 |
| hardened | background_noise | 24 | 668 | 841 | 883 |
| hardened | barge_in | 15 | 704 | 815 | 867 |
| hardened | compound_utterance | 9 | 644 | 817 | 817 |
| hardened | happy_path | 18 | 587 | 796 | 885 |
| hardened | long_silence | 18 | 708 | 850 | 900 |
| hardened | mind_change | 21 | 621 | 857 | 873 |
| hardened | out_of_scope | 12 | 668 | 868 | 900 |
| hardened | self_correction | 24 | 634 | 823 | 856 |
| naive | ambiguous_date | 39 | 1145 | 1462 | 1595 |
| naive | background_noise | 24 | 944 | 1491 | 1532 |
| naive | barge_in | 15 | 940 | 1586 | 1597 |
| naive | compound_utterance | 9 | 963 | 1485 | 1485 |
| naive | happy_path | 18 | 782 | 1454 | 1464 |
| naive | long_silence | 18 | 990 | 1522 | 1527 |
| naive | mind_change | 21 | 880 | 1438 | 1560 |
| naive | out_of_scope | 12 | 798 | 1086 | 1089 |
| naive | self_correction | 24 | 1036 | 1453 | 1600 |

## LLM judge vs deterministic scorer

The judge grades two checks the rules already cover. Disagreements are listed because they are the evidence for keeping the primary score deterministic.

_Judge disabled or no overlapping checks recorded._
