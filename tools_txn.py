"""Six deterministic transaction tools — built out in S03.

spend_total, spend_by_category, top_merchants, compare_periods,
find_transactions, recurring_charges — plus the resolve_period date helper.

The one rule every function in this file exists to enforce (PRD.md §3):

    "A model asked to sum 2,000 rows will produce a plausible, confident,
    wrong figure."

So the LLM never touches `amount`. Every number below comes out of pandas,
not out of a language model. Each `@tool`-decorated function is a *thin*
wrapper: it loads the canonical DataFrame via `data_loader.load_transactions`
and delegates to a private, pure `_..._core` function that takes the
DataFrame and already-typed arguments and returns a flat dict of scalars.
That split is what makes the arithmetic testable without going through the
LangChain tool-calling machinery — tests in `tests/test_tools_txn.py` call
the private core functions directly with a fixed `today`, and hand-computed
(or independently one-lined) expected values.

Two hard constraints carried over from data_loader.py (S02) and CLAUDE.md:

- Only the six canonical columns (`txn_id, timestamp, amount, merchant,
  category, card_id`) may be relied on. This repo's synthetic CSV also
  carries `txn_type`, `city`, `currency`, but those are NOT part of the
  schema-swap contract, so no logic here reads them — a real swapped-in
  CSV is not guaranteed to have them.
- Relative dates are resolved by `resolve_period()` in Python. The LLM only
  ever passes a phrase string; it never computes a date range itself.

See all-specs.md S03 and .claude/agents/txn-tools-builder.md.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

import pandas as pd
from langchain_core.tools import tool

from data_loader import load_transactions

# Bound-method reference captured once at import time, purely so
# `find_transactions` (whose LangChain-exposed parameter is itself named
# `date`, per the S03 spec table) can get today's date without needing to
# refer to the `date` class by name inside a scope where that name is
# shadowed by the parameter.
_today_fn = date.today

# --------------------------------------------------------------------------
# resolve_period — the shared date helper. Never called by the LLM directly;
# every tool below calls it internally with a plain phrase string.
# --------------------------------------------------------------------------

_MONTH_ALIASES: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_MONTH_PATTERN = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?"
    r"|nov(?:ember)?|dec(?:ember)?)\b"
)
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
_DAY_PATTERN = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\b")

_WORD_NUMBERS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_LAST_N_MONTHS_PATTERN = re.compile(
    r"^last (\d+|" + "|".join(_WORD_NUMBERS) + r") months?$"
)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _step_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift (year, month) by `delta` whole months (may be negative)."""
    total = (year * 12 + (month - 1)) + delta
    return total // 12, total % 12 + 1


def _parse_date_like(phrase_norm: str, today: date) -> tuple[date, date, str] | None:
    """Try to parse `phrase_norm` as either a specific single date or a
    whole named month. Returns (start, end, label) or None if no month
    name (and no bare ISO date) could be found in the phrase at all.

    Missing-year rule (applies to both branches): if the phrase names a
    month but no year, we pick the most recent occurrence that is not in
    the future relative to `today` — i.e. this year if that month has
    already started this year, otherwise last year. "March" asked on
    2026-08-11 means March 2026; "December" asked on 2026-08-11 means
    December 2025, because December 2026 hasn't happened yet.
    """
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", phrase_norm.strip())
    if iso:
        y, m, d = (int(g) for g in iso.groups())
        dt = date(y, m, d)
        return dt, dt, dt.strftime("%B %d, %Y")

    month_match = _MONTH_PATTERN.search(phrase_norm)
    if not month_match:
        return None
    month = _MONTH_ALIASES[month_match.group(1)]

    year_match = _YEAR_PATTERN.search(phrase_norm)
    if year_match:
        year = int(year_match.group(0))
        scrubbed = phrase_norm[: year_match.start()] + " " + phrase_norm[year_match.end() :]
    else:
        year = today.year if month <= today.month else today.year - 1
        scrubbed = phrase_norm

    # A day number, if present, turns this into a single specific date
    # rather than a whole-month period. Search only outside the year token
    # (already scrubbed out above) so a 4-digit year is never misread as a
    # day.
    day_match = _DAY_PATTERN.search(scrubbed)
    if day_match:
        day = int(day_match.group(1))
        last_day = calendar.monthrange(year, month)[1]
        if 1 <= day <= last_day:
            dt = date(year, month, day)
            return dt, dt, dt.strftime("%B %d, %Y")

    start, end = _month_bounds(year, month)
    return start, end, start.strftime("%B %Y")


