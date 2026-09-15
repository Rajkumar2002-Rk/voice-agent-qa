"""Pull time/date mentions out of free-text utterances.

Used for two behavioural checks that need to know what the agent *said*, not
just what it recorded: confirm-back and invented-availability.
"""

from __future__ import annotations

import re
from datetime import date

from .normalize import normalize_date, normalize_time

_TIME_PATTERNS = [
    r"\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?",
    r"\b\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)",
    r"\bnoon\b",
    r"\bmidnight\b",
]
_TIME_RE = re.compile("|".join(_TIME_PATTERNS), re.IGNORECASE)

# Utterances describing opening hours legitimately contain times that were
# never "offered" as slots.  Excluding them removes the main false-positive
# mode of the hallucination check.  This is a heuristic and is declared as a
# known limitation in the findings.
_HOURS_CONTEXT = re.compile(
    r"\b(open|opens|closed|closes|hours|business hours|from .{0,12} to |between)\b",
    re.IGNORECASE,
)

_DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    r"\b(?:next|this)\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day\b",
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b",
    r"\b(?:today|tomorrow|day after tomorrow)\b",
    (r"\b(?:january|february|march|april|may|june|july|august|september|"
     r"october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?\b"),
    r"\bthe\s+\d{1,2}(?:st|nd|rd|th)\b",
]
_DATE_RE = re.compile("|".join(_DATE_PATTERNS), re.IGNORECASE)


def extract_times(text: str, *, skip_hours_context: bool = True) -> list[tuple[str, str]]:
    """Return [(raw_span, canonical_HH:MM)] for every parseable time mentioned."""
    if not text:
        return []
    if skip_hours_context and _HOURS_CONTEXT.search(text):
        return []
    out: list[tuple[str, str]] = []
    for m in _TIME_RE.finditer(text):
        raw = m.group(0).strip()
        n = normalize_time(raw)
        if n.ok and n.value:
            out.append((raw, n.value))
    return out


def extract_dates(text: str, reference: date) -> list[tuple[str, str]]:
    """Return [(raw_span, canonical_ISO_date)] for every parseable date mentioned."""
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for m in _DATE_RE.finditer(text):
        raw = m.group(0).strip()
        n = normalize_date(raw, reference)
        if n.ok and n.value:
            out.append((raw, n.value))
    return out
