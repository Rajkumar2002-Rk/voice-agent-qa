# DISCARDED PILOT — do not use these numbers

4 runs from the first text ablation attempt, killed early. Kept as evidence for
B12/F1/B13 in `docs/notes.md`, not as results.

**Invalid for two independent reasons:**

1. `check_invented_availability` parsed the availability tool's own 24-hour slots
   with *spoken* rules, so every morning slot was dropped from ground truth and
   `s01_happy_path/naive#2` was reported as inventing three times it had in fact
   read straight off the tool.
2. The hardened prompt demanded the caller confirm the year, and the open-loop
   caller could not answer, so `s01_happy_path/hardened#0` stalled at 0/4.

Both fixed before the real run. This directory is the reason the findings say a
reproducible scorer is not automatically a correct one.
