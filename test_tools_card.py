"""Pytest suite for tools_card.py (S03B).

Every expected value here is hand-computed independently of the code under
test:

* card_rewards / card_fees / card_offers expectations are read directly off
  the literal values authored in card_terms.yaml (the test author wrote
  both files, so this is a transcription check, not a tautology -- the
  numbers below are typed out by hand, not produced by calling the tool
  and asserting its own output).
* rewards_earned's cap/refund/exclusion expectations are computed with a
  short, independent pandas one-liner (real-data cases) or worked out by
  hand on a small synthetic DataFrame (synthetic cases) -- never by calling
  `rewards_earned` and asserting what it returned.
* resolve_period expectations are worked out by hand against a fixed
  `today`.

Run with:  pytest test_tools_card.py -v
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

import tools_card as tc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def terms() -> dict:
    return tc.load_card_terms()


@pytest.fixture(scope="module")
def real_df() -> pd.DataFrame:
    """The actual canonical transaction DataFrame, loaded once per module."""
    return tc.load_transactions(str(tc.DEFAULT_MAPPING_PATH))


# ---------------------------------------------------------------------------
# card_terms.yaml <-> S01 canonical category cross-check
#
# The spec explicitly warns this must be verified against the real generated
# data, not eyeballed against spec text: a mismatched category key silently
# zeroes out reward calculations for that category.
# ---------------------------------------------------------------------------

def test_canonical_categories_match_generated_data(real_df):
    actual_categories = set(real_df["category"].unique())
    assert actual_categories == set(tc.CANONICAL_CATEGORIES), (
        "tools_card.CANONICAL_CATEGORIES must exactly match the category "
        "values actually present in the generated transaction data"
    )


def test_yaml_category_rate_keys_are_canonical_and_present_in_data(terms, real_df):
    actual_categories = set(real_df["category"].unique())
    cat_rate_keys = set(terms["rewards"]["category_rates"].keys())
    excluded_keys = set(terms["rewards"]["excluded_categories"])

    assert cat_rate_keys <= set(tc.CANONICAL_CATEGORIES)
    assert excluded_keys <= set(tc.CANONICAL_CATEGORIES)
    # every category_rates / excluded_categories key must be a category that
    # genuinely occurs in the data, or the entry is dead weight at best and
    # a typo'd no-op at worst
    assert cat_rate_keys <= actual_categories
    assert excluded_keys <= actual_categories
    # the 12 canonical categories are fully partitioned between explicit
    # rate overrides, exclusions, and base-rate fallback -- nothing is
    # silently missing
    fallback_categories = set(tc.CANONICAL_CATEGORIES) - cat_rate_keys - excluded_keys
    assert fallback_categories == {"shopping", "health", "education", "other"}


def test_deliberate_gap_charge_types_are_genuinely_absent(terms):
    """The 2-3 deliberate gaps must actually be absent, or the
    "admit a gap, don't fill it" test is unfalsifiable."""
    fees = terms["fees"]
    for gap in ("railway_surcharge", "wallet_load_fee", "balance_transfer_fee"):
        assert gap not in fees


# ---------------------------------------------------------------------------
# card_rewards
# ---------------------------------------------------------------------------

def test_card_rewards_no_category_returns_base_schedule(terms):
    r = tc._card_rewards_core(terms, None)
    assert r["found"] is True
    assert r["base_rate_points_per_100"] == 2
    assert r["rate_used_points_per_100"] == 2
    assert r["used_base_rate_fallback"] is True
    assert r["cap_points_per_month"] is None
    assert r["exclusions"] == ["cash_advance", "fees_interest"]
    assert r["redemption_value_inr_per_point"] == 0.25
    assert r["clause"] == (
        "You earn 2 reward points for every Rs. 100 spent on categories "
        "without a listed higher rate."
    )


def test_card_rewards_food_dining_rate_and_cap(terms):
    r = tc._card_rewards_core(terms, "food_dining")
    assert r["found"] is True
    assert r["category_rate_points_per_100"] == 5
    assert r["rate_used_points_per_100"] == 5
    assert r["used_base_rate_fallback"] is False
    assert r["cap_points_per_month"] == 2000
    assert r["excluded"] is False
    assert r["clause"] == (
        "You earn 5 reward points for every Rs. 100 spent on dining and "
        "food delivery, capped at 2,000 bonus points per calendar month."
    )


def test_card_rewards_fuel_has_surcharge_waiver_note(terms):
    r = tc._card_rewards_core(terms, "fuel")
    assert r["rate_used_points_per_100"] == 1
    assert r["cap_points_per_month"] is None  # fuel has no points cap
    assert r["note"] == (
        "A 1% fuel surcharge, up to Rs. 200 per statement cycle, is waived "
        "on fuel transactions between Rs. 400 and Rs. 4,000."
    )


@pytest.mark.parametrize("category", ["shopping", "health", "education", "other"])
def test_card_rewards_falls_back_to_base_rate(terms, category):
    r = tc._card_rewards_core(terms, category)
    assert r["found"] is True
    assert r["category_rate_points_per_100"] is None
    assert r["rate_used_points_per_100"] == 2  # == base rate
    assert r["used_base_rate_fallback"] is True
    assert r["excluded"] is False


@pytest.mark.parametrize("category", ["cash_advance", "fees_interest"])
def test_card_rewards_excluded_categories_earn_nothing(terms, category):
    r = tc._card_rewards_core(terms, category)
    assert r["found"] is True
    assert r["excluded"] is True
    assert r["rate_used_points_per_100"] == 0
    assert r["clause"] == "Cash advances and fee or interest charges do not earn reward points."


def test_card_rewards_unknown_category_not_found(terms):
    r = tc._card_rewards_core(terms, "not_a_real_category")
    assert r == {
        "found": False,
        "requested": "not_a_real_category",
        "available_categories": tc.CANONICAL_CATEGORIES,
    }


def test_card_rewards_tool_invoke_smoke():
    r = tc.card_rewards.invoke({"category": "groceries"})
    assert r["rate_used_points_per_100"] == 3
    assert r["cap_points_per_month"] == 1500


# ---------------------------------------------------------------------------
# card_fees
# ---------------------------------------------------------------------------

def test_card_fees_annual(terms):
    r = tc._card_fees_core(terms, "annual")
    assert r["found"] is True
    assert r["amount_or_pct"] == 2500
    assert r["currency"] == "INR"
    assert r["waiver_condition"] == "Waived if you spend Rs. 3,00,000 or more in a card year."
    assert r["clause"] == (
        "An annual fee of Rs. 2,500 plus applicable taxes is charged each "
        "card year, waived if you spend Rs. 3,00,000 or more in that card year."
    )


def test_card_fees_forex_markup(terms):
    r = tc._card_fees_core(terms, "forex_markup")
    assert r["found"] is True
    assert r["amount_or_pct"] == 3.5
    assert r["clause"] == (
        "A currency conversion markup of 3.5% applies to all transactions "
        "billed in a currency other than Indian Rupees."
    )


def test_card_fees_late_payment_is_tiered(terms):
    r = tc._card_fees_core(terms, "late_payment")
    assert r["found"] is True
    assert r["amount_or_pct"] is None
    assert len(r["tiers"]) == 4
    assert r["tiers"][0]["amount_inr"] == 0
    assert r["tiers"][1]["amount_inr"] == 500
    assert r["tiers"][2]["amount_inr"] == 750
    assert r["tiers"][3]["amount_inr"] == 1200
    assert r["tiers"][3]["max_due_inr"] is None


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("annual_fee", "annual"),
        ("late_fee", "late_payment"),
        ("forex", "forex_markup"),
        ("cash_advance", "cash_advance_fee"),
        ("overlimit_fee", "over_limit"),
        ("Foreclosure Fee", "emi_foreclosure"),
    ],
)
def test_card_fees_aliases_resolve(terms, alias, canonical):
    r = tc._card_fees_core(terms, alias)
    assert r["found"] is True
    assert r["fee_type"] == canonical


def test_card_fees_no_arg_returns_full_schedule(terms):
    r = tc._card_fees_core(terms, None)
    assert r["found"] is True
    assert r["fee_type"] is None
    assert r["count"] == 12
    fee_types = {f["fee_type"] for f in r["fees"]}
    assert fee_types == {
        "annual", "joining", "forex_markup", "late_payment",
        "cash_advance_fee", "cash_advance_finance_charge", "over_limit",
        "emi_processing", "emi_foreclosure", "card_replacement",
        "cheque_bounce", "reward_redemption",
    }


@pytest.mark.parametrize(
    "gap_fee_type",
    ["railway_surcharge", "wallet_load_fee", "balance_transfer_fee"],
)
def test_card_fees_missing_term_returns_found_false(terms, gap_fee_type):
    """The 'admit a gap, don't fill it' contract: never an empty dict,
    always found:False plus what IS available."""
    r = tc._card_fees_core(terms, gap_fee_type)
    assert r == {
        "found": False,
        "requested": gap_fee_type,
        "available_fee_types": sorted(terms["fees"].keys()),
    }
    assert r["found"] is False
    assert r != {}


def test_card_fees_tool_invoke_smoke():
    r = tc.card_fees.invoke({"fee_type": "cheque_bounce"})
    assert r["found"] is True
    assert r["amount_or_pct"] == 500


# ---------------------------------------------------------------------------
# card_offers
# ---------------------------------------------------------------------------

FIXED_TODAY = date(2026, 8, 11)  # matches this project's fixed "today"


def test_card_offers_filter_by_merchant_case_insensitive(terms):
    r = tc._card_offers_core(terms, "SWIGGY", None, FIXED_TODAY)
    assert r["count"] == 1
    assert r["offers"][0]["merchant"] == "Swiggy"
    assert r["offers"][0]["benefit"] == "10% instant discount up to Rs. 150 on orders above Rs. 499."
    assert r["offers"][0]["is_active"] is True


def test_card_offers_filter_by_category(terms):
    r = tc._card_offers_core(terms, None, "shopping", FIXED_TODAY)
    assert r["count"] == 2
    merchants = {o["merchant"] for o in r["offers"]}
    assert merchants == {"Myntra", "Amazon"}


def test_card_offers_expired_offer_marked_inactive_not_removed(terms):
    r = tc._card_offers_core(terms, "PVR", None, FIXED_TODAY)
    assert r["count"] == 1  # still returned
    assert r["offers"][0]["valid_until"] == "2026-07-31"
    assert r["offers"][0]["is_active"] is False  # but marked expired


def test_card_offers_active_offer_marked_active(terms):
    r = tc._card_offers_core(terms, "BigBasket", None, FIXED_TODAY)
    assert r["offers"][0]["is_active"] is True


def test_card_offers_no_match_returns_empty_not_error(terms):
    r = tc._card_offers_core(terms, "some merchant that does not exist", None, FIXED_TODAY)
    assert r == {"offers": [], "count": 0}


def test_card_offers_tool_invoke_smoke():
    r = tc.card_offers.invoke({"merchant": "apollo"})
    assert r["count"] == 1
    assert r["offers"][0]["category"] == "health"


# ---------------------------------------------------------------------------
# resolve_period
# ---------------------------------------------------------------------------

TODAY = date(2026, 8, 11)  # a Tuesday


def test_resolve_period_last_month():
    assert tc.resolve_period("last month", TODAY) == (
        date(2026, 7, 1), date(2026, 7, 31), "July 2026"
    )


def test_resolve_period_this_month():
    assert tc.resolve_period("this month", TODAY) == (
        date(2026, 8, 1), date(2026, 8, 11), "August 2026"
    )


def test_resolve_period_last_week():
    # Aug 11 2026 is a Tuesday (weekday()==1); this week starts Mon Aug 10;
    # last week is Mon Aug 3 - Sun Aug 9.
    assert tc.resolve_period("last week", TODAY) == (
        date(2026, 8, 3), date(2026, 8, 9), "2026-08-03 to 2026-08-09"
    )


def test_resolve_period_this_week():
    assert tc.resolve_period("this week", TODAY) == (
        date(2026, 8, 10), date(2026, 8, 11), "2026-08-10 to 2026-08-11"
    )


def test_resolve_period_last_year():
    assert tc.resolve_period("last year", TODAY) == (
        date(2025, 1, 1), date(2025, 12, 31), "2025"
    )


def test_resolve_period_ytd():
    assert tc.resolve_period("YTD", TODAY) == (
        date(2026, 1, 1), date(2026, 8, 11), "YTD 2026"
    )


def test_resolve_period_last_n_months():
    # last month = July 2026; "last 3 months" -> May, Jun, Jul 2026
    assert tc.resolve_period("last 3 months", TODAY) == (
        date(2026, 5, 1), date(2026, 7, 31), "Last 3 months (May 2026–Jul 2026)"
    )


def test_resolve_period_named_month():
    assert tc.resolve_period("October 2025", TODAY) == (
        date(2025, 10, 1), date(2025, 10, 31), "October 2025"
    )
    assert tc.resolve_period("Oct 2025", TODAY) == (
        date(2025, 10, 1), date(2025, 10, 31), "October 2025"
    )


def test_resolve_period_iso_month():
    assert tc.resolve_period("2025-10", TODAY) == (
        date(2025, 10, 1), date(2025, 10, 31), "October 2025"
    )


def test_resolve_period_quarter_named():
    assert tc.resolve_period("Q4 2025", TODAY) == (
        date(2025, 10, 1), date(2025, 12, 31), "Q4 2025"
    )


def test_resolve_period_this_quarter_capped_at_today():
    # Aug 2026 is in Q3 2026 (Jul-Sep); "this quarter" must not run past today
    assert tc.resolve_period("this quarter", TODAY) == (
        date(2026, 7, 1), date(2026, 8, 11), "Q3 2026"
    )


def test_resolve_period_last_quarter():
    assert tc.resolve_period("last quarter", TODAY) == (
        date(2026, 4, 1), date(2026, 6, 30), "Q2 2026"
    )


def test_resolve_period_explicit_range():
    assert tc.resolve_period("2025-10-01 to 2025-12-31", TODAY) == (
        date(2025, 10, 1), date(2025, 12, 31), "2025-10-01 to 2025-12-31"
    )


def test_resolve_period_explicit_single_date():
    assert tc.resolve_period("2025-10-14", TODAY) == (
        date(2025, 10, 14), date(2025, 10, 14), "2025-10-14"
    )


def test_resolve_period_unparseable_raises():
    with pytest.raises(ValueError):
        tc.resolve_period("sometime soonish", TODAY)


# ---------------------------------------------------------------------------
# rewards_earned -- synthetic DataFrame tests (fully hand-computed)
# ---------------------------------------------------------------------------

def _mk_row(day, category, amount, merchant="M"):
    return {
        "txn_id": f"T{day}{category}{amount}",
        "timestamp": pd.Timestamp(day),
        "amount": amount,
        "merchant": merchant,
        "category": category,
        "card_id": "XXXX4412",
    }


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    rows = [
        # food_dining, Jan 2026: 30000 + 20000 purchase, 5000 refund
        # net = 45000 -> raw points floor(45000/100*5) = 2250 -> capped at 2000
        _mk_row("2026-01-05", "food_dining", 30000.0),
        _mk_row("2026-01-12", "food_dining", 20000.0),
        _mk_row("2026-01-20", "food_dining", -5000.0),
        # food_dining, Feb 2026: 50000 purchase, no refund
        # net = 50000 -> raw points floor(50000/100*5) = 2500 -> capped at 2000
        _mk_row("2026-02-03", "food_dining", 50000.0),
        # groceries, Jan 2026: 10000 purchase, rate 3/100, cap 1500
        # net = 10000 -> points floor(10000/100*3) = 300 -> under cap
        _mk_row("2026-01-08", "groceries", 10000.0),
        # cash_advance (excluded), Jan 2026
        _mk_row("2026-01-15", "cash_advance", 5000.0),
        # fees_interest (excluded), Jan 2026
        _mk_row("2026-01-16", "fees_interest", 800.0),
        # entertainment, Jan 2026: 100 purchase, 150 refund -> net -50,
        # floored to 0 eligible spend -> 0 points (no cap on this category)
        _mk_row("2026-01-10", "entertainment", 100.0),
        _mk_row("2026-01-11", "entertainment", -150.0),
        # shopping (base-rate fallback, rate 2/100), Jan 2026
        _mk_row("2026-01-09", "shopping", 1000.0),
    ]
    return pd.DataFrame(rows)


def test_rewards_earned_cap_hit_synthetic(synthetic_df, terms):
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 1, 31), "January 2026",
        category="food_dining",
    )
    assert r["by_category"]["food_dining"] == 2000  # capped, not 2250
    assert r["points_total"] == 2000
    assert len(r["capped_categories"]) == 1
    cap_row = r["capped_categories"][0]
    assert cap_row["month"] == "2026-01"
    assert cap_row["capped_points"] == 2000
    assert cap_row["uncapped_points_would_be"] == 2250
    assert cap_row["eligible_spend_inr"] == 45000.0  # net of the 5000 refund


def test_rewards_earned_cap_not_hit_synthetic(synthetic_df, terms):
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 1, 31), "January 2026",
        category="groceries",
    )
    assert r["by_category"]["groceries"] == 300
    assert r["points_total"] == 300
    assert r["capped_categories"] == []  # cap of 1500 not reached


def test_rewards_earned_multi_month_cap_applies_independently(synthetic_df, terms):
    """Jan and Feb both breach the dining cap; the cap must apply in BOTH
    months, not once across the combined two-month period."""
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 2, 28), "Jan-Feb 2026",
        category="food_dining",
    )
    assert r["points_total"] == 4000  # 2000 (Jan) + 2000 (Feb), NOT one shared cap
    assert len(r["capped_categories"]) == 2
    months_capped = {c["month"] for c in r["capped_categories"]}
    assert months_capped == {"2026-01", "2026-02"}
    for c in r["capped_categories"]:
        assert c["capped_points"] == 2000


def test_rewards_earned_excluded_category_earns_zero(synthetic_df, terms):
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 1, 31), "January 2026",
        category="cash_advance",
    )
    assert r["points_total"] == 0
    assert r["by_category"] == {"cash_advance": 0}
    assert r["excluded_spend"] == 5000.0
    assert r["category_excluded"] is True


def test_rewards_earned_refund_netted_and_floored_at_zero(synthetic_df, terms):
    """entertainment: 100 purchase, 150 refund in the same month -> net -50,
    which must floor to 0 eligible spend (never negative points)."""
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 1, 31), "January 2026",
        category="entertainment",
    )
    assert r["points_total"] == 0
    assert r["by_category"].get("entertainment", 0) == 0
    assert r["capped_categories"] == []


def test_rewards_earned_base_rate_fallback_synthetic(synthetic_df, terms):
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 1, 31), "January 2026",
        category="shopping",
    )
    assert r["by_category"]["shopping"] == 20  # floor(1000/100*2)


def test_rewards_earned_all_categories_combined_synthetic(synthetic_df, terms):
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 1, 31), "January 2026",
        category=None,
    )
    # food_dining capped 2000 + groceries 300 + entertainment 0 + shopping 20
    # (cash_advance/fees_interest excluded entirely from points_total)
    assert r["points_total"] == 2000 + 300 + 0 + 20
    assert r["excluded_spend"] == 5000.0 + 800.0
    assert r["redemption_value_inr"] == round((2000 + 300 + 0 + 20) * 0.25, 2)


def test_rewards_earned_unknown_category_not_found(synthetic_df, terms):
    r = tc._rewards_earned_core(
        synthetic_df, terms, date(2026, 1, 1), date(2026, 1, 31), "January 2026",
        category="not_a_category",
    )
    assert r["found"] is False
    assert r["requested_category"] == "not_a_category"


def test_rewards_earned_empty_period_returns_zeroes(terms):
    empty_df = pd.DataFrame(columns=["timestamp", "amount", "category"])
    empty_df["timestamp"] = pd.to_datetime(empty_df["timestamp"])
    r = tc._rewards_earned_core(
        empty_df, terms, date(2030, 1, 1), date(2030, 1, 31), "January 2030",
    )
    assert r["points_total"] == 0
    assert r["by_category"] == {}
    assert r["capped_categories"] == []
    assert r["excluded_spend"] == 0.0
    assert r["transaction_count"] == 0


# ---------------------------------------------------------------------------
# rewards_earned -- real-data integration tests
#
# Expected values are computed with an independent pandas one-liner here,
# not by calling the tool. This is the end-to-end proof that S01's real
# dining-cap-breach months (Oct/Nov 2025, engineered against the SAME
# 5-points-per-100 / 2000-point reference the yaml also uses) actually
# breach the cap through this code path, not just in a synthetic fixture.
# ---------------------------------------------------------------------------

def _independent_net_spend(df, category, start, end):
    mask = (
        (df["timestamp"].dt.date >= start)
        & (df["timestamp"].dt.date <= end)
        & (df["category"] == category)
    )
    return float(df.loc[mask, "amount"].sum())


def test_rewards_earned_real_data_october_2025_dining_cap_hit(real_df, terms):
    expected_net_spend = _independent_net_spend(
        real_df, "food_dining", date(2025, 10, 1), date(2025, 10, 31)
    )
    expected_raw_points = math.floor(expected_net_spend / 100 * 5)
    assert expected_raw_points > 2000, "fixture assumption: Oct 2025 must breach the cap"

    r = tc._rewards_earned_core(
        real_df, terms, date(2025, 10, 1), date(2025, 10, 31), "October 2025",
        category="food_dining",
    )
    assert r["points_total"] == 2000
    assert r["by_category"]["food_dining"] == 2000
    assert len(r["capped_categories"]) == 1
    assert r["capped_categories"][0]["uncapped_points_would_be"] == expected_raw_points
    assert r["capped_categories"][0]["eligible_spend_inr"] == round(expected_net_spend, 2)


def test_rewards_earned_real_data_july_2025_dining_cap_not_hit(real_df, terms):
    expected_net_spend = _independent_net_spend(
        real_df, "food_dining", date(2025, 7, 1), date(2025, 7, 31)
    )
    expected_points = math.floor(expected_net_spend / 100 * 5)
    assert expected_points < 2000, "fixture assumption: Jul 2025 must be under the cap"

    r = tc._rewards_earned_core(
        real_df, terms, date(2025, 7, 1), date(2025, 7, 31), "July 2025",
        category="food_dining",
    )
    assert r["points_total"] == expected_points
    assert r["capped_categories"] == []


def test_rewards_earned_real_data_q4_2025_multi_month_cap(real_df, terms):
    """Q4 2025 spans Oct (breach), Nov (breach), Dec (no breach) -- the cap
    must fire independently in Oct and Nov, worth 2000 each, not once
    across the quarter."""
    oct_net = _independent_net_spend(real_df, "food_dining", date(2025, 10, 1), date(2025, 10, 31))
    nov_net = _independent_net_spend(real_df, "food_dining", date(2025, 11, 1), date(2025, 11, 30))
    dec_net = _independent_net_spend(real_df, "food_dining", date(2025, 12, 1), date(2025, 12, 31))
    oct_pts, nov_pts, dec_pts = (math.floor(n / 100 * 5) for n in (oct_net, nov_net, dec_net))
    assert oct_pts > 2000 and nov_pts > 2000 and dec_pts < 2000  # fixture assumptions

    expected_total = 2000 + 2000 + dec_pts

    r = tc._rewards_earned_core(
        real_df, terms, date(2025, 10, 1), date(2025, 12, 31), "Q4 2025",
        category="food_dining",
    )
    assert r["points_total"] == expected_total
    assert len(r["capped_categories"]) == 2
    assert {c["month"] for c in r["capped_categories"]} == {"2025-10", "2025-11"}


def test_rewards_earned_real_data_excluded_category(real_df, terms):
    expected_ca_net = _independent_net_spend(real_df, "cash_advance", date(2026, 1, 1), date(2026, 3, 31))
    r = tc._rewards_earned_core(
        real_df, terms, date(2026, 1, 1), date(2026, 3, 31), "Q1 2026",
        category="cash_advance",
    )
    assert r["points_total"] == 0
    assert r["by_category"] == {"cash_advance": 0}
    assert r["excluded_spend"] == round(expected_ca_net, 2)


def test_rewards_earned_tool_invoke_smoke():
    r = tc.rewards_earned.invoke({"period": "October 2025", "category": "food_dining"})
    assert r["found"] is True
    assert r["points_total"] == 2000
    assert r["period_label"] == "October 2025"