def resolve_period(phrase: str, today: date) -> tuple[date, date, str]:
    """Resolve a natural-language period phrase into (start, end, label).

    This is the ONLY place relative dates get resolved in this codebase.
    The LLM planner (S05) passes phrases straight through as strings; it
    never computes a date itself. Supported phrase families (case-
    insensitive, whitespace-trimmed):

        "last month"            -> previous full calendar month
        "this month"            -> current full calendar month
        "last week"             -> previous Mon-Sun week
        "this week"             -> current Mon-Sun week
        "last N months"         -> N full calendar months ending with last
                                    month, e.g. "last 3 months" on 2026-08-11
                                    -> May 2026 .. Jul 2026 (does NOT include
                                    the current, still-in-progress month)
        "last year"             -> previous full calendar year
        "YTD" / "year to date"  -> Jan 1 of this year .. today
        a named month           -> e.g. "March", "March 2026" -> that whole
                                    calendar month
        a specific date         -> e.g. "2026-03-14", "March 14, 2026" ->
                                    start == end == that single day

    Raises ValueError if `phrase` doesn't match any supported family, naming
    what is supported so the caller can surface a clear error (or route to
    a clarifying question upstream).
    """
    if not phrase or not phrase.strip():
        raise ValueError("resolve_period: received an empty period phrase")
    p = phrase.strip().lower()

    if p == "last month":
        y, m = _step_month(today.year, today.month, -1)
        start, end = _month_bounds(y, m)
        return start, end, start.strftime("%B %Y")

    if p == "this month":
        start, end = _month_bounds(today.year, today.month)
        return start, end, start.strftime("%B %Y")

    if p == "last week":
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)
        end = start + timedelta(days=6)
        return start, end, f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

    if p == "this week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end, f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

    if p == "last year":
        y = today.year - 1
        return date(y, 1, 1), date(y, 12, 31), str(y)

    if p in ("ytd", "year to date", "this year to date"):
        start = date(today.year, 1, 1)
        return start, today, f"Jan 1 - {today.strftime('%b %d, %Y')} (YTD)"

    n_match = _LAST_N_MONTHS_PATTERN.fullmatch(p)
    if n_match:
        raw = n_match.group(1)
        n = int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]
        if n < 1:
            raise ValueError(f"resolve_period: 'last N months' needs N >= 1, got {n}")
        end_y, end_m = _step_month(today.year, today.month, -1)
        start_y, start_m = _step_month(end_y, end_m, -(n - 1))
        start, _ = _month_bounds(start_y, start_m)
        _, end = _month_bounds(end_y, end_m)
        label = f"{start.strftime('%b %Y')} - {end.strftime('%b %Y')} (last {n} months)"
        return start, end, label

    parsed = _parse_date_like(p, today)
    if parsed:
        return parsed

    raise ValueError(
        f"resolve_period: could not resolve period phrase {phrase!r}. Supported: "
        "'last month', 'this month', 'last week', 'this week', 'last N months', "
        "a named month (e.g. 'March 2026'), 'last year', 'YTD', or a specific "
        "date (e.g. '2026-03-14')."
    )


