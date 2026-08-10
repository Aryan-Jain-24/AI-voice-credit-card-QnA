"""Tests for tools_txn.py (S03) — resolve_period plus the six transaction tools.

Every expected numeric value below was hand-computed independently: either
worked out on paper from calendar arithmetic (for `resolve_period`), or
produced by a standalone pandas one-liner run separately from this test
suite and pasted in as a literal (for the aggregation tools) — never by
calling the function under test and asserting its own output.

Tests call the private `_..._core` functions directly (not the
`@tool`-decorated wrappers) so a fixed `today` can be injected — the real
`date.today()` will keep moving, but the synthetic dataset is frozen and
ends 2026-07-31, so tests must pin `today` to stay meaningful regardless of
when they're run. Numeric-correctness assertions therefore live on the
`_..._core` functions.

Separately, `TestToolWrappersEndToEnd` below invokes the real
`@tool`-decorated functions through `.invoke()` (LangChain's calling
convention, as the planner in S05 will use them) with no injected `today`,
confirming the whole wrapper -> `data_loader.load_transactions()` -> pandas
path is wired correctly. Those assertions are structural (keys, types,
internal consistency) rather than hand-computed literals, since they run
against whatever the real clock says "last month" is.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from data_loader import load_transactions
from tools_txn import (
    _compare_periods_core,
    _find_transactions_core,
    _recurring_charges_core,
    _spend_by_category_core,
    _spend_total_core,
    _top_merchants_core,
    compare_periods,
    find_transactions,
    recurring_charges,
    resolve_period,
    spend_by_category,
    spend_total,
    top_merchants,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = str(REPO_ROOT / "mapping.yaml")

# The project's fixed reference "today" (see generate_data.py and
# CLAUDE.md's currentDate) — the synthetic dataset was deliberately built
# to end the month before this date (2026-07-31), so "last month" from
# here always lands on a fully populated month.
TODAY = date(2026, 8, 11)


@pytest.fixture(scope="module")
def df():
    return load_transactions(MAPPING_PATH)


# ==========================================================================
# resolve_period
# ==========================================================================


class TestResolvePeriod:
    def test_last_month(self):
        # Hand: today is Aug 2026 -> previous calendar month is July 2026,
        # which has 31 days.
        assert resolve_period("last month", TODAY) == (
            date(2026, 7, 1),
            date(2026, 7, 31),
            "July 2026",
        )

    def test_this_month(self):
        assert resolve_period("this month", TODAY) == (
            date(2026, 8, 1),
            date(2026, 8, 31),
            "August 2026",
        )

    def test_this_week_and_last_week(self):
        # Hand: 2026-08-11 is a Tuesday (weekday index 1). Monday-start
        # week containing it is 2026-08-10 .. 2026-08-16; the week before
        # that is 2026-08-03 .. 2026-08-09.
        assert resolve_period("this week", TODAY) == (
            date(2026, 8, 10),
            date(2026, 8, 16),
            "Aug 10 - Aug 16, 2026",
        )
        assert resolve_period("last week", TODAY) == (
            date(2026, 8, 3),
            date(2026, 8, 9),
            "Aug 03 - Aug 09, 2026",
        )

    def test_last_n_months_does_not_include_current_month(self):
        # Hand: last month is July 2026; "last 3 months" is the 3 full
        # calendar months ending there: May, June, July 2026. August
        # (in progress) is deliberately excluded.
        assert resolve_period("last 3 months", TODAY) == (
            date(2026, 5, 1),
            date(2026, 7, 31),
            "May 2026 - Jul 2026 (last 3 months)",
        )

    def test_last_year(self):
        assert resolve_period("last year", TODAY) == (
            date(2025, 1, 1),
            date(2025, 12, 31),
            "2025",
        )

    def test_ytd(self):
        assert resolve_period("YTD", TODAY) == (
            date(2026, 1, 1),
            date(2026, 8, 11),
            "Jan 1 - Aug 11, 2026 (YTD)",
        )

    def test_named_month_no_year_defaults_to_most_recent_non_future_occurrence(self):
        # Hand: today is August 2026. "March" (month 3 <= 8) resolves to
        # this year, March 2026. "December" (month 12 > 8) hasn't happened
        # yet this year, so it resolves to last December, i.e. 2025.
        assert resolve_period("March", TODAY) == (
            date(2026, 3, 1),
            date(2026, 3, 31),
            "March 2026",
        )
        assert resolve_period("December", TODAY) == (
            date(2025, 12, 1),
            date(2025, 12, 31),
            "December 2025",
        )

    def test_named_month_with_explicit_year(self):
        assert resolve_period("in December 2025", TODAY) == (
            date(2025, 12, 1),
            date(2025, 12, 31),
            "December 2025",
        )

    def test_specific_date_iso_and_natural_forms(self):
        expected = (date(2026, 3, 14), date(2026, 3, 14), "March 14, 2026")
        assert resolve_period("2026-03-14", TODAY) == expected
        assert resolve_period("March 14, 2026", TODAY) == expected
        assert resolve_period("14 March 2026", TODAY) == expected

    def test_year_boundary_rollover(self):
        # Hand: today is 2026-01-15 (a Thursday). "last month" must roll
        # back across the year boundary to December 2025, not month 0.
        jan_today = date(2026, 1, 15)
        assert resolve_period("last month", jan_today) == (
            date(2025, 12, 1),
            date(2025, 12, 31),
            "December 2025",
        )
        # Hand: Monday of the week containing 2026-01-15 is 2026-01-12;
        # last week is therefore 2026-01-05 .. 2026-01-11.
        assert resolve_period("last week", jan_today) == (
            date(2026, 1, 5),
            date(2026, 1, 11),
            "Jan 05 - Jan 11, 2026",
        )
        # Hand: last month from Jan 2026 is Dec 2025; 3 months ending
        # there is Oct, Nov, Dec 2025 -- crossing the year boundary.
        assert resolve_period("last 3 months", jan_today) == (
            date(2025, 10, 1),
            date(2025, 12, 31),
            "Oct 2025 - Dec 2025 (last 3 months)",
        )

    def test_unsupported_phrase_raises(self):
        with pytest.raises(ValueError):
            resolve_period("sometime next quarter maybe", TODAY)

    def test_empty_phrase_raises(self):
        with pytest.raises(ValueError):
            resolve_period("   ", TODAY)


# ==========================================================================
# spend_total
# ==========================================================================


class TestSpendTotal:
    def test_last_month_all_categories(self, df):
        # Hand-computed via an independent one-liner against the loaded
        # DataFrame (not through this tool):
        #   jul = df[(df.timestamp.dt.date >= date(2026,7,1)) & (df.timestamp.dt.date <= date(2026,7,31))]
        #   round(jul.amount.sum(), 2) == 122048.88; len(jul) == 101
        result = _spend_total_core(df, "last month", category=None, card_id=None, today=TODAY)
        assert result == {
            "total": 122048.88,
            "count": 101,
            "period_label": "July 2026",
            "avg_txn": round(122048.88 / 101, 2),
        }

    def test_last_month_food_dining_category_filter(self, df):
        # Hand-computed: jul[jul.category == 'food_dining'] -> sum
        # 18159.05 across 22 rows, avg 825.41.
        result = _spend_total_core(
            df, "last month", category="food_dining", card_id=None, today=TODAY
        )
        assert result == {
            "total": 18159.05,
            "count": 22,
            "period_label": "July 2026",
            "avg_txn": 825.41,
        }

    def test_period_with_no_data_returns_zeroed_result(self, df):
        # Hand: the dataset ends 2026-07-31, so "this month" (August 2026,
        # relative to TODAY) contains zero rows by construction.
        result = _spend_total_core(df, "this month", category=None, card_id=None, today=TODAY)
        assert result == {
            "total": 0.0,
            "count": 0,
            "period_label": "August 2026",
            "avg_txn": 0.0,
        }

    def test_card_id_filter(self, df):
        # Hand: the synthetic dataset is single-card (card_id == "XXXX4412"
        # for every row, per generate_data.py). Filtering to that card_id
        # must reproduce the unfiltered total; filtering to any other
        # card_id must return zero rows.
        unfiltered = _spend_total_core(df, "last month", category=None, card_id=None, today=TODAY)
        same_card = _spend_total_core(
            df, "last month", category=None, card_id="XXXX4412", today=TODAY
        )
        other_card = _spend_total_core(
            df, "last month", category=None, card_id="XXXX0000", today=TODAY
        )
        assert same_card == unfiltered
        assert other_card == {
            "total": 0.0,
            "count": 0,
            "period_label": "July 2026",
            "avg_txn": 0.0,
        }


# ==========================================================================
# spend_by_category
# ==========================================================================


class TestSpendByCategory:
    def test_top_3_categories_for_february_2026(self, df):
        # Reference date 2026-03-10 (a Tuesday) so "last month" resolves
        # to February 2026, a normal populated month.
        # Hand-computed via an independent one-liner:
        #   feb = df[... between 2026-02-01 and 2026-02-28 ...]
        #   feb.groupby('category').amount.sum().sort_values(ascending=False)
        # gave: travel 25139.64, shopping 21695.99, groceries 18125.61,
        # ... ; grand total (all categories) 115399.39.
        # pct = category_total / grand_total * 100:
        #   travel:    25139.64 / 115399.39 * 100 = 21.78
        #   shopping:  21695.99 / 115399.39 * 100 = 18.80
        #   groceries: 18125.61 / 115399.39 * 100 = 15.71
        result = _spend_by_category_core(
            df, "last month", top_n=3, today=date(2026, 3, 10)
        )
        assert result == {
            "categories": [
                {"name": "travel", "total": 25139.64, "pct": 21.78},
                {"name": "shopping", "total": 21695.99, "pct": 18.8},
                {"name": "groceries", "total": 18125.61, "pct": 15.71},
            ],
            "total": 115399.39,
            "period_label": "February 2026",
        }

    def test_top_n_1_returns_single_top_category(self, df):
        result = _spend_by_category_core(
            df, "last month", top_n=1, today=date(2026, 3, 10)
        )
        assert len(result["categories"]) == 1
        assert result["categories"][0]["name"] == "travel"
        assert result["categories"][0]["total"] == 25139.64

    def test_period_with_no_data_returns_empty_list(self, df):
        result = _spend_by_category_core(df, "this month", top_n=5, today=TODAY)
        assert result == {"categories": [], "total": 0.0, "period_label": "August 2026"}


# ==========================================================================
# top_merchants
# ==========================================================================


class TestTopMerchants:
    def test_top_3_merchants_for_february_2026(self, df):
        # Hand-computed via an independent one-liner:
        #   feb.groupby('merchant').agg(total=('amount','sum'), count=('amount','size'))
        #      .sort_values('total', ascending=False)
        # gave: Booking.com 12456.22 (1 txn), IndiGo 7695.90 (1 txn),
        # Blinkit 7343.07 (4 txns), as the top 3.
        result = _top_merchants_core(df, "last month", top_n=3, today=date(2026, 3, 10))
        assert result == {
            "merchants": [
                {"name": "Booking.com", "total": 12456.22, "count": 1},
                {"name": "IndiGo", "total": 7695.90, "count": 1},
                {"name": "Blinkit", "total": 7343.07, "count": 4},
            ],
            "period_label": "February 2026",
        }

    def test_top_n_1(self, df):
        result = _top_merchants_core(df, "last month", top_n=1, today=date(2026, 3, 10))
        assert result["merchants"] == [{"name": "Booking.com", "total": 12456.22, "count": 1}]

    def test_period_with_no_data_returns_empty_list(self, df):
        result = _top_merchants_core(df, "this month", top_n=5, today=TODAY)
        assert result == {"merchants": [], "period_label": "August 2026"}


# ==========================================================================
# compare_periods
# ==========================================================================


class TestComparePeriods:
    def test_spike_month_vs_prior_month(self, df):
        # March 2026 is generate_data.py's deliberate "genuine spend spike"
        # month. Hand-computed via an independent one-liner:
        #   mar.amount.sum() = 168254.45 ; feb.amount.sum() = 115399.39
        #   delta = 168254.45 - 115399.39 = 52855.06
        #   pct_change = 52855.06 / 115399.39 * 100 = 45.80
        result = _compare_periods_core(
            df, "March 2026", "February 2026", category=None, today=TODAY
        )
        assert result == {
            "total_a": 168254.45,
            "total_b": 115399.39,
            "delta": 52855.06,
            "pct_change": 45.8,
            "direction": "up",
            "labels": {"a": "March 2026", "b": "February 2026"},
        }

    def test_category_filtered_comparison(self, df):
        # Hand-computed: mar[mar.category=='food_dining'].amount.sum() =
        # 15300.02 ; feb[...].amount.sum() = 10526.80 ; delta = 4773.22 ;
        # pct_change = 4773.22 / 10526.80 * 100 = 45.34.
        result = _compare_periods_core(
            df, "March 2026", "February 2026", category="food_dining", today=TODAY
        )
        assert result == {
            "total_a": 15300.02,
            "total_b": 10526.80,
            "delta": 4773.22,
            "pct_change": 45.34,
            "direction": "up",
            "labels": {"a": "March 2026", "b": "February 2026"},
        }

    def test_zero_baseline_gives_none_pct_change(self, df):
        # Hand: "this month" (August 2026, relative to TODAY) has zero
        # rows in the frozen dataset, so total_b == 0 while total_a
        # (July 2026, 122048.88) is nonzero -> percent change from a zero
        # baseline is undefined, not a fabricated number.
        result = _compare_periods_core(
            df, "last month", "this month", category=None, today=TODAY
        )
        assert result == {
            "total_a": 122048.88,
            "total_b": 0.0,
            "delta": 122048.88,
            "pct_change": None,
            "direction": "up",
            "labels": {"a": "July 2026", "b": "August 2026"},
        }


# ==========================================================================
# find_transactions
# ==========================================================================


class TestFindTransactions:
    def test_merchant_filter_only_caps_at_5_but_reports_true_count(self, df):
        # Hand-computed via an independent one-liner:
        #   df[df.merchant.str.contains('swiggy', case=False)] has 83 rows
        #   total; sorted by timestamp descending, the 5 most recent are:
        #   2026-06-24 166.94, 2026-06-15 500.00, 2026-06-13 295.74,
        #   2026-06-11 539.00, 2026-05-14 310.00.
        result = _find_transactions_core(
            df, merchant="swiggy", date_phrase=None, min_amount=None, period=None, today=TODAY
        )
        assert result["count"] == 83
        assert result["matches"] == [
            {"date": "2026-06-24", "merchant": "Swiggy", "amount": 166.94},
            {"date": "2026-06-15", "merchant": "Swiggy", "amount": 500.0},
            {"date": "2026-06-13", "merchant": "Swiggy", "amount": 295.74},
            {"date": "2026-06-11", "merchant": "Swiggy", "amount": 539.0},
            {"date": "2026-05-14", "merchant": "Swiggy", "amount": 310.0},
        ]

    def test_merchant_and_date_finds_the_synthetic_duplicate_charge(self, df):
        # Hand-computed: generate_data.py's dedicated duplicate-charge
        # scenario. Direct filter on the loaded frame:
        #   df[(df.merchant=="McDonald's") & (df.timestamp.dt.date == date(2025,5,28))]
        # gives exactly 3 rows: 460.0 @ 11:23:59, 460.0 @ 13:08:59 (the
        # duplicate pair), and 280.0 @ 14:31:24.
        result = _find_transactions_core(
            df,
            merchant="McDonald's",
            date_phrase="2025-05-28",
            min_amount=None,
            period=None,
            today=TODAY,
        )
        assert result["count"] == 3
        assert result["matches"] == [
            {"date": "2025-05-28", "merchant": "McDonald's", "amount": 280.0},
            {"date": "2025-05-28", "merchant": "McDonald's", "amount": 460.0},
            {"date": "2025-05-28", "merchant": "McDonald's", "amount": 460.0},
        ]

    def test_min_amount_filter_finds_the_big_ticket_rows(self, df):
        # Hand-computed: df[df.amount >= 20000] has exactly 2 rows across
        # the whole 18-month history — the EMI-conversion original
        # purchase (Croma, 35988.0 on 2025-06-15) and the spike-month
        # Croma purchase (24000.0 on 2026-03-14).
        result = _find_transactions_core(
            df, merchant=None, date_phrase=None, min_amount=20000, period=None, today=TODAY
        )
        assert result["count"] == 2
        assert result["matches"] == [
            {"date": "2026-03-14", "merchant": "Croma", "amount": 24000.0},
            {"date": "2025-06-15", "merchant": "Croma", "amount": 35988.0},
        ]

    def test_merchant_and_period_with_no_matches(self, df):
        # Hand-computed: there is no Swiggy transaction in July 2026 at
        # all (verified by direct inspection of the loaded frame), so this
        # combination of filters must return an empty, not a guessed,
        # result.
        result = _find_transactions_core(
            df, merchant="swiggy", date_phrase=None, min_amount=None, period="last month", today=TODAY
        )
        assert result == {"matches": [], "count": 0}

    def test_unparseable_date_raises(self, df):
        with pytest.raises(ValueError):
            _find_transactions_core(
                df,
                merchant=None,
                date_phrase="whenever, basically",
                min_amount=None,
                period=None,
                today=TODAY,
            )


# ==========================================================================
# recurring_charges
# ==========================================================================


class TestRecurringCharges:
    def test_detects_exactly_the_six_synthetic_subscriptions(self, df):
        # Hand-computed via an independent one-liner applying the same
        # documented rule (>=3 occurrences, amount within 10% of its own
        # min, median consecutive-charge interval 28-31 days) to each
        # merchant group of the loaded frame. Result: exactly the 6
        # merchants generate_data.py designates as SUBSCRIPTIONS, with
        # mean amounts (rounded 2dp) 648.40 / 118.93 / 399.47 / 2002.99 /
        # 299.23 / 130.53, sorted descending by amount, and last_charged
        # equal to each merchant's most recent 2026-07 occurrence.
        result = _recurring_charges_core(df)
        assert [s["merchant"] for s in result["subscriptions"]] == [
            "Cult.fit Membership",
            "Netflix",
            "Jio Postpaid",
            "Amazon Prime",
            "Google One",
            "Spotify Premium",
        ]
        assert result["subscriptions"] == [
            {
                "merchant": "Cult.fit Membership",
                "amount": 2002.99,
                "frequency": "monthly",
                "last_charged": "2026-07-10",
            },
            {
                "merchant": "Netflix",
                "amount": 648.40,
                "frequency": "monthly",
                "last_charged": "2026-07-05",
            },
            {
                "merchant": "Jio Postpaid",
                "amount": 399.47,
                "frequency": "monthly",
                "last_charged": "2026-07-03",
            },
            {
                "merchant": "Amazon Prime",
                "amount": 299.23,
                "frequency": "monthly",
                "last_charged": "2026-07-15",
            },
            {
                "merchant": "Google One",
                "amount": 130.53,
                "frequency": "monthly",
                "last_charged": "2026-07-20",
            },
            {
                "merchant": "Spotify Premium",
                "amount": 118.93,
                "frequency": "monthly",
                "last_charged": "2026-07-09",
            },
        ]
        # Hand: 2002.99 + 648.40 + 399.47 + 299.23 + 130.53 + 118.93 = 3599.55
        assert result["monthly_total"] == 3599.55

    def test_emi_installment_series_is_not_flagged_as_a_subscription(self, df):
        # Hand-reasoned from generate_data.py: the EMI conversion (Croma,
        # 12 monthly instalments of a fixed amount) is generated on the
        # SAME merchant name ("Croma") as Croma's ordinary, highly
        # variable one-off retail purchases (ranging roughly Rs.2,469 to
        # Rs.35,988 in the raw data). Because the recurring-charge rule
        # requires the *entire* merchant's amount history to sit within a
        # 10% band, that mix correctly fails the amount-consistency check,
        # so "Croma" must not appear in the detected subscriptions list
        # even though the EMI instalments alone are monthly and
        # same-amount.
        merchants_detected = {s["merchant"] for s in _recurring_charges_core(df)["subscriptions"]}
        assert "Croma" not in merchants_detected

    def test_exactly_six_subscriptions_detected(self, df):
        result = _recurring_charges_core(df)
        assert len(result["subscriptions"]) == 6


# ==========================================================================
# End-to-end wiring: the real @tool-decorated functions, real clock, real
# data loaded through data_loader.load_transactions() — this is the path
# S05's planner will actually call. Structural checks, not hand-computed
# numeric literals (see module docstring).
# ==========================================================================


class TestToolWrappersEndToEnd:
    def test_spend_total_invoke_loads_real_data_and_matches_shape(self):
        result = spend_total.invoke({"period": "last month"})
        assert set(result.keys()) == {"total", "count", "period_label", "avg_txn"}
        assert isinstance(result["total"], float)
        assert isinstance(result["count"], int)
        assert isinstance(result["period_label"], str)
        # The dataset is frozen through 2026-07-31, so as long as this
        # suite runs on or after 2026-08-01, "last month" always lands on
        # a populated month.
        assert result["count"] > 0
        assert result["total"] > 0

    def test_spend_by_category_invoke_shape_and_internal_consistency(self):
        result = spend_by_category.invoke({"period": "last month", "top_n": 3})
        assert set(result.keys()) == {"categories", "total", "period_label"}
        assert len(result["categories"]) <= 3
        for c in result["categories"]:
            assert set(c.keys()) == {"name", "total", "pct"}
        # Every returned category total must be a subset of the grand
        # total actually reachable via spend_total for the same period.
        grand = spend_total.invoke({"period": "last month"})
        assert result["total"] == grand["total"]

    def test_top_merchants_invoke_shape(self):
        result = top_merchants.invoke({"period": "last month", "top_n": 3})
        assert set(result.keys()) == {"merchants", "period_label"}
        assert len(result["merchants"]) <= 3
        totals = [m["total"] for m in result["merchants"]]
        assert totals == sorted(totals, reverse=True)  # ranked highest first

    def test_compare_periods_invoke_shape(self):
        result = compare_periods.invoke({"period_a": "last month", "period_b": "last 3 months"})
        assert set(result.keys()) == {
            "total_a", "total_b", "delta", "pct_change", "direction", "labels",
        }
        assert result["direction"] in ("up", "down", "flat")
        assert round(result["total_a"] - result["total_b"], 2) == result["delta"]

    def test_find_transactions_invoke_shape(self):
        result = find_transactions.invoke({"merchant": "Swiggy"})
        assert set(result.keys()) == {"matches", "count"}
        assert len(result["matches"]) <= 5
        assert result["count"] >= len(result["matches"])

    def test_recurring_charges_invoke_finds_the_six_subscriptions_via_real_clock(self):
        # recurring_charges takes no period argument, so this is fully
        # clock-independent and can assert the same literal as the
        # core-level test above.
        result = recurring_charges.invoke({})
        assert set(result.keys()) == {"subscriptions", "monthly_total"}
        assert len(result["subscriptions"]) == 6
        assert result["monthly_total"] == 3599.55
