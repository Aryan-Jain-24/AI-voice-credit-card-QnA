"""Card terms and rewards tools — S03B.

card_rewards, card_fees, card_offers, rewards_earned (the cross-domain tool).

The one rule every function in this file obeys: **the LLM never recalls a
card term, it only looks one up.** Every rate, fee, cap, and offer returned
by these four tools is read from ``card_terms.yaml`` at call time — nothing
is hardcoded, cached stale, or synthesized from what a "typical" card might
charge. If a requested term is not in the file, the tool says so
(``found: False``) instead of returning something plausible.

Design notes worth knowing before editing this file:

* Every public tool is a thin ``@tool``-decorated wrapper around a private
  ``_..._core`` function that takes plain data (a parsed terms dict, a
  DataFrame, an explicit ``today``) instead of reaching out to disk/the
  clock itself. Tests call the ``_core`` functions directly with
  hand-built inputs, and the public tools separately for integration-level
  checks against the real ``card_terms.yaml`` and ``data/transactions.csv``.
  This is what makes "hand-computed expectations" possible without
  monkeypatching the filesystem or the system clock.

* ``card_terms.yaml`` is read fresh (not cached) on every call. It is a
  couple of KB; the cost is negligible, and it guarantees the tools can
  never serve a stale term after the file is edited mid-session.

* ``rewards_earned`` resolves its own ``period`` phrases via a small
  ``resolve_period(phrase, today) -> (start, end, label)`` implemented in
  this module. It intentionally does NOT import ``resolve_period`` from
  ``tools_txn.py``: that module (owned by ``txn-tools-builder``) was being
  built in parallel with this one, so tools_card.py carries its own small,
  independently-tested copy of the same contract described in S03 rather
  than taking a hard dependency on code that may not exist yet. If S05
  wants a single shared resolver, consolidating the two later is a small,
  low-risk refactor — they are written to the same (phrase, today) ->
  (start, end, label) contract on purpose.

* Refund handling in ``rewards_earned`` (see its docstring for the full
  order of operations): refunds are **netted off**, not excluded outright.
  A refund (negative ``amount``) subtracts from that category's spend in
  the calendar month it posts, before rates/caps are applied, and net
  eligible spend per category per month is floored at 0 — a category can
  never earn negative points even in a month where refunds outweigh
  purchases.

See all-specs.md S03B and .claude/agents/card-terms-builder.md.
"""

from __future__ import annotations

import calendar
import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml
from langchain_core.tools import tool

from data_loader import load_transactions

# ---------------------------------------------------------------------------
# Paths & canonical categories
# ---------------------------------------------------------------------------

_MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_CARD_TERMS_PATH = _MODULE_DIR / "card_terms.yaml"
DEFAULT_MAPPING_PATH = _MODULE_DIR / "mapping.yaml"

# The 12 canonical categories, verbatim from generate_data.py (S01). Kept as
# a local literal (not imported from generate_data.py) so this module has no
# import-time dependency on the data generator, but test_tools_card.py
# cross-checks this list against the actual `category` values found in
# data/transactions.csv — a mismatch there is exactly the "silently zeroes
# out reward calculations" bug the spec warns about, and it must be caught
# by a test, not by eyeballing.
CANONICAL_CATEGORIES: list[str] = [
    "food_dining",
    "groceries",
    "fuel",
    "travel",
    "shopping",
    "entertainment",
    "utilities",
    "health",
    "education",
    "cash_advance",
    "fees_interest",
    "other",
]