def _parse_specific_date(phrase: str, today: date) -> date | None:
    """Parse a single specific calendar date out of `phrase` (used by
    `find_transactions`'s `date` filter, which names one day rather than a
    period). Reuses the same month/day parsing as resolve_period, but
    returns None instead of raising when the phrase names a whole month
    with no day — that's not a single date.
    """
    p = phrase.strip().lower()
    parsed = _parse_date_like(p, today)
    if parsed is None:
        return None
    start, end, _ = parsed
    if start != end:
        return None
    return start


# --------------------------------------------------------------------------
# Data access — the only place tools read the source DataFrame.
# --------------------------------------------------------------------------


def _get_df() -> pd.DataFrame:
    return load_transactions()


def _filter_period(df: pd.DataFrame, period: str, today: date) -> tuple[pd.DataFrame, str]:
    start, end, label = resolve_period(period, today)
    ts_date = df["timestamp"].dt.date
    mask = (ts_date >= start) & (ts_date <= end)
    return df.loc[mask], label


def _filter_category(df: pd.DataFrame, category: str | None) -> pd.DataFrame:
    if not category:
        return df
    needle = category.strip().lower()
    return df[df["category"].str.lower() == needle]


def _filter_card(df: pd.DataFrame, card_id: str | None) -> pd.DataFrame:
    if not card_id:
        return df
    needle = card_id.strip().lower()
    return df[df["card_id"].str.lower() == needle]


# --------------------------------------------------------------------------
# spend_total
# --------------------------------------------------------------------------


def _spend_total_core(
    df: pd.DataFrame,
    period: str,
    category: str | None,
    card_id: str | None,
    today: date,
) -> dict:
    filtered, label = _filter_period(df, period, today)
    filtered = _filter_category(filtered, category)
    filtered = _filter_card(filtered, card_id)

    total = round(float(filtered["amount"].sum()), 2)
    count = int(len(filtered))
    avg_txn = round(total / count, 2) if count else 0.0

    return {"total": total, "count": count, "period_label": label, "avg_txn": avg_txn}


@tool(parse_docstring=True)
def spend_total(
    period: str,
    category: str | None = None,
    card_id: str | None = None,
) -> dict:
    """Compute the total (net) amount spent over a time period, as one number.

    Use this when the user wants a single aggregate spend figure, optionally
    narrowed to one category or one card. Example utterances: "How much did
    I spend last month?", "What did I spend on food_dining in March?",
    "What was my total spend this year?". The total nets refunds against
    purchases (a negative `amount` row is a refund), so it reflects what
    actually left the account, not gross purchases.

    Not for merchant- or fee-schedule questions. Do NOT use this for "what
    fees do I pay" or "what's the late payment fee" — those ask about the
    card's documented fee SCHEDULE, which is a lookup (the `card_fees` tool
    in the card-terms domain), not something computed from transaction
    history. Use spend_total(category="fees_interest") only for "what fees
    WAS I charged" / "how much interest did I pay" — actual historical fee
    and interest transactions on this account.

    Args:
        period: A period phrase resolved by resolve_period, e.g. "last
            month", "this week", "March 2026", "last 3 months", "YTD",
            "last year", or a specific date like "2026-03-14".
        category: Optional canonical category to filter to, e.g.
            "food_dining", "groceries", "fuel", "fees_interest". Omit for
            spend across all categories.
        card_id: Optional card identifier to filter to. Omit unless the
            user names a specific card; v1 has a single card so this is
            rarely needed.
    """
    return _spend_total_core(_get_df(), period, category, card_id, today=date.today())


# --------------------------------------------------------------------------
# spend_by_category
# --------------------------------------------------------------------------


def _spend_by_category_core(
    df: pd.DataFrame,
    period: str,
    top_n: int,
    today: date,
) -> dict:
    filtered, label = _filter_period(df, period, today)
    grand_total = round(float(filtered["amount"].sum()), 2)

    if filtered.empty:
        return {"categories": [], "total": 0.0, "period_label": label}

    grouped = filtered.groupby("category")["amount"].sum().sort_values(ascending=False)
    categories = []
    for name, cat_total in grouped.head(top_n).items():
        cat_total = round(float(cat_total), 2)
        pct = round((cat_total / grand_total) * 100, 2) if grand_total else 0.0
        categories.append({"name": name, "total": cat_total, "pct": pct})

    return {"categories": categories, "total": grand_total, "period_label": label}


