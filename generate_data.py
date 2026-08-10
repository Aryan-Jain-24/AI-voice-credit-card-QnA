"""Synthetic transaction generator — built out in S01.

Produces data/transactions.csv (~2,000 rows, 18 months, 1 user, 1 card) with
the realism requirements (subscriptions, refunds, EMI, FX, duplicate charge,
spend spike, reward-cap-breaching months) that later specs depend on.

Determinism: every random draw goes through a single ``random.Random(SEED)``
instance. Re-running this script produces byte-identical output.

See all-specs.md S01 and .claude/agents/data-generator.md.

Run:
    python generate_data.py

This writes data/transactions.csv and then runs a battery of assertions
(each a one-line-ish pandas filter) against the freshly built DataFrame —
if any realism guarantee below is violated, the script fails loudly instead
of silently shipping a flat dataset.
"""

from __future__ import annotations

import calendar
import random
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

SEED = 42
CARD_ID = "XXXX4412"
HOME_CITY = "Bengaluru"
TRAVEL_CITIES = ["Mumbai", "Delhi", "Goa", "Chennai", "Pune", "Jaipur", "Hyderabad"]

OUTPUT_PATH = Path(__file__).parent / "data" / "transactions.csv"

# 12 canonical categories — load-bearing, must match card_terms.yaml exactly.
CANONICAL_CATEGORIES = [
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

VALID_TXN_TYPES = {"purchase", "refund", "fee", "interest", "emi"}

# 18-month window, hardcoded (not derived from date.today()) so the generator
# is deterministic regardless of the day it is run. Ends July 2026, i.e. the
# month before the fixed "today" (2026-08-11) this project is being built
# against — so "last month" queries in later specs land on a populated month.
END_MONTH = (2026, 7)
NUM_MONTHS = 18

# Reference dining reward cap used only to make the cap-breach scenario real.
# card_terms.yaml in this repo is still the S03B skeleton (all TODO) at the
# time S01 runs, so there is no authored cap to read yet. We use the worked
# example from PRD.md §7.3 as the reference: dining earns 5 points per ₹100,
# capped at 2,000 points/month => breach threshold = 2000 / 5 * 100 = ₹40,000
# of dining spend in a calendar month. If S03B's final card_terms.yaml lands
# on a materially different dining cap, this constant (and the two booster
# months below) should be revisited so the breach stays real.
REFERENCE_DINING_CAP_POINTS = 2000
REFERENCE_DINING_RATE_PER_100 = 5
REFERENCE_DINING_CAP_SPEND = REFERENCE_DINING_CAP_POINTS / REFERENCE_DINING_RATE_PER_100 * 100  # 40,000


# --------------------------------------------------------------------------
# Merchant dictionary — ~40-50 recognizable Indian (or India-common) brands.
# Kept as a module-level dict/list (not buried in a function) because
# voice-ui-engineer reuses ALL_MERCHANTS verbatim in S07 for fuzzy ASR
# correction of merchant names.
# --------------------------------------------------------------------------

MERCHANTS: dict[str, list[str]] = {
    "food_dining": [
        "Swiggy", "Zomato", "Domino's Pizza", "McDonald's", "Starbucks", "Barbeque Nation",
    ],
    "groceries": [
        "BigBasket", "DMart", "Reliance Fresh", "Blinkit",
    ],
    "fuel": [
        "Indian Oil", "Bharat Petroleum", "HP Petrol Pump", "Shell",
    ],
    "travel": [
        "IRCTC", "MakeMyTrip", "Ola", "Uber", "IndiGo", "RedBus",
    ],
    "shopping": [
        "Amazon", "Flipkart", "Myntra", "Ajio", "Croma", "Reliance Digital", "Amazon Prime",
    ],
    "entertainment": [
        "BookMyShow", "Netflix", "Spotify Premium", "PVR Cinemas", "Disney+ Hotstar",
    ],
    "utilities": [
        "Airtel", "Tata Power", "BSES", "ACT Fibernet", "Jio Postpaid",
    ],
    "health": [
        "Apollo Pharmacy", "Practo", "Netmeds", "PharmEasy", "Cult.fit Membership",
    ],
    "education": [
        "BYJU'S", "Coursera", "Udemy",
    ],
    "cash_advance": [
        "ATM Cash Withdrawal", "Cash Advance - Branch",
    ],
    "fees_interest": [
        "Late Payment Fee", "Interest Charge", "Finance Charge", "Cash Advance Fee", "Over-limit Fee",
    ],
    "other": [
        "PhonePe", "Paytm", "Google Play Store", "Local Kirana Store", "Google One",
    ],
}

# Categories whose merchants are genuine "you said this out loud" merchant
# names, as opposed to bank-generated fee/interest line items or the ATM
# descriptor for a cash advance. This is the list voice-ui-engineer wants.
_SPEND_CATEGORIES = [c for c in CANONICAL_CATEGORIES if c not in ("cash_advance", "fees_interest")]
ALL_MERCHANTS: list[str] = sorted({m for c in _SPEND_CATEGORIES for m in MERCHANTS[c]})

# The 6 recurring subscriptions live in their own list below and must not
# also be drawn by the organic random generator (that would double up the
# pattern in a confusing way), so we exclude them from the "organic" pools.
SUBSCRIPTIONS = [
    {"merchant": "Netflix", "category": "entertainment", "amount": 649.0, "day": 5},
    {"merchant": "Spotify Premium", "category": "entertainment", "amount": 119.0, "day": 8},
    {"merchant": "Jio Postpaid", "category": "utilities", "amount": 399.0, "day": 3},
    {"merchant": "Cult.fit Membership", "category": "health", "amount": 1999.0, "day": 10},
    {"merchant": "Amazon Prime", "category": "shopping", "amount": 299.0, "day": 15},
    {"merchant": "Google One", "category": "other", "amount": 130.0, "day": 20},
]
_SUBSCRIPTION_MERCHANT_NAMES = {s["merchant"] for s in SUBSCRIPTIONS}

# "Late Payment Fee" / "Interest Charge" are reserved for the dedicated
# late-fee-then-interest scenario below so that scenario stays exactly
# findable (2 of each) rather than blended with organic noise.
_RESERVED_FEES_INTEREST_MERCHANTS = {"Late Payment Fee", "Interest Charge"}

ORGANIC_MERCHANTS: dict[str, list[str]] = {
    cat: [m for m in merchants if m not in _SUBSCRIPTION_MERCHANT_NAMES and m not in _RESERVED_FEES_INTEREST_MERCHANTS]
    for cat, merchants in MERCHANTS.items()
}

FEES_INTEREST_TXN_TYPE = {
    "Late Payment Fee": "fee",
    "Interest Charge": "interest",
    "Finance Charge": "interest",
    "Cash Advance Fee": "fee",
    "Over-limit Fee": "fee",
}

# --------------------------------------------------------------------------
# Amount ranges
# --------------------------------------------------------------------------

AMOUNT_RANGES: dict[str, tuple[float, float]] = {
    "food_dining": (120, 650),
    "groceries": (250, 2600),
    "fuel": (400, 1800),
    "travel": (120, 1200),
    "shopping": (250, 2200),
    "entertainment": (180, 800),
    "utilities": (300, 2200),
    "health": (180, 1500),
    "education": (350, 2200),
    "cash_advance": (2000, 6000),
    "fees_interest": (150, 800),
    "other": (100, 1200),
}

# Big-ticket merchants get their own range instead of the category default.
MERCHANT_AMOUNT_OVERRIDES: dict[str, tuple[float, float]] = {
    "Barbeque Nation": (1200, 3000),
    "MakeMyTrip": (3000, 12000),
    "IndiGo": (3500, 9500),
    "IRCTC": (350, 1800),
    "Croma": (2000, 7000),
    "Reliance Digital": (2000, 7000),
    "BYJU'S": (1200, 4500),
    "Coursera": (1500, 3200),
}

# A handful of categories mix everyday merchants with rare big-ticket ones
# (a flight is not a weekly occurrence the way a cab ride is). These weights
# make the common merchant dominate; falls back to a mild default weight for
# any merchant in the category not listed here.
MERCHANT_WEIGHTS: dict[str, dict[str, float]] = {
    "travel": {"Ola": 30, "Uber": 30, "IRCTC": 14, "RedBus": 10, "MakeMyTrip": 4, "IndiGo": 4},
    "shopping": {"Amazon": 24, "Flipkart": 20, "Myntra": 16, "Ajio": 12, "Croma": 4, "Reliance Digital": 4},
}

BASE_WEEKDAY_WEIGHTS: dict[str, float] = {
    "food_dining": 16, "groceries": 10, "fuel": 5, "travel": 6, "shopping": 10,
    "entertainment": 4, "utilities": 4, "health": 5, "education": 3,
    "cash_advance": 1, "fees_interest": 1, "other": 6,
}
BASE_WEEKEND_WEIGHTS: dict[str, float] = {
    "food_dining": 26, "groceries": 8, "fuel": 3, "travel": 10, "shopping": 15,
    "entertainment": 12, "utilities": 2, "health": 3, "education": 2,
    "cash_advance": 1, "fees_interest": 1, "other": 6,
}

# --------------------------------------------------------------------------
# Scenario dates
# --------------------------------------------------------------------------

SPIKE_MONTH = (2026, 3)
DINING_BREACH_MONTHS = [(2025, 10), (2025, 11)]
LATE_FEE_MONTHS = [(2025, 5), (2026, 1)]
EMI_PURCHASE_DATE = (2025, 6, 15)
LATE_FEE_AMOUNT = 750.0


# --------------------------------------------------------------------------
# Date helpers
# --------------------------------------------------------------------------

def month_range(end_year: int, end_month: int, n: int) -> list[tuple[int, int]]:
    """Last n (year, month) tuples ending at (end_year, end_month), ascending."""
    months = []
    y, m = end_year, end_month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()
    return months


def last_day_of_month(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def daterange(start, end):
    d = start
    one_day = pd.Timedelta(days=1)
    while d <= end:
        yield d
        d = (d + one_day)


MONTHS = month_range(END_MONTH[0], END_MONTH[1], NUM_MONTHS)
START_DATE = pd.Timestamp(MONTHS[0][0], MONTHS[0][1], 1)
END_DATE = pd.Timestamp(MONTHS[-1][0], MONTHS[-1][1], last_day_of_month(*MONTHS[-1]))


# --------------------------------------------------------------------------
# Small realism helpers
# --------------------------------------------------------------------------

def realistic_amount(rng: random.Random, low: float, high: float) -> float:
    """Uniform draw, biased towards MRP-style endings (x99, x49, round tens)."""
    val = rng.uniform(low, high)
    if rng.random() < 0.6:
        val = round(val / 10) * 10
        if rng.random() < 0.5:
            val -= 1
    return round(max(val, low), 2)


def txn_count_for_day(rng: random.Random, d: pd.Timestamp) -> int:
    is_weekend = d.dayofweek >= 5  # 5=Sat, 6=Sun
    is_salary_week = d.day <= 5
    is_festive = d.month in (10, 11)
    if is_weekend or is_festive:
        base = rng.choices([2, 3, 4, 5, 6], weights=[10, 25, 30, 20, 15])[0]
    else:
        base = rng.choices([1, 2, 3, 4, 5], weights=[15, 35, 30, 15, 5])[0]
    if is_salary_week:
        base += rng.choice([1, 1, 2, 2, 3])
    return base


def category_weights_for_day(d: pd.Timestamp) -> dict[str, float]:
    is_weekend = d.dayofweek >= 5
    is_festive = d.month in (10, 11)
    weights = dict(BASE_WEEKEND_WEIGHTS if is_weekend else BASE_WEEKDAY_WEIGHTS)
    if is_festive:
        for c in ("shopping", "food_dining", "travel", "entertainment"):
            weights[c] = weights[c] * 1.6
    return weights


def pick_merchant(rng: random.Random, category: str) -> str:
    pool = ORGANIC_MERCHANTS[category]
    weights_map = MERCHANT_WEIGHTS.get(category)
    if weights_map:
        weights = [weights_map.get(m, 5) for m in pool]
        return rng.choices(pool, weights=weights)[0]
    return rng.choice(pool)


def pick_city(category: str, merchant: str, rng: random.Random) -> str:
    if category == "travel" and merchant in ("MakeMyTrip", "IndiGo", "RedBus"):
        pool = [HOME_CITY] + TRAVEL_CITIES
        weights = [40] + [10] * len(TRAVEL_CITIES)
        return rng.choices(pool, weights=weights)[0]
    return HOME_CITY


def pick_time(category: str, txn_type: str, rng: random.Random) -> tuple[int, int, int]:
    if txn_type in ("fee", "interest"):
        # Bank-generated line items post during overnight batch runs.
        hour = rng.randint(0, 5)
    elif category == "food_dining":
        hour = rng.choice(list(range(11, 15)) + list(range(18, 23)))
    elif category == "fuel":
        hour = rng.choice(list(range(7, 11)) + list(range(17, 21)))
    else:
        hour = rng.randint(8, 23)
    return hour, rng.randint(0, 59), rng.randint(0, 59)


def txn_type_for(category: str, merchant: str) -> str:
    if category == "fees_interest":
        return FEES_INTEREST_TXN_TYPE.get(merchant, "fee")
    return "purchase"


# --------------------------------------------------------------------------
# Organic generation
# --------------------------------------------------------------------------

def generate_organic(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    for d in daterange(START_DATE, END_DATE):
        n = txn_count_for_day(rng, d)
        weights = category_weights_for_day(d)
        cats = list(weights.keys())
        wts = list(weights.values())
        for _ in range(n):
            category = rng.choices(cats, weights=wts, k=1)[0]
            merchant = pick_merchant(rng, category)
            low, high = MERCHANT_AMOUNT_OVERRIDES.get(merchant, AMOUNT_RANGES[category])
            amount = realistic_amount(rng, low, high)
            txn_type = txn_type_for(category, merchant)
            city = pick_city(category, merchant, rng)
            hour, minute, second = pick_time(category, txn_type, rng)
            ts = pd.Timestamp(d.year, d.month, d.day, hour, minute, second)
            rows.append({
                "timestamp": ts,
                "amount": amount,
                "merchant": merchant,
                "category": category,
                "card_id": CARD_ID,
                "txn_type": txn_type,
                "city": city,
                "currency": "INR",
            })
    return rows


# --------------------------------------------------------------------------
# Recurring subscriptions — 6 merchants, ~same amount, ~same day each month
# --------------------------------------------------------------------------

def generate_subscriptions(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    for sub in SUBSCRIPTIONS:
        for (y, m) in MONTHS:
            day = sub["day"] + rng.choice([-1, 0, 0, 0, 1])
            day = min(max(day, 1), last_day_of_month(y, m))
            amount = round(sub["amount"] * (1 + rng.uniform(-0.02, 0.02)), 2)
            hour, minute, second = rng.randint(6, 10), rng.randint(0, 59), rng.randint(0, 59)
            ts = pd.Timestamp(y, m, day, hour, minute, second)
            rows.append({
                "timestamp": ts,
                "amount": amount,
                "merchant": sub["merchant"],
                "category": sub["category"],
                "card_id": CARD_ID,
                "txn_type": "purchase",
                "city": HOME_CITY,
                "currency": "INR",
            })
    return rows


# --------------------------------------------------------------------------
# 15 refunds, matched to earlier purchases
# --------------------------------------------------------------------------

REFUNDABLE_CATEGORIES = {"shopping", "food_dining", "travel", "entertainment", "health"}


def generate_refunds(rng: random.Random, organic_rows: list[dict]) -> list[dict]:
    candidates = [
        r for r in organic_rows
        if r["txn_type"] == "purchase"
        and r["category"] in REFUNDABLE_CATEGORIES
        and r["amount"] >= 300
        and (END_DATE - r["timestamp"]).days >= 10
    ]
    chosen = rng.sample(candidates, 15)
    rows: list[dict] = []
    for i, orig in enumerate(chosen):
        delay_days = rng.randint(2, 9)
        refund_ts = orig["timestamp"] + pd.Timedelta(days=delay_days)
        is_partial = i < 3  # first 3 chosen are partial refunds, rest are full
        pct = rng.uniform(0.5, 0.85) if is_partial else 1.0
        refund_amount = -round(orig["amount"] * pct, 2)
        rows.append({
            "timestamp": refund_ts,
            "amount": refund_amount,
            "merchant": orig["merchant"],
            "category": orig["category"],
            "card_id": CARD_ID,
            "txn_type": "refund",
            "city": orig["city"],
            "currency": orig["currency"],
        })
    return rows


# --------------------------------------------------------------------------
# 1 EMI conversion with a monthly instalment series
# --------------------------------------------------------------------------

def generate_emi(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    y0, m0, d0 = EMI_PURCHASE_DATE
    purchase_amount = 35988.0
    rows.append({
        "timestamp": pd.Timestamp(y0, m0, d0, 12, 30, 0),
        "amount": purchase_amount,
        "merchant": "Croma",
        "category": "shopping",
        "card_id": CARD_ID,
        "txn_type": "purchase",
        "city": HOME_CITY,
        "currency": "INR",
    })
    installment = round(purchase_amount / 12, 2)
    y, m = next_month(y0, m0)
    for _ in range(12):
        day = min(15, last_day_of_month(y, m))
        rows.append({
            "timestamp": pd.Timestamp(y, m, day, 9, 0, 0),
            "amount": installment,
            "merchant": "Croma",
            "category": "shopping",
            "card_id": CARD_ID,
            "txn_type": "emi",
            "city": HOME_CITY,
            "currency": "INR",
        })
        y, m = next_month(y, m)
    return rows


# --------------------------------------------------------------------------
# 3 foreign-currency transactions with FX markup
# --------------------------------------------------------------------------

FX_RATE = 83.0        # illustrative USD->INR rate used to bill the card
FX_MARKUP_PCT = 3.5    # matches the forex markup worked example in PRD.md §7.3

FX_EVENTS = [
    {"date": (2025, 9, 10), "merchant": "Amazon.com", "category": "shopping", "city": "Seattle", "base_usd": 62.0},
    {"date": (2026, 2, 14), "merchant": "Booking.com", "category": "travel", "city": "Singapore", "base_usd": 145.0},
    {"date": (2026, 6, 5), "merchant": "Apple Store", "category": "entertainment", "city": "Dubai", "base_usd": 38.0},
]


def generate_fx(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    for ev in FX_EVENTS:
        y, m, d = ev["date"]
        # Amount billed to the card in INR, after conversion + FX markup —
        # this is what actually appears on a statement, so aggregations that
        # sum `amount` regardless of currency stay correct.
        amount_inr = round(ev["base_usd"] * FX_RATE * (1 + FX_MARKUP_PCT / 100), 2)
        ts = pd.Timestamp(y, m, d, rng.randint(10, 20), rng.randint(0, 59), 0)
        rows.append({
            "timestamp": ts,
            "amount": amount_inr,
            "merchant": ev["merchant"],
            "category": ev["category"],
            "card_id": CARD_ID,
            "txn_type": "purchase",
            "city": ev["city"],
            "currency": "USD",
        })
    return rows


# --------------------------------------------------------------------------
# 2 late fees, each followed by an interest charge
# --------------------------------------------------------------------------

def generate_late_fee_interest(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    for (y, m) in LATE_FEE_MONTHS:
        fee_day = rng.randint(18, 22)
        fee_ts = pd.Timestamp(y, m, fee_day, 2, 15, 0)
        rows.append({
            "timestamp": fee_ts,
            "amount": LATE_FEE_AMOUNT,
            "merchant": "Late Payment Fee",
            "category": "fees_interest",
            "card_id": CARD_ID,
            "txn_type": "fee",
            "city": HOME_CITY,
            "currency": "INR",
        })
        interest_ts = fee_ts + pd.Timedelta(days=int(rng.randint(3, 5)))
        interest_amount = round(rng.uniform(900, 1600), 2)
        rows.append({
            "timestamp": interest_ts,
            "amount": interest_amount,
            "merchant": "Interest Charge",
            "category": "fees_interest",
            "card_id": CARD_ID,
            "txn_type": "interest",
            "city": HOME_CITY,
            "currency": "INR",
        })
    return rows


# --------------------------------------------------------------------------
# 1 duplicate charge — same merchant, same amount, same day
# --------------------------------------------------------------------------

def generate_duplicate(rng: random.Random, organic_rows: list[dict]) -> list[dict]:
    candidates = [
        r for r in organic_rows
        if r["txn_type"] == "purchase" and r["category"] in ("food_dining", "groceries")
    ]
    orig = rng.choice(candidates)
    dup_ts = orig["timestamp"] + pd.Timedelta(minutes=rng.randint(20, 240))
    if dup_ts.date() != orig["timestamp"].date():
        dup_ts = orig["timestamp"] + pd.Timedelta(minutes=15)
    dup = dict(orig)
    dup["timestamp"] = dup_ts
    return [dup]


# --------------------------------------------------------------------------
# 1 genuine spend spike in one month
# --------------------------------------------------------------------------

SPIKE_EXTRA = [
    {"merchant": "IndiGo", "category": "travel", "amount": 9200.0, "day": 6, "city": "Goa"},
    {"merchant": "IndiGo", "category": "travel", "amount": 8600.0, "day": 6, "city": "Goa"},
    {"merchant": "MakeMyTrip", "category": "travel", "amount": 14500.0, "day": 5, "city": "Goa"},
    {"merchant": "Croma", "category": "shopping", "amount": 24000.0, "day": 14, "city": HOME_CITY},
    {"merchant": "Myntra", "category": "shopping", "amount": 7200.0, "day": 20, "city": HOME_CITY},
]


def generate_spike(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    y, m = SPIKE_MONTH
    for item in SPIKE_EXTRA:
        ts = pd.Timestamp(y, m, item["day"], rng.randint(10, 20), rng.randint(0, 59), 0)
        rows.append({
            "timestamp": ts,
            "amount": item["amount"],
            "merchant": item["merchant"],
            "category": item["category"],
            "card_id": CARD_ID,
            "txn_type": "purchase",
            "city": item["city"],
            "currency": "INR",
        })
    return rows


# --------------------------------------------------------------------------
# Dining reward-cap breach months (>=2) and a clean control month (>=1 under)
# --------------------------------------------------------------------------

DINING_BOOSTER_ITEMS = [
    ("Barbeque Nation", 4200.0),
    ("Barbeque Nation", 4600.0),
    ("Zomato", 3400.0),
    ("Swiggy", 3100.0),
    ("Barbeque Nation", 4100.0),
    ("Zomato", 3600.0),
    ("Swiggy", 2900.0),
]


def generate_dining_boosters(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    for (y, m) in DINING_BREACH_MONTHS:
        for i, (merchant, amount) in enumerate(DINING_BOOSTER_ITEMS):
            day = min(3 + i * 4, last_day_of_month(y, m))
            hour = rng.randint(19, 22)
            ts = pd.Timestamp(y, m, day, hour, rng.randint(0, 59), 0)
            rows.append({
                "timestamp": ts,
                "amount": amount,
                "merchant": merchant,
                "category": "food_dining",
                "card_id": CARD_ID,
                "txn_type": "purchase",
                "city": HOME_CITY,
                "currency": "INR",
            })
    return rows


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_dataset() -> pd.DataFrame:
    rng = random.Random(SEED)

    organic = generate_organic(rng)
    subs = generate_subscriptions(rng)
    refunds = generate_refunds(rng, organic)
    emi = generate_emi(rng)
    fx = generate_fx(rng)
    late = generate_late_fee_interest(rng)
    dup = generate_duplicate(rng, organic)
    spike = generate_spike(rng)
    dining_boost = generate_dining_boosters(rng)

    all_rows = organic + subs + refunds + emi + fx + late + dup + spike + dining_boost
    all_rows.sort(key=lambda r: r["timestamp"])

    for i, r in enumerate(all_rows, start=1):
        r["txn_id"] = f"TXN{i:06d}"

    df = pd.DataFrame(all_rows)
    df = df[["txn_id", "timestamp", "amount", "merchant", "category", "card_id", "txn_type", "city", "currency"]]
    df["amount"] = df["amount"].round(2).astype(float)
    return df


# --------------------------------------------------------------------------
# Realism assertions — the guarantee is enforced by running this script,
# not by eyeballing the CSV. Each check is a one-line-ish pandas filter.
# --------------------------------------------------------------------------

def run_assertions(df: pd.DataFrame) -> None:
    # --- schema sanity -----------------------------------------------------
    expected_cols = ["txn_id", "timestamp", "amount", "merchant", "category", "card_id", "txn_type", "city", "currency"]
    assert list(df.columns) == expected_cols, f"column order/schema drift: {list(df.columns)}"
    assert set(df["category"].unique()) <= set(CANONICAL_CATEGORIES), "category outside the 12 canonical names"
    assert set(df["txn_type"].unique()) <= VALID_TXN_TYPES, "txn_type outside purchase/refund/fee/interest/emi"
    assert df["card_id"].nunique() == 1 and df["card_id"].iloc[0] == CARD_ID, "card_id must be a constant single card"
    assert df["txn_id"].is_unique, "txn_id must be unique"

    # --- row count -----------------------------------------------------
    assert len(df) >= 1800, f"expected >=1800 rows, got {len(df)}"

    # --- 18-month span ---------------------------------------------------
    span_months = (df["timestamp"].max().to_period("M") - df["timestamp"].min().to_period("M")).n + 1
    assert span_months == 18, f"expected an 18-month span, got {span_months}"

    # --- weekday/weekend rhythm -----------------------------------------
    dow = df["timestamp"].dt.dayofweek
    daily_counts = df.groupby(df["timestamp"].dt.date).size()
    daily_dow = pd.Series(daily_counts.index).map(lambda d: pd.Timestamp(d).dayofweek)
    weekend_avg = daily_counts.values[daily_dow.values >= 5].mean()
    weekday_avg = daily_counts.values[daily_dow.values < 5].mean()
    assert weekend_avg > weekday_avg, f"no weekend rhythm: weekend {weekend_avg:.2f} <= weekday {weekday_avg:.2f}"

    # --- monthly salary-week spike ----------------------------------------
    spend = df[df["amount"] > 0].copy()
    spend["day"] = spend["timestamp"].dt.day
    salary_week_daily_total = spend[spend["day"] <= 5].groupby(spend["timestamp"].dt.date)["amount"].sum().mean()
    rest_of_month_daily_total = spend[spend["day"] > 5].groupby(spend["timestamp"].dt.date)["amount"].sum().mean()
    assert salary_week_daily_total > rest_of_month_daily_total, "no salary-week spike in daily spend"

    # --- festive season lift (Oct-Nov) ------------------------------------
    monthly_spend = spend.groupby(spend["timestamp"].dt.to_period("M"))["amount"].sum()
    festive_months = monthly_spend[monthly_spend.index.month.isin([10, 11])]
    other_months = monthly_spend[~monthly_spend.index.month.isin([10, 11])]
    assert festive_months.mean() > other_months.mean(), "no festive-season (Oct-Nov) lift"

    # --- 6 recurring subscriptions -----------------------------------------
    for sub in SUBSCRIPTIONS:
        rows = df[df["merchant"] == sub["merchant"]]
        assert len(rows) >= 15, f"{sub['merchant']} subscription missing occurrences: {len(rows)}"
        assert rows["amount"].std() / rows["amount"].mean() < 0.05, f"{sub['merchant']} amount not ~stable"
        assert rows["timestamp"].dt.day.std() < 1.5, f"{sub['merchant']} not charged on ~the same day each month"
    assert len(SUBSCRIPTIONS) == 6

    # --- 15 refunds matched to earlier purchases ---------------------------
    refunds = df[df["txn_type"] == "refund"]
    assert len(refunds) == 15, f"expected 15 refunds, got {len(refunds)}"
    assert (refunds["amount"] < 0).all(), "refunds must be negative amounts"
    for _, r in refunds.iterrows():
        match = df[
            (df["txn_type"] == "purchase")
            & (df["merchant"] == r["merchant"])
            & (df["timestamp"] < r["timestamp"])
            & (df["amount"] >= -r["amount"] - 0.01)
        ]
        assert len(match) >= 1, f"refund at {r['timestamp']} for {r['merchant']} has no matching earlier purchase"

    # --- 1 EMI conversion with a monthly instalment series ------------------
    emi_rows = df[df["txn_type"] == "emi"]
    assert emi_rows["merchant"].nunique() == 1, "EMI instalments should belong to a single conversion"
    assert len(emi_rows) >= 6, f"expected an EMI instalment series (>=6 rows), got {len(emi_rows)}"
    original_purchase = df[(df["merchant"] == emi_rows["merchant"].iloc[0]) & (df["txn_type"] == "purchase")]
    assert len(original_purchase) >= 1, "EMI series has no originating purchase"

    # --- 3 foreign-currency transactions with FX markup ---------------------
    fx_rows = df[df["currency"] != "INR"]
    assert len(fx_rows) == 3, f"expected 3 FX transactions, got {len(fx_rows)}"
    for ev in FX_EVENTS:
        expected = round(ev["base_usd"] * FX_RATE * (1 + FX_MARKUP_PCT / 100), 2)
        actual = fx_rows[fx_rows["merchant"] == ev["merchant"]]["amount"].iloc[0]
        assert actual > ev["base_usd"] * FX_RATE, f"{ev['merchant']} FX amount does not reflect a markup"
        assert abs(actual - expected) < 0.01

    # --- 2 late fees, each followed by an interest charge --------------------
    late_fees = df[(df["txn_type"] == "fee") & (df["merchant"] == "Late Payment Fee")]
    assert len(late_fees) == 2, f"expected 2 late fees, got {len(late_fees)}"
    for _, fee_row in late_fees.iterrows():
        follow_up = df[
            (df["txn_type"] == "interest")
            & (df["merchant"] == "Interest Charge")
            & (df["timestamp"] > fee_row["timestamp"])
            & (df["timestamp"] <= fee_row["timestamp"] + pd.Timedelta(days=10))
        ]
        assert len(follow_up) >= 1, f"late fee at {fee_row['timestamp']} has no following interest charge"

    # --- 1 duplicate charge (same merchant, same amount, same day) -----------
    purchases = df[df["txn_type"] == "purchase"].copy()
    purchases["date"] = purchases["timestamp"].dt.date
    dup_groups = purchases.groupby(["merchant", "amount", "date"]).size()
    assert (dup_groups >= 2).sum() >= 1, "no duplicate same-merchant/same-amount/same-day charge found"

    # --- 1 genuine spend spike month ----------------------------------------
    spike_period = pd.Period(f"{SPIKE_MONTH[0]}-{SPIKE_MONTH[1]:02d}")
    spike_total = monthly_spend.loc[spike_period]
    other_totals = monthly_spend.drop(spike_period)
    assert spike_total > other_totals.median() * 1.4, "spike month is not clearly higher than a typical month"

    # --- dining reward-cap breach: >=2 months over, >=1 month under ----------
    dining_monthly = spend[spend["category"] == "food_dining"].groupby(spend["timestamp"].dt.to_period("M"))["amount"].sum()
    breach_months = dining_monthly[dining_monthly > REFERENCE_DINING_CAP_SPEND]
    under_cap_months = dining_monthly[dining_monthly <= REFERENCE_DINING_CAP_SPEND]
    assert len(breach_months) >= 2, f"expected >=2 months over the ₹{REFERENCE_DINING_CAP_SPEND:.0f} dining cap, got {len(breach_months)}"
    assert len(under_cap_months) >= 1, "expected at least 1 month with dining spend under the cap"

    # --- enough cash_advance and fees_interest rows for exclusion testing ----
    assert (df["category"] == "cash_advance").sum() >= 8, "not enough cash_advance rows to test reward exclusions"
    assert (df["category"] == "fees_interest").sum() >= 8, "not enough fees_interest rows to test reward exclusions"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    df = build_dataset()
    run_assertions(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    out.to_csv(OUTPUT_PATH, index=False)

    # --- summary -------------------------------------------------------
    print(f"Wrote {len(df)} rows to {OUTPUT_PATH}")
    print(f"Date range: {df['timestamp'].min()} .. {df['timestamp'].max()}")
    print(f"Categories: {sorted(df['category'].unique())}")
    print(f"txn_type counts:\n{df['txn_type'].value_counts()}")
    print(f"Merchants in ALL_MERCHANTS: {len(ALL_MERCHANTS)}")
    print("All realism assertions passed.")


if __name__ == "__main__":
    main()