# Common alternate phrasings for fee_type -> the actual key under
# card_terms.yaml's `fees:` block. Purely a convenience lookup; every value
# on the right must be a real key in the yaml, so this can never cause a
# term to be invented — it only widens which planner phrasings resolve to
# an existing entry.
FEE_TYPE_ALIASES: dict[str, str] = {
    "annual_fee": "annual",
    "joining_fee": "joining",
    "membership_fee": "joining",
    "forex": "forex_markup",
    "fx_markup": "forex_markup",
    "foreign_transaction": "forex_markup",
    "foreign_transaction_fee": "forex_markup",
    "late_fee": "late_payment",
    "late_payment_fee": "late_payment",
    "cash_advance": "cash_advance_fee",
    "cash_withdrawal_fee": "cash_advance_fee",
    "cash_advance_interest": "cash_advance_finance_charge",
    "cash_advance_interest_rate": "cash_advance_finance_charge",
    "overlimit": "over_limit",
    "over_limit_fee": "over_limit",
    "overlimit_fee": "over_limit",
    "emi_processing_fee": "emi_processing",
    "foreclosure": "emi_foreclosure",
    "foreclosure_fee": "emi_foreclosure",
    "emi_foreclosure_fee": "emi_foreclosure",
    "card_replacement_fee": "card_replacement",
    "duplicate_card_fee": "card_replacement",
    "replacement_fee": "card_replacement",
    "cheque_bounce_fee": "cheque_bounce",
    "auto_debit_reversal": "cheque_bounce",
    "auto_debit_reversal_fee": "cheque_bounce",
    "redemption_fee": "reward_redemption",
    "reward_redemption_fee": "reward_redemption",
}


# ---------------------------------------------------------------------------
# card_terms.yaml loading
# ---------------------------------------------------------------------------

def load_card_terms(path: str | Path | None = None) -> dict[str, Any]:
    """Read and parse card_terms.yaml fresh from disk.

    Deliberately uncached: the file is small, so re-reading it on every tool
    call costs nothing and guarantees a tool can never answer from a stale
    in-memory copy after the file changes.
    """
    p = Path(path) if path is not None else DEFAULT_CARD_TERMS_PATH
    with p.open("r", encoding="utf-8") as f:
        terms = yaml.safe_load(f) or {}
    return terms


# ---------------------------------------------------------------------------
# card_rewards
# ---------------------------------------------------------------------------

def _card_rewards_core(terms: dict[str, Any], category: str | None) -> dict[str, Any]:
    rewards = terms.get("rewards", {})
    base = rewards.get("base_rate", {})
    base_rate = base.get("points_per_100")
    base_clause = base.get("clause")
    exclusions = list(rewards.get("excluded_categories", []))
    exclusions_clause = rewards.get("excluded_categories_clause")
    redemption = rewards.get("redemption", {})
    redemption_value = redemption.get("value_per_point_inr")
    redemption_clause = redemption.get("clause")

    result: dict[str, Any] = {
        "found": True,
        "category": category,
        "base_rate_points_per_100": base_rate,
        "base_rate_clause": base_clause,
        "category_rate_points_per_100": None,
        "rate_used_points_per_100": base_rate,
        "used_base_rate_fallback": category is None,
        "cap_points_per_month": None,
        "cap_clause": None,
        "excluded": False,
        "exclusions": exclusions,
        "redemption_value_inr_per_point": redemption_value,
        "redemption_clause": redemption_clause,
        "clause": base_clause,
        "note": None,
    }

    if category is None:
        return result

    if category not in CANONICAL_CATEGORIES:
        return {
            "found": False,
            "requested": category,
            "available_categories": list(CANONICAL_CATEGORIES),
        }

    if category in exclusions:
        result.update(
            {
                "excluded": True,
                "rate_used_points_per_100": 0,
                "used_base_rate_fallback": False,
                "clause": exclusions_clause,
            }
        )
        return result

    cat_entry = rewards.get("category_rates", {}).get(category)
    if cat_entry:
        rate = cat_entry.get("points_per_100")
        cap = cat_entry.get("monthly_cap_points")
        result.update(
            {
                "category_rate_points_per_100": rate,
                "rate_used_points_per_100": rate,
                "used_base_rate_fallback": False,
                "cap_points_per_month": cap,
                "cap_clause": cat_entry.get("clause") if cap is not None else None,
                "clause": cat_entry.get("clause", base_clause),
                "note": cat_entry.get("surcharge_waiver_clause"),
            }
        )
    # else: category has no override in category_rates -> falls back to the
    # base rate, and `result` already reflects that (used_base_rate_fallback
    # stays False above only because we default it to `category is None`; a
    # category WAS given here, so mark the fallback explicitly).
    else:
        result["used_base_rate_fallback"] = True

    return result