@tool(parse_docstring=True)
def spend_by_category(period: str, top_n: int = 5) -> dict:
    """Break down spend by category for a period, ranked highest total first.

    Use this when the user wants to know WHERE their money went across
    several categories, not a single number. Example utterances: "Where did
    my money go in March?", "Break down my spending by category last
    month", "What are my top spending categories this year?".

    Not for a single category's total. Do NOT use this when the user names
    one specific category (use spend_total with category set instead), and
    do NOT use this for a merchant ranking (use top_merchants).

    Args:
        period: A period phrase resolved by resolve_period, e.g. "last
            month", "March 2026", "YTD".
        top_n: How many categories to return, ranked by total spend
            descending. Defaults to 5.
    """
    return _spend_by_category_core(_get_df(), period, top_n, today=date.today())


# --------------------------------------------------------------------------
# top_merchants
# --------------------------------------------------------------------------


def _top_merchants_core(
    df: pd.DataFrame,
    period: str,
    top_n: int,
    today: date,
) -> dict:
    filtered, label = _filter_period(df, period, today)

    if filtered.empty:
        return {"merchants": [], "period_label": label}

    grouped = (
        filtered.groupby("merchant")
        .agg(total=("amount", "sum"), count=("amount", "size"))
        .sort_values("total", ascending=False)
    )
    merchants = [
        # Bracket indexing, not attribute access (`row.count`) — "count" is
        # also the name of a built-in Series method, and attribute access
        # resolves to that method rather than this row's "count" column.
        {"name": name, "total": round(float(row["total"]), 2), "count": int(row["count"])}
        for name, row in grouped.head(top_n).iterrows()
    ]
    return {"merchants": merchants, "period_label": label}


@tool(parse_docstring=True)
def top_merchants(period: str, top_n: int = 5) -> dict:
    """Rank merchants by total spend for a period, highest spend first.

    Use this when the user asks WHO or WHERE they spend the most, by
    merchant name — not by category. Example utterances: "Who do I spend
    the most at?", "What are my top merchants this month?", "Where do I
    shop most often?".

    Not for a category breakdown. Do NOT use this for "where did my money
    go" by category (use spend_by_category), and do NOT use this to check
    whether one specific transaction happened (use find_transactions).

    Args:
        period: A period phrase resolved by resolve_period, e.g. "last
            month", "this month", "last 3 months".
        top_n: How many merchants to return, ranked by total spend
            descending. Defaults to 5.
    """
    return _top_merchants_core(_get_df(), period, top_n, today=date.today())


# --------------------------------------------------------------------------
# compare_periods
# --------------------------------------------------------------------------


def _compare_periods_core(
    df: pd.DataFrame,
    period_a: str,
    period_b: str,
    category: str | None,
    today: date,
) -> dict:
    filtered_a, label_a = _filter_period(df, period_a, today)
    filtered_b, label_b = _filter_period(df, period_b, today)
    filtered_a = _filter_category(filtered_a, category)
    filtered_b = _filter_category(filtered_b, category)

    total_a = round(float(filtered_a["amount"].sum()), 2)
    total_b = round(float(filtered_b["amount"].sum()), 2)
    delta = round(total_a - total_b, 2)

    if total_b != 0:
        # Denominator uses abs(total_b) so pct_change's sign always agrees
        # with `direction`, even in the (rare) case that the baseline
        # period itself nets negative (e.g. a heavy-refund category).
        pct_change = round((delta / abs(total_b)) * 100, 2)
    elif total_a == 0:
        pct_change = 0.0
    else:
        # Baseline is exactly zero and the other period isn't: "percent
        # change from zero" is mathematically undefined, so we say so
        # rather than fabricate a number (e.g. an arbitrary "100%").
        pct_change = None

    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "flat"

    return {
        "total_a": total_a,
        "total_b": total_b,
        "delta": delta,
        "pct_change": pct_change,
        "direction": direction,
        "labels": {"a": label_a, "b": label_b},
    }


