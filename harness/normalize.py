"""Slot normalisation.

Every function here is pure and total: same input -> same output, no clock, no
network, no model.  That is the whole point.  If a comparison cannot be made
deterministically it must fail loudly rather than guess, so the scorer can
report MISSING/UNPARSEABLE instead of silently inventing agreement.

Relative dates ("next Tuesday") are resolved against a *reference date declared
by the scenario*, never against today's date.  That is what makes the ambiguous
date scenarios reproducible a year from now.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Norm:
    """Outcome of normalising one raw value."""

    ok: bool
    value: str | None      # canonical form, e.g. "2026-09-22" or "15:00"
    rule: str              # which rule produced it — recorded in every verdict
    detail: str = ""       # human-readable note, shown in the report

    @staticmethod
    def fail(rule: str, detail: str) -> Norm:
        return Norm(ok=False, value=None, rule=rule, detail=detail)


# --------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s'-]")
_WS = re.compile(r"\s+")


def normalize_name(raw: str | None) -> Norm:
    if raw is None or not str(raw).strip():
        return Norm.fail("name.empty", "no value captured")
    s = str(raw).strip().lower()
    s = _PUNCT.sub("", s)
    # apostrophes vanish rather than split: STT renders "O'Brien" every which way
    s = s.replace("'", "").replace("-", " ")
    s = _WS.sub(" ", s).strip()
    # drop courtesy titles; they are not part of the identity
    parts = [p for p in s.split(" ") if p not in {"mr", "mrs", "ms", "miss", "dr", "mx"}]
    if not parts:
        return Norm.fail("name.only_title", f"{raw!r} contained only a title")
    return Norm(True, " ".join(parts), "name.casefold_strip_title")


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ORDINAL = re.compile(r"\b(\d{1,2})(st|nd|rd|th)\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")


def normalize_date(raw: str | None, reference: date) -> Norm:
    """Resolve a spoken/written date to ISO YYYY-MM-DD against `reference`.

    `reference` is the scenario's declared "today". Relative phrases are
    resolved from it so the expected answer never drifts.
    """
    if raw is None or not str(raw).strip():
        return Norm.fail("date.empty", "no value captured")

    s = str(raw).strip().lower()
    s = _WS.sub(" ", s)

    # 1. already ISO
    if m := _ISO.search(s):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        try:
            return Norm(True, date(y, mo, d).isoformat(), "date.iso")
        except ValueError:
            return Norm.fail("date.iso_invalid", f"{raw!r} is not a real calendar date")

    # 2. today / tomorrow / day after tomorrow
    for phrase, delta in (
        ("day after tomorrow", 2),
        ("tomorrow", 1),
        ("today", 0),
    ):
        if phrase in s:
            return Norm(
                True, (reference + timedelta(days=delta)).isoformat(),
                f"date.relative_{phrase.replace(' ', '_')}",
                f"resolved against reference {reference.isoformat()}",
            )

    # 3. weekday phrases.
    #
    #    "next <weekday>" is the genuinely ambiguous one. We commit to ONE
    #    reading and document it: the named weekday inside the *following
    #    calendar week* (weeks starting Monday). From Mon 14 Sep, "next
    #    Tuesday" is Tue 22 Sep, not tomorrow.
    #
    #    The competing reading — "the next Tuesday to occur", i.e. tomorrow —
    #    is also defensible, and real callers use both. So we also compute it
    #    and hand it back as `alternate`. The scorer marks a disagreement that
    #    matches `alternate` as AMBIGUOUS_ALTERNATE rather than WRONG, which
    #    keeps a defensible interpretation from being scored as an error.
    for name, idx in _WEEKDAYS.items():
        if not re.search(rf"\b{name}\b", s):
            continue

        ahead = (idx - reference.weekday()) % 7
        upcoming = reference + timedelta(days=ahead or 7)   # never the ref day itself

        next_monday = reference + timedelta(days=7 - reference.weekday())
        following_week = next_monday + timedelta(days=idx)

        if re.search(rf"\bnext\s+{name}\b", s):
            return Norm(
                True, following_week.isoformat(), "date.weekday_next",
                f"'next {name}' from {reference.isoformat()} "
                f"({reference.strftime('%A')}) resolved to the following "
                f"calendar week; competing reading would be "
                f"{upcoming.isoformat()}",
            )
        return Norm(
            True, upcoming.isoformat(), "date.weekday_upcoming",
            f"next occurrence of {name} strictly after {reference.isoformat()}",
        )

    # 4. "<month> <day>" or "<day> <month>", with or without ordinal suffix
    s_ord = _ORDINAL.sub(r"\1", s)
    for mname, mnum in _MONTHS.items():
        if re.search(rf"\b{mname}\b", s_ord):
            if (dm := re.search(rf"\b{mname}\b\s+(\d{{1,2}})\b", s_ord)) or (dm := re.search(rf"\b(\d{{1,2}})\s+{mname}\b", s_ord)):
                day = int(dm[1])
            else:
                return Norm.fail("date.month_no_day", f"{raw!r} names a month but no day")
            year = reference.year
            try:
                cand = date(year, mnum, day)
            except ValueError:
                return Norm.fail("date.month_day_invalid", f"{raw!r} is not a real date")
            if cand < reference:                # a past date means next year
                cand = date(year + 1, mnum, day)
            return Norm(True, cand.isoformat(), "date.month_day")

    # 5. bare ordinal — "the 3rd".  Next occurrence of that day-of-month.
    if om := re.search(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)?\b", s):
        day = int(om[1])
        if not 1 <= day <= 31:
            return Norm.fail("date.ordinal_range", f"day {day} out of range")
        y, mo = reference.year, reference.month
        for _ in range(13):
            try:
                cand = date(y, mo, day)
            except ValueError:
                mo += 1
                if mo > 12:
                    mo, y = 1, y + 1
                continue
            if cand >= reference:
                return Norm(
                    True, cand.isoformat(), "date.bare_ordinal",
                    f"next occurrence of day-{day} on/after {reference.isoformat()}",
                )
            mo += 1
            if mo > 12:
                mo, y = 1, y + 1
        return Norm.fail("date.ordinal_unresolved", f"could not place {raw!r}")

    # 6. numeric M/D or M/D/Y
    if m := _SLASH.search(s):
        mo, d = int(m[1]), int(m[2])
        y = reference.year
        if m[3]:
            y = int(m[3])
            if y < 100:
                y += 2000
        try:
            cand = date(y, mo, d)
        except ValueError:
            return Norm.fail("date.slash_invalid", f"{raw!r} is not a real date")
        if not m[3] and cand < reference:
            cand = date(y + 1, mo, d)
        return Norm(True, cand.isoformat(), "date.slash")

    return Norm.fail("date.unparseable", f"no rule matched {raw!r}")


# --------------------------------------------------------------------------
# times
# --------------------------------------------------------------------------

_WORD_HOUR = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_TIME_NUM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b")


def normalize_time(raw: str | None, *, context: str = "spoken") -> Norm:
    """Canonicalise to 24h HH:MM.

    `context` matters, and getting it wrong was a real bug here:

    - "spoken" (default): text a human or the agent SAID. A bare hour with no
      am/pm is NOT guessed at. "Three" could be either, and quietly assuming pm
      is exactly the invented agreement this harness exists to catch.

    - "structured": a value from a tool argument whose schema declares
      24-hour HH:MM. There "09:00" is unambiguous BY CONTRACT, and refusing it
      would mark every correct morning appointment UNPARSEABLE. A colon form is
      read as 24-hour; a bare hour with no colon and no meridiem is still
      refused, because that is the agent ignoring the schema.
    """
    if raw is None or not str(raw).strip():
        return Norm.fail("time.empty", "no value captured")

    s = str(raw).strip().lower().replace(".", "")
    s = _WS.sub(" ", s)

    # \b matters: a bare `"noon" in s` also matches "afterNOON", which silently
    # scored "4 in the afternoon" as 12:00. Regression test in test_normalize.py.
    if re.search(r"\bnoon\b", s) or re.search(r"\bmidday\b", s):
        return Norm(True, "12:00", "time.noon")
    if re.search(r"\bmidnight\b", s):
        return Norm(True, "00:00", "time.midnight")

    meridiem = None
    if re.search(r"(?<![a-z])p\s?m\b", s):
        meridiem = "pm"
    elif re.search(r"(?<![a-z])a\s?m\b", s):
        meridiem = "am"
    elif "afternoon" in s or "evening" in s:
        meridiem = "pm"
    elif "morning" in s:
        meridiem = "am"

    hour = minute = None
    if m := re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", s):
        hour, minute = int(m[1]), int(m[2])
    elif m := re.search(r"(?<!\d)(\d{1,2})(?!\d)", s):
        hour, minute = int(m[1]), 0
    else:
        for word, h in _WORD_HOUR.items():
            if re.search(rf"\b{word}\b", s):
                hour, minute = h, 0
                break
        if "thirty" in s and hour is not None:
            minute = 30
        if "quarter past" in s and hour is not None:
            minute = 15

    if hour is None:
        return Norm.fail("time.unparseable", f"no rule matched {raw!r}")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return Norm.fail("time.range", f"{hour}:{minute:02d} out of range")

    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    elif meridiem is None:
        if hour > 12:
            return Norm(True, f"{hour:02d}:{minute:02d}", "time.24h_unambiguous")
        if context == "structured" and ":" in s:
            return Norm(
                True, f"{hour:02d}:{minute:02d}", "time.24h_by_schema",
                f"{raw!r} came from a field declared as 24-hour HH:MM",
            )
        return Norm.fail(
            "time.ambiguous_meridiem",
            f"{raw!r} has no am/pm and hour {hour} could be either — refusing to guess"
            + (" (field declares 24-hour HH:MM but no colon was given)"
               if context == "structured" else ""),
        )

    return Norm(True, f"{hour:02d}:{minute:02d}", "time.meridiem")


# --------------------------------------------------------------------------
# phone numbers
# --------------------------------------------------------------------------


def normalize_phone(raw: str | None) -> Norm:
    if raw is None or not str(raw).strip():
        return Norm.fail("phone.empty", "no value captured")
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return Norm.fail("phone.length", f"{raw!r} -> {len(digits)} digits, expected 10")
    return Norm(True, digits, "phone.digits_last10")


# --------------------------------------------------------------------------
# free-text reason  (matched against a scenario-declared accept list)
# --------------------------------------------------------------------------


def normalize_reason(raw: str | None) -> Norm:
    if raw is None or not str(raw).strip():
        return Norm.fail("reason.empty", "no value captured")
    s = str(raw).strip().lower()
    s = _PUNCT.sub(" ", s)
    return Norm(True, _WS.sub(" ", s).strip(), "reason.casefold")


def reason_matches(normalized: str, accept_any_of: list[str]) -> tuple[bool, str]:
    """Reason is fuzzy by nature, so the *scenario* declares what counts.

    This keeps the check deterministic: the accept-list is written down before
    the run, not decided afterwards by a model looking at the answer.
    """
    for term in accept_any_of:
        t = term.strip().lower()
        if t and t in normalized:
            return True, f"matched declared term {term!r}"
    return False, (
        f"none of the declared terms {accept_any_of!r} appear in {normalized!r}"
    )


def alternate_date_reading(raw: str | None, reference: date) -> Norm | None:
    """The competing reading of an ambiguous relative date, or None.

    Only "next <weekday>" is genuinely two-way ambiguous in our scenario set.
    The scorer uses this to distinguish "the agent chose the other defensible
    interpretation" from "the agent got the date wrong", which are very
    different findings.
    """
    if raw is None or not str(raw).strip():
        return None
    s = _WS.sub(" ", str(raw).strip().lower())
    for name, idx in _WEEKDAYS.items():
        if re.search(rf"\bnext\s+{name}\b", s):
            ahead = (idx - reference.weekday()) % 7
            upcoming = reference + timedelta(days=ahead or 7)
            return Norm(
                True, upcoming.isoformat(), "date.weekday_next_alternate",
                f"competing reading of 'next {name}': the very next {name}",
            )
    return None