@tool
def card_rewards(category: str | None = None) -> dict[str, Any]:
    """Look up this card's reward-EARNING SCHEDULE from card_terms.yaml.

    Use for questions about what the card pays for spending: "what's the
    reward rate on dining?", "is there a cap on groceries points?", "what
    do I earn on fuel?", "what's the base reward rate?". This is the
    SCHEDULE, not the user's history — for "how many points did I earn" or
    "am I close to the dining cap this month" (applying the schedule to
    actual transactions), use `rewards_earned` instead.

    Args:
        category: one of the 12 canonical categories, e.g. "food_dining",
            "fuel", "travel". Omit for the card's general/base reward rate
            plus the list of excluded categories.

    Returns a flat dict including: base_rate_points_per_100,
    category_rate_points_per_100 (None if this category has no override and
    falls back to the base rate), rate_used_points_per_100 (the effective
    rate to quote for `category`), used_base_rate_fallback,
    cap_points_per_month, excluded (True for cash_advance/fees_interest,
    which never earn points), exclusions, redemption_value_inr_per_point,
    and `clause` — the exact sentence to speak. If `category` is not one of
    the 12 canonical categories, returns {"found": False, ...} rather than
    guessing.
    """
    terms = load_card_terms()
    return _card_rewards_core(terms, category)


# ---------------------------------------------------------------------------
# card_fees
# ---------------------------------------------------------------------------

def _summarize_fee(key: str, entry: Any) -> dict[str, Any]:
    """Flatten one `fees:` entry into the tool's return shape.

    Every field here is read straight off the yaml entry — nothing is
    synthesized or paraphrased. `late_payment` is a list of tiers rather
    than a single scalar fee, so it is handled separately.
    """
    if isinstance(entry, list):  # tiered, e.g. late_payment
        return {
            "fee_type": key,
            "amount_or_pct": None,
            "tiers": entry,
            "waiver_condition": None,
            "clause": " ".join(t.get("clause", "") for t in entry).strip(),
        }
    amount_or_pct = entry.get("amount_inr")
    if amount_or_pct is None:
        amount_or_pct = entry.get("pct", entry.get("pct_per_month"))
    return {
        "fee_type": key,
        "amount_or_pct": amount_or_pct,
        "currency": entry.get("currency", "INR" if "amount_inr" in entry else None),
        "waiver_condition": entry.get("waiver_condition"),
        "clause": entry.get("clause"),
    }


def _card_fees_core(terms: dict[str, Any], fee_type: str | None) -> dict[str, Any]:
    fees = terms.get("fees", {})

    if fee_type is None:
        listing = [_summarize_fee(key, entry) for key, entry in fees.items()]
        return {"found": True, "fee_type": None, "fees": listing, "count": len(listing)}

    key = fee_type.strip().lower().replace(" ", "_").replace("-", "_")
    key = FEE_TYPE_ALIASES.get(key, key)

    if key not in fees:
        return {
            "found": False,
            "requested": fee_type,
            "available_fee_types": sorted(fees.keys()),
        }

    return {"found": True, **_summarize_fee(key, fees[key])}


@tool
def card_fees(fee_type: str | None = None) -> dict[str, Any]:
    """Look up a fee or charge from this card's SCHEDULE in card_terms.yaml.

    Use for "what does this card charge" questions: "what's the annual
    fee?", "what's the forex markup?", "what's the late payment charge?",
    "what's the cash advance fee?". This is the CARD'S SCHEDULE, not the
    user's history — "what fees was I actually charged" (past
    txn_type=fee/interest rows on the statement) is a transaction-history
    question, not this tool.

    Args:
        fee_type: one of "annual", "joining", "forex_markup",
            "late_payment", "cash_advance_fee", "cash_advance_finance_charge",
            "over_limit", "emi_processing", "emi_foreclosure",
            "card_replacement", "cheque_bounce", "reward_redemption".
            Common synonyms ("late_fee", "annual_fee", "forex", ...) are
            also accepted. Omit to get the full fee schedule.

    If `fee_type` names a charge this card's terms file does not document
    (e.g. a railway-booking surcharge, a wallet-load fee, a balance-transfer
    fee), the return is {"found": False, "requested": ..., ...} — never a
    recalled or invented number for it.
    """
    terms = load_card_terms()
    return _card_fees_core(terms, fee_type)


# ---------------------------------------------------------------------------
# card_offers
# ---------------------------------------------------------------------------

def _is_offer_active(valid_until: str | None, today: date) -> bool | None:
    if not valid_until:
        return None
    try:
        end = date.fromisoformat(str(valid_until))
    except ValueError:
        return None
    return today <= end