@tool(parse_docstring=True)
def compare_periods(
    period_a: str,
    period_b: str,
    category: str | None = None,
) -> dict:
    """Compare total spend between two periods and report the change.

    Use this when the user compares spending across two time ranges.
    Example utterances: "Am I spending more than last month?", "How does
    July compare to June?", "Did my dining spend go up this quarter vs
    last?". `period_a` is the period being asked about (usually the more
    recent one); `period_b` is the baseline it's compared against.

    Not for a single period's number. Do NOT use this for a plain total
    (use spend_total) or a category breakdown within one period (use
    spend_by_category).

    Args:
        period_a: The first (typically current / more recent) period
            phrase, e.g. "this month".
        period_b: The second (baseline / comparison) period phrase, e.g.
            "last month".
        category: Optional canonical category to restrict the comparison
            to, e.g. "food_dining". Omit to compare total spend across all
            categories.
    """
    return _compare_periods_core(_get_df(), period_a, period_b, category, today=date.today())


# --------------------------------------------------------------------------
# find_transactions
# --------------------------------------------------------------------------

_MATCH_CAP = 5


def _find_transactions_core(
    df: pd.DataFrame,
    merchant: str | None,
    date_phrase: str | None,
    min_amount: float | None,
    period: str | None,
    today: date,
) -> dict:
    filtered = df

    if period:
        filtered, _ = _filter_period(filtered, period, today)

    if date_phrase:
        specific = _parse_specific_date(date_phrase, today)
        if specific is None:
            raise ValueError(
                f"find_transactions: could not parse `date` phrase {date_phrase!r} "
                "as a single specific date."
            )
        filtered = filtered[filtered["timestamp"].dt.date == specific]

    if merchant:
        filtered = filtered[
            filtered["merchant"].str.contains(merchant.strip(), case=False, na=False, regex=False)
        ]

    if min_amount is not None:
        filtered = filtered[filtered["amount"] >= min_amount]

    filtered = filtered.sort_values("timestamp", ascending=False)
    count = int(len(filtered))
    head = filtered.head(_MATCH_CAP)
    matches = [
        {"date": ts.date().isoformat(), "merchant": merch, "amount": round(float(amt), 2)}
        for ts, merch, amt in zip(head["timestamp"], head["merchant"], head["amount"])
    ]

    # NB: no `period_label` key here, unlike the other five tools. The
    # shared rule ("every dict includes period_label") is written for
    # tools where a period is the primary organizing argument; here period
    # is one of four optional, independent filters (merchant/date/
    # min_amount/period), so there isn't always a period to label. The
    # exact return shape `{matches, count}` is the one specified in
    # all-specs.md S03's tool table and is kept as-is.
    return {"matches": matches, "count": count}


@tool(parse_docstring=True)
def find_transactions(
    merchant: str | None = None,
    date: str | None = None,
    min_amount: float | None = None,
    period: str | None = None,
) -> dict:
    """Look up specific individual transactions matching given filters, capped at 5.

    Use this to find or confirm one or a few specific transactions — not a
    total. Example utterances: "Did I pay Swiggy on the 14th?", "Show me
    transactions over 5000 last month", "Find my Amazon charges in March",
    "Was I charged twice by the same merchant on the same day?" (duplicate-
    charge / dispute lookups). `count` reports how many transactions
    matched in total; `matches` returns at most the 5 most recent.

    Not for an aggregate total or a count-heavy answer. Do NOT use this to
    answer "how much did I spend" or "how many transactions" as the actual
    answer (use spend_total) — it is capped at 5 rows and is not a
    reliable source for a sum. At least one filter should normally be
    supplied; with none, it returns the 5 most recent transactions overall.

    Args:
        merchant: Optional merchant name or partial name to match,
            case-insensitive, e.g. "Swiggy".
        date: Optional specific calendar date to match, e.g. "2026-03-14"
            or "March 14, 2026". This is a single day, not a range — for a
            range use `period` instead.
        min_amount: Optional minimum transaction amount (inclusive) to
            match.
        period: Optional period phrase resolved by resolve_period, e.g.
            "last month", to narrow the search to a date range.
    """
    return _find_transactions_core(
        _get_df(), merchant, date, min_amount, period, today=_today_fn()
    )


