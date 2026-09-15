"""Normalisation is the foundation of every verdict, so it gets the most tests."""

from datetime import date

import pytest

from harness.normalize import (
    alternate_date_reading,
    normalize_date,
    normalize_name,
    normalize_phone,
    normalize_reason,
    normalize_time,
    reason_matches,
)

MON = date(2026, 9, 14)
SAT = date(2026, 9, 19)
SUN = date(2026, 9, 20)


class TestDates:
    @pytest.mark.parametrize("raw,ref,want", [
        ("2026-09-22", MON, "2026-09-22"),
        ("today", MON, "2026-09-14"),
        ("tomorrow", MON, "2026-09-15"),
        ("day after tomorrow", MON, "2026-09-16"),
        ("October 3rd", MON, "2026-10-03"),
        ("3 October", MON, "2026-10-03"),
        ("the 3rd", MON, "2026-10-03"),
        ("the 20th", MON, "2026-09-20"),
        ("9/22", MON, "2026-09-22"),
        ("9/22/2026", MON, "2026-09-22"),
    ])
    def test_absolute_and_relative(self, raw, ref, want):
        assert normalize_date(raw, ref).value == want

    @pytest.mark.parametrize("ref,want", [
        (MON, "2026-09-22"),   # Mon -> Tue of following week
        (SAT, "2026-09-22"),   # Sat -> Tue of following week (3 days out)
        (SUN, "2026-09-22"),   # Sun -> Tue of following week (2 days out)
    ])
    def test_next_weekday_uses_following_calendar_week(self, ref, want):
        """The rule the docstring promises, checked from three starting days.

        This is a regression test for a real bug: the first implementation
        resolved 'next Tuesday' from a Saturday to 10 days out.
        """
        got = normalize_date("next Tuesday", ref)
        assert got.value == want
        assert got.rule == "date.weekday_next"

    def test_bare_weekday_is_next_occurrence(self):
        assert normalize_date("Tuesday", MON).value == "2026-09-15"

    def test_bare_weekday_never_resolves_to_reference_day(self):
        assert normalize_date("Monday", MON).value == "2026-09-21"

    def test_month_day_in_past_rolls_to_next_year(self):
        assert normalize_date("January 5", MON).value == "2027-01-05"

    def test_alternate_reading_is_offered_for_next_weekday(self):
        alt = alternate_date_reading("next Tuesday", MON)
        assert alt is not None and alt.value == "2026-09-15"

    def test_no_alternate_for_unambiguous_date(self):
        assert alternate_date_reading("2026-09-22", MON) is None

    @pytest.mark.parametrize("raw", ["", None, "sometime soon", "whenever"])
    def test_unparseable_fails_loudly(self, raw):
        got = normalize_date(raw, MON)
        assert not got.ok and got.value is None

    def test_impossible_date_rejected(self):
        assert not normalize_date("2026-02-30", MON).ok


class TestTimes:
    @pytest.mark.parametrize("raw,want", [
        ("3pm", "15:00"), ("3 PM", "15:00"), ("3:00 p.m.", "15:00"),
        ("15:00", "15:00"), ("9am", "09:00"), ("12pm", "12:00"),
        ("12am", "00:00"), ("noon", "12:00"), ("midnight", "00:00"),
        ("2:15pm", "14:15"), ("4 in the afternoon", "16:00"),
        ("9 in the morning", "09:00"),
    ])
    def test_canonical(self, raw, want):
        assert normalize_time(raw).value == want

    def test_bare_hour_refuses_to_guess_meridiem(self):
        """Quietly assuming pm is exactly the invented agreement we're hunting."""
        got = normalize_time("3")
        assert not got.ok
        assert got.rule == "time.ambiguous_meridiem"

    def test_24h_hour_is_unambiguous(self):
        assert normalize_time("16:30").value == "16:30"

    def test_out_of_range_rejected(self):
        assert not normalize_time("99:99").ok


class TestNamesPhonesReasons:
    @pytest.mark.parametrize("raw,want", [
        ("John Smith", "john smith"), ("  john   SMITH ", "john smith"),
        ("Mr. John Smith", "john smith"), ("Dr Jane Doe", "jane doe"),
        ("O'Brien", "obrien"), ("Mary-Jane", "mary jane"),
    ])
    def test_names(self, raw, want):
        assert normalize_name(raw).value == want

    def test_title_only_name_fails(self):
        assert not normalize_name("Mr.").ok

    @pytest.mark.parametrize("raw,want", [
        ("(555) 123-4567", "5551234567"), ("555.123.4567", "5551234567"),
        ("+1 555 123 4567", "5551234567"), ("15551234567", "5551234567"),
    ])
    def test_phones(self, raw, want):
        assert normalize_phone(raw).value == want

    def test_short_phone_rejected(self):
        assert not normalize_phone("123").ok

    def test_reason_accept_list(self):
        n = normalize_reason("My knee has been hurting!")
        assert n.ok
        ok, why = reason_matches(n.value, ["knee", "joint"])
        assert ok and "knee" in why

    def test_reason_miss_explains_itself(self):
        n = normalize_reason("I need a flu shot")
        ok, why = reason_matches(n.value, ["knee", "joint"])
        assert not ok and "knee" in why


class TestStructuredTimeContext:
    """Regression: the tool schema declares 24-hour HH:MM, so a structured
    '09:00' is unambiguous by contract. Treating it as ambiguous marked every
    correct morning appointment UNPARSEABLE."""

    def test_structured_colon_form_is_24h(self):
        got = normalize_time("09:00", context="structured")
        assert got.ok and got.value == "09:00"
        assert got.rule == "time.24h_by_schema"

    def test_structured_afternoon(self):
        assert normalize_time("15:00", context="structured").value == "15:00"

    def test_spoken_bare_hour_still_refused(self):
        assert not normalize_time("09:00", context="spoken").ok

    def test_structured_without_colon_still_refused(self):
        """No colon means the agent ignored the schema — that's a real failure."""
        got = normalize_time("9", context="structured")
        assert not got.ok
        assert "24-hour" in got.detail

    def test_structured_still_honours_explicit_meridiem(self):
        assert normalize_time("3pm", context="structured").value == "15:00"