def _card_offers_core(
    terms: dict[str, Any],
    merchant: str | None,
    category: str | None,
    today: date,
) -> dict[str, Any]:
    offers = terms.get("offers", [])

    def matches(o: dict[str, Any]) -> bool:
        if merchant and merchant.strip().lower() not in str(o.get("merchant", "")).lower():
            return False
        if category and o.get("category") != category:
            return False
        return True

    filtered = []
    for o in offers:
        if not matches(o):
            continue
        valid_until = o.get("valid_until")
        filtered.append(
            {
                "merchant": o.get("merchant"),
                "benefit": o.get("benefit"),
                "valid_until": valid_until,
                "category": o.get("category"),
                "is_active": _is_offer_active(valid_until, today),
            }
        )

    return {"offers": filtered, "count": len(filtered)}


@tool
def card_offers(merchant: str | None = None, category: str | None = None) -> dict[str, Any]:
    """List current merchant offers on this card from card_terms.yaml.

    Use for "any offers on X right now?", "what deals do I have at Swiggy?",
    "dining offers?". Not for reward earn rates (`card_rewards`) or fees
    (`card_fees`).

    Args:
        merchant: filter to offers whose merchant name contains this text,
            case-insensitive, e.g. "swiggy".
        category: filter to offers tagged with one of the 12 canonical
            categories, e.g. "food_dining".

    Returns {offers: [{merchant, benefit, valid_until, category, is_active}],
    count}. `is_active` compares `valid_until` to today's date but does NOT
    remove expired offers from the list — an expired offer is still named
    and marked inactive rather than silently disappearing, so "is the Swiggy
    offer still on" can be answered honestly either way. An empty `offers`
    list with count 0 means no offer matched the filter; it is a normal
    result, not a missing-term error.
    """
    terms = load_card_terms()
    return _card_offers_core(terms, merchant, category, date.today())


# ---------------------------------------------------------------------------
# resolve_period — local to tools_card.py, see module docstring for why.
# ---------------------------------------------------------------------------

_MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTH_ABBR = {m.lower().rstrip("."): i for i, m in enumerate(calendar.month_abbr) if m}


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    start_month = (quarter - 1) * 3 + 1
    start, _ = _month_bounds(year, start_month)
    _, end = _month_bounds(year, start_month + 2)
    return start, end