# --------------------------------------------------------------------------
# recurring_charges
# --------------------------------------------------------------------------

_RECURRING_MIN_OCCURRENCES = 3
_RECURRING_AMOUNT_TOLERANCE_PCT = 0.10
_RECURRING_INTERVAL_MIN_DAYS = 28
_RECURRING_INTERVAL_MAX_DAYS = 31


def _recurring_charges_core(df: pd.DataFrame) -> dict:
    """Deterministic pandas rule (no LLM judgement): a merchant is
    recurring if it has >=3 transactions, ALL of whose amounts sit within
    a band no wider than 10% of the smallest one, AND whose consecutive
    charge dates have a median gap of 28-31 days (i.e. roughly monthly).

    Requiring the amount check across the merchant's *entire* history
    (not a matched subset) is deliberate: it's what correctly excludes a
    merchant like "Croma" whose transactions mix a monthly EMI instalment
    series with unrelated one-off retail purchases of very different
    amounts — the EMI rows alone would look monthly, but the merchant as a
    whole does not read as "a subscription".
    """
    subscriptions = []
    for merchant, rows in df.groupby("merchant"):
        rows = rows.sort_values("timestamp")
        if len(rows) < _RECURRING_MIN_OCCURRENCES:
            continue

        amt_min = float(rows["amount"].min())
        amt_max = float(rows["amount"].max())
        if amt_min <= 0:
            continue  # refunds/fees only, or non-positive spend: not a subscription
        if (amt_max - amt_min) > _RECURRING_AMOUNT_TOLERANCE_PCT * amt_min:
            continue

        diffs = rows["timestamp"].diff().dt.days.dropna()
        if diffs.empty:
            continue
        median_interval = diffs.median()
        if not (_RECURRING_INTERVAL_MIN_DAYS <= median_interval <= _RECURRING_INTERVAL_MAX_DAYS):
            continue

        subscriptions.append(
            {
                "merchant": merchant,
                "amount": round(float(rows["amount"].mean()), 2),
                "frequency": "monthly",
                "last_charged": rows["timestamp"].max().date().isoformat(),
            }
        )

    subscriptions.sort(key=lambda s: s["amount"], reverse=True)
    monthly_total = round(sum(s["amount"] for s in subscriptions), 2)
    return {"subscriptions": subscriptions, "monthly_total": monthly_total}


@tool(parse_docstring=True)
def recurring_charges() -> dict:
    """List detected recurring / subscription charges and their combined monthly cost.

    Use this when the user asks about subscriptions or recurring charges in
    general, across their whole history. Example utterances: "What
    subscriptions am I paying for?", "What recurring charges do I have?",
    "What am I paying every month on autopay?". Detection is a fixed rule,
    not a judgement call: the same merchant charged at least 3 times, at an
    amount that never varies by more than 10% from its lowest charge, at a
    roughly monthly cadence (median gap between charges of 28-31 days).
    There is no period argument — it always looks across the full
    transaction history and returns the latest detected state.

    Not for a period-scoped total. Do NOT use this for a category or
    merchant total in a specific window (use spend_total or top_merchants
    instead).
    """
    return _recurring_charges_core(_get_df())