def resolve_period(phrase: str, today: date) -> tuple[date, date, str]:
    """Resolve a relative or absolute period phrase into (start, end, label).

    Pure function of (phrase, today) — no system clock, no I/O — so it is
    fully unit-testable. Supports: "last month", "this month", "last week",
    "this week", "last year", "this year" / "ytd", "last N months", a named
    month ("October 2025", "Oct 2025"), an ISO month ("2025-10"), a quarter
    ("Q4 2025", "this quarter", "last quarter"), an explicit ISO date
    ("2025-10-14"), and an explicit ISO date range
    ("2025-10-01 to 2025-12-31").

    Raises ValueError on an unparseable phrase — by design. The planner
    (S05) must call `ask_clarification` rather than ever pass a guessed or
    malformed period phrase down to this layer.
    """
    p = phrase.strip().lower()

    if p == "last month":
        y, m = today.year, today.month - 1
        if m == 0:
            y, m = y - 1, 12
        start, end = _month_bounds(y, m)
        return start, end, date(y, m, 1).strftime("%B %Y")

    if p == "this month":
        start = date(today.year, today.month, 1)
        return start, today, today.strftime("%B %Y")

    if p == "last week":
        start_of_this_week = today - timedelta(days=today.weekday())
        end = start_of_this_week - timedelta(days=1)
        start = end - timedelta(days=6)
        return start, end, f"{start.isoformat()} to {end.isoformat()}"

    if p == "this week":
        start = today - timedelta(days=today.weekday())
        return start, today, f"{start.isoformat()} to {today.isoformat()}"

    if p == "last year":
        y = today.year - 1
        return date(y, 1, 1), date(y, 12, 31), str(y)

    if p in ("this year", "ytd", "year to date"):
        return date(today.year, 1, 1), today, f"YTD {today.year}"

    m_last_n = re.match(r"^last (\d+) months?$", p)
    if m_last_n:
        n = int(m_last_n.group(1))
        end_y, end_m = today.year, today.month - 1
        if end_m == 0:
            end_y, end_m = end_y - 1, 12
        _, end = _month_bounds(end_y, end_m)
        start_total = end_y * 12 + (end_m - 1) - (n - 1)
        start_y, start_m = divmod(start_total, 12)
        start_m += 1
        start, _ = _month_bounds(start_y, start_m)
        label = (
            f"Last {n} months "
            f"({date(start_y, start_m, 1).strftime('%b %Y')}–"
            f"{date(end_y, end_m, 1).strftime('%b %Y')})"
        )
        return start, end, label

    m_quarter = re.match(r"^q([1-4]) (\d{4})$", p)
    if m_quarter:
        q, y = int(m_quarter.group(1)), int(m_quarter.group(2))
        start, end = _quarter_bounds(y, q)
        return start, end, f"Q{q} {y}"

    if p == "this quarter":
        q = (today.month - 1) // 3 + 1
        start, end = _quarter_bounds(today.year, q)
        return start, min(end, today), f"Q{q} {today.year}"

    if p == "last quarter":
        q = (today.month - 1) // 3 + 1
        y = today.year
        q -= 1
        if q == 0:
            q, y = 4, y - 1
        start, end = _quarter_bounds(y, q)
        return start, end, f"Q{q} {y}"

    m_iso_month = re.match(r"^(\d{4})-(\d{2})$", p)
    if m_iso_month:
        y, mth = int(m_iso_month.group(1)), int(m_iso_month.group(2))
        start, end = _month_bounds(y, mth)
        return start, end, date(y, mth, 1).strftime("%B %Y")

    m_named_month = re.match(r"^([a-z]+)\.?\s+(\d{4})$", p)
    if m_named_month:
        name, y = m_named_month.group(1), int(m_named_month.group(2))
        mth = _MONTH_NAMES.get(name) or _MONTH_ABBR.get(name)
        if mth:
            start, end = _month_bounds(y, mth)
            return start, end, date(y, mth, 1).strftime("%B %Y")

    m_range = re.match(r"^(\d{4}-\d{2}-\d{2})\s*(?:to|:)\s*(\d{4}-\d{2}-\d{2})$", p)
    if m_range:
        start = date.fromisoformat(m_range.group(1))
        end = date.fromisoformat(m_range.group(2))
        return start, end, f"{start.isoformat()} to {end.isoformat()}"

    m_single_date = re.match(r"^(\d{4}-\d{2}-\d{2})$", p)
    if m_single_date:
        d = date.fromisoformat(m_single_date.group(1))
        return d, d, d.isoformat()

    raise ValueError(
        f"resolve_period could not parse period phrase {phrase!r}. The planner "
        f"must call ask_clarification instead of passing an unresolvable or "
        f"guessed period through to a tool."
    )


# ---------------------------------------------------------------------------
# rewards_earned — the cross-domain, demo-centrepiece tool.
# ---------------------------------------------------------------------------

def _rewards_earned_core(
    df: pd.DataFrame,
    terms: dict[str, Any],
    start: date,
    end: date,
    period_label: str,
    category: str | None = None,
) -> dict[str, Any]:
    """Deterministic reward calculation over real transactions.

    Order of operations (do not reorder — see S03B spec and module
    docstring):

    1. Group net spend by (category, calendar month) within [start, end].
       Grouping by calendar month, not by the whole query period, is what
       makes step 4's cap application correct for multi-month queries.
    2. Refunds are netted off within that grouping: `amount` is signed
       (positive purchase, negative refund) and simply summed, so a refund
       reduces that category's spend in the month it posts. Net eligible
       spend per (category, month) is floored at 0 — a category can never
       contribute negative points even in a heavy-refund month.
    3. Categories in rewards.excluded_categories (cash_advance,
       fees_interest) are removed from the reward-eligible set entirely;
       their net spend is accumulated into `excluded_spend` instead.
    4. The remaining net eligible spend earns points at the category rate
       if defined in card_terms.yaml, else the base rate — computed once
       per (category, month) as floor(net_spend / 100 * rate).
    5. If that category has a monthly_cap_points, the points for THAT
       (category, month) pair are capped there — independently for every
       calendar month in the query period. A quarter query never applies
       the cap once across all three months.
    6. Every (category, month) pair where the cap was hit is recorded in
       `capped_categories` so the answer can name which month(s) hit it.
    """
    rewards = terms.get("rewards", {})
    base_rate = rewards.get("base_rate", {}).get("points_per_100", 0)
    cat_rates = rewards.get("category_rates", {})
    excluded = set(rewards.get("excluded_categories", []))
    value_per_point = rewards.get("redemption", {}).get("value_per_point_inr", 0)

    if category is not None and category not in CANONICAL_CATEGORIES:
        return {
            "found": False,
            "requested_category": category,
            "available_categories": list(CANONICAL_CATEGORIES),
        }

    mask = (df["timestamp"].dt.date >= start) & (df["timestamp"].dt.date <= end)
    period_df = df.loc[mask]
    if category is not None:
        period_df = period_df[period_df["category"] == category]

    by_category_points: dict[str, int] = {}
    capped_categories: list[dict[str, Any]] = []
    excluded_spend = 0.0

    if len(period_df) > 0:
        grouped = period_df.groupby(
            [period_df["category"], period_df["timestamp"].dt.to_period("M")]
        )["amount"].sum()

        for (cat, month_period), net_amount in grouped.items():
            if cat in excluded:
                excluded_spend += float(net_amount)
                continue

            net_eligible = max(float(net_amount), 0.0)  # floor refunds at 0
            cat_entry = cat_rates.get(cat, {})
            rate = cat_entry.get("points_per_100", base_rate)
            raw_points = math.floor(net_eligible / 100 * rate)
            cap = cat_entry.get("monthly_cap_points")

            if cap is not None and raw_points > cap:
                points_awarded = cap
                capped_categories.append(
                    {
                        "category": cat,
                        "month": str(month_period),
                        "month_label": month_period.strftime("%B %Y"),
                        "capped_points": cap,
                        "uncapped_points_would_be": raw_points,
                        "eligible_spend_inr": round(net_eligible, 2),
                    }
                )
            else:
                points_awarded = raw_points

            by_category_points[cat] = by_category_points.get(cat, 0) + points_awarded

    # If the caller asked about one specific (excluded) category and it had
    # transactions, make that explicit in by_category rather than an empty
    # dict that looks like "no data".
    if category is not None and category in excluded and category not in by_category_points:
        by_category_points[category] = 0

    points_total = sum(by_category_points.values())
    redemption_value_inr = round(points_total * value_per_point, 2)

    return {
        "found": True,
        "period_label": period_label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "category": category,
        "category_excluded": (category in excluded) if category is not None else None,
        "points_total": points_total,
        "by_category": by_category_points,
        "capped_categories": capped_categories,
        "excluded_spend": round(excluded_spend, 2),
        "redemption_value_inr": redemption_value_inr,
        "transaction_count": int(len(period_df)),
    }


@tool
def rewards_earned(period: str, category: str | None = None) -> dict[str, Any]:
    """Apply the card's reward SCHEDULE to ACTUAL transactions — the
    cross-domain calculation. Use for "how many points did I earn in
    July?", "am I near the dining cap?", "how many points from groceries
    last quarter?". This is a deterministic computation over real spend
    (never an LLM estimate) — for "what's the reward rate on dining" (the
    schedule itself, not what was actually earned), use `card_rewards`
    instead.

    Args:
        period: a time phrase resolved against today's date, e.g.
            "last month", "this month", "YTD", "last year", "last 3 months",
            "October 2025", "2025-10", "Q4 2025", "last quarter", or an
            explicit "2025-10-01 to 2025-12-31" range. Never guess a period
            — if the question doesn't name one, ask for it instead of
            calling this tool.
        category: restrict to one of the 12 canonical categories. Omit for
            every category combined.

    Returns {points_total, by_category, capped_categories, excluded_spend,
    redemption_value_inr, period_label, ...}. `capped_categories` lists
    every (category, calendar month) pair where the monthly cap was hit —
    caps are applied per category, per CALENDAR MONTH, never once across
    the whole query period, so a quarter with two capped months shows both.
    """
    today = date.today()
    terms = load_card_terms()
    start, end, period_label = resolve_period(period, today)
    df = load_transactions(str(DEFAULT_MAPPING_PATH))
    return _rewards_earned_core(df, terms, start, end, period_label, category)
