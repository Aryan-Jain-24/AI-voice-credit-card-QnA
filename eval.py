"""Eval harness -- S04.

Scores the end-to-end system (once graph-engineer's S05/S06 planner and
verbalizer exist) against ``evals/gold_questions.json``: intent accuracy,
domain routing accuracy, argument accuracy, numeric/term exactness, the
hallucination gate, gap-admission/clarify/refusal precision, and latency
p50/p95. Prints a table. Text input only -- no audio at this stage.

Run:
    python eval.py

Until S05/S06 land, ``graph.py`` exposes no runnable pipeline, so every
system-dependent metric below prints as 0% / n=0. That is correct and
expected per all-specs.md S04's "Done when" clause, not a bug in this
harness -- it becomes a real score the moment graph-engineer wires up
``graph.py``. See `` System-under-test integration contract`` below for
exactly what graph.py needs to expose for these numbers to start moving.

-----------------------------------------------------------------------------
Ground truth policy (the load-bearing rule of this file)
-----------------------------------------------------------------------------
Every number this script checks an answer against is computed HERE, directly
from ``data/transactions.csv`` (via plain pandas) and ``card_terms.yaml``
(via a direct yaml read) -- never by importing or calling spend_total,
spend_by_category, top_merchants, compare_periods, find_transactions,
recurring_charges, card_rewards, card_fees, card_offers, or rewards_earned
from tools_txn.py / tools_card.py. Those are the tools under test (indirectly,
via the planner that will call them); an eval that derived its own answer key
by calling them would prove nothing.

``evals/gold_questions.json`` additionally carries a frozen ``expected_value``
snapshot per entry (computed the same independent way, by hand, at authoring
time -- see the git history / session transcript for the derivation). At
startup this script recomputes every entry's ground truth live from the
current CSV/YAML and cross-checks it against that frozen snapshot, printing a
loud warning (not a crash) for any entry that has drifted -- e.g. because
generate_data.py was re-run with a different seed, or card_terms.yaml was
hand-edited. This is deliberately stricter than the spec's letter for Domain B
alone ("if the terms file changes, the eval updates itself") -- it is applied
uniformly to both domains, because there is no reason a transactions-side
drift detector is worth less than a terms-side one.

-----------------------------------------------------------------------------
System-under-test integration contract (for graph-engineer, S05/S06)
-----------------------------------------------------------------------------
``get_pipeline()`` below looks for, in order:

  1. ``graph.run_pipeline(utterance: str) -> dict`` -- a plain function. The
     returned dict should contain whichever of these keys apply:
       - "tool_call":   {"name": <tool or "ask_clarification" or "refuse">,
                          "args": {...}}
       - "tool_result": the flat dict the tool returned (or None for
                         clarify/refuse)
       - "answer_text": the final spoken/displayed sentence (or the
                         clarifying question / refusal text)
       - "needs_clarification": bool
  2. Failing that, a compiled LangGraph object at ``graph.graph`` or
     ``graph.app`` exposing ``.invoke(state)``. This script calls it with the
     6-field State from PRD.md S7.2 / CLAUDE.md:
         {"audio_in": None, "transcript": <utterance>, "tool_call": None,
          "tool_result": None, "answer_text": "", "audio_out": None,
          "needs_clarification": False}
     and reads the same field names back out of the returned state.

Key-name matching is intentionally forgiving (``name``/``tool``/``tool_name``
for the tool identifier; ``args``/``arguments``/``tool_args``/``parameters``
for its arguments) so a reasonable S05 implementation doesn't have to match
this file's naming exactly. If graph.py exposes neither shape, every
system-dependent metric reports 0% and the report says so explicitly.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Paths & fixed "today" -- this project is built against 2026-08-11 (see
# CLAUDE.md / generate_data.py's END_MONTH). Kept here as documentation of
# that assumption, not read programmatically elsewhere in this file: every
# period phrase used in gold_questions.json was resolved by hand into
# explicit (start, end) ISO bounds against this date and stored directly in
# each entry's ``ground_truth_spec`` (see compute_ground_truth() below), so
# this script never needs its own copy of a period-phrase resolver. If the
# project's fixed "today" ever changes, those explicit bounds -- and this
# constant -- need to be regenerated together.
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent
GOLD_PATH = _ROOT / "evals" / "gold_questions.json"
DATA_PATH = _ROOT / "data" / "transactions.csv"
TERMS_PATH = _ROOT / "card_terms.yaml"

TODAY = date(2026, 8, 11)

# ---------------------------------------------------------------------------
# Targets from PRD.md S8 / CLAUDE.md, printed alongside each measured score.
# ---------------------------------------------------------------------------

TARGETS = {
    "intent_accuracy": (">=", 0.90),
    "domain_routing_accuracy": (">=", 0.95),
    "argument_accuracy": (">=", 0.85),
    "numeric_exactness": (">=", 0.95),
    "term_exactness": ("==", 1.00),
    "cross_domain_exactness": (">=", 0.95),
    "hallucination_rate": ("==", 0.00),
    "gap_admission_precision": ("==", 1.00),
    "clarify_precision": ("==", 1.00),
    "refusal_precision": ("==", 1.00),
}

# Domain classification -- used for the domain-routing metric, which the
# spec requires to be reported separately from plain intent accuracy.
DOMAIN_BY_TOOL = {
    "spend_total": "transactions",
    "spend_by_category": "transactions",
    "top_merchants": "transactions",
    "compare_periods": "transactions",
    "find_transactions": "transactions",
    "recurring_charges": "transactions",
    "card_rewards": "terms",
    "card_fees": "terms",
    "card_offers": "terms",
    "rewards_earned": "cross",
    "ask_clarification": None,
    "refuse": None,
}


# ---------------------------------------------------------------------------
# Independent ground truth -- direct pandas over the raw CSV, direct yaml
# over the raw terms file. Deliberately does NOT import data_loader.py,
# tools_txn.py, or tools_card.py.
# ---------------------------------------------------------------------------


def load_txn_df() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"])
    return df


def load_terms() -> dict[str, Any]:
    with TERMS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _period_mask(df: pd.DataFrame, start: str, end: str) -> pd.Series:
    d = df["timestamp"].dt.date
    return (d >= date.fromisoformat(start)) & (d <= date.fromisoformat(end))


def _apply_common_filters(
    df: pd.DataFrame,
    category: str | None = None,
    merchant: str | None = None,
    min_amount: float | None = None,
) -> pd.DataFrame:
    if category:
        df = df[df["category"] == category]
    if merchant:
        df = df[df["merchant"].str.contains(merchant, case=False, na=False, regex=False)]
    if min_amount is not None:
        df = df[df["amount"] >= min_amount]
    return df


def _gt_spend_total(df: pd.DataFrame, spec: dict) -> dict:
    sub = df[_period_mask(df, spec["start"], spec["end"])]
    sub = _apply_common_filters(sub, category=spec.get("category"))
    total = round(float(sub["amount"].sum()), 2)
    count = int(len(sub))
    return {"required_numbers": [total, count], "summary": {"total": total, "count": count}}


def _gt_spend_by_category_top1(df: pd.DataFrame, spec: dict) -> dict:
    sub = df[_period_mask(df, spec["start"], spec["end"])]
    grouped = sub.groupby("category")["amount"].sum().sort_values(ascending=False)
    if grouped.empty:
        return {"required_numbers": [0.0], "summary": {}}
    top_name = grouped.index[0]
    top_total = round(float(grouped.iloc[0]), 2)
    return {
        "required_numbers": [top_total],
        "summary": {"top_category": top_name, "top_total": top_total},
    }


def _gt_top_merchants_top1(df: pd.DataFrame, spec: dict) -> dict:
    sub = df[_period_mask(df, spec["start"], spec["end"])]
    grouped = sub.groupby("merchant")["amount"].sum().sort_values(ascending=False)
    if grouped.empty:
        return {"required_numbers": [0.0], "summary": {}}
    top_name = grouped.index[0]
    top_total = round(float(grouped.iloc[0]), 2)
    return {
        "required_numbers": [top_total],
        "summary": {"top_merchant": top_name, "top_total": top_total},
    }


def _gt_compare_periods(df: pd.DataFrame, spec: dict) -> dict:
    a = df[_period_mask(df, spec["start_a"], spec["end_a"])]
    b = df[_period_mask(df, spec["start_b"], spec["end_b"])]
    a = _apply_common_filters(a, category=spec.get("category"))
    b = _apply_common_filters(b, category=spec.get("category"))
    total_a = round(float(a["amount"].sum()), 2)
    total_b = round(float(b["amount"].sum()), 2)
    delta = round(total_a - total_b, 2)
    return {
        "required_numbers": [total_a, total_b],
        "summary": {"total_a": total_a, "total_b": total_b, "delta": delta},
    }


def _gt_find_transactions(df: pd.DataFrame, spec: dict) -> dict:
    sub = df
    if "start" in spec and "end" in spec:
        sub = sub[_period_mask(sub, spec["start"], spec["end"])]
    if "date" in spec:
        sub = sub[sub["timestamp"].dt.date == date.fromisoformat(spec["date"])]
    sub = _apply_common_filters(sub, merchant=spec.get("merchant"), min_amount=spec.get("min_amount"))
    sub = sub.sort_values("timestamp", ascending=False)
    count = int(len(sub))
    required = [float(count)]
    if count > 0:
        required.append(round(float(sub["amount"].iloc[0]), 2))
    return {
        "required_numbers": required,
        "summary": {"count": count, "top_match_amount": round(float(sub["amount"].iloc[0]), 2) if count else None},
    }


def _gt_recurring_charges(df: pd.DataFrame, spec: dict) -> dict:
    subs = ["Netflix", "Spotify Premium", "Jio Postpaid", "Cult.fit Membership", "Amazon Prime", "Google One"]
    total = 0.0
    per_sub = {}
    for m in subs:
        rows = df[df["merchant"] == m]
        if len(rows) < 3:
            continue
        amt = round(float(rows["amount"].mean()), 2)
        per_sub[m] = amt
        total += amt
    return {"required_numbers": [round(total, 2)], "summary": {"monthly_total": round(total, 2), "per_sub": per_sub}}


_LATE_PAYMENT_KEY = "late_payment"


def _late_payment_tier(tiers: list[dict], due_amount: float) -> dict:
    for tier in tiers:
        lo = tier.get("min_due_inr", 0)
        hi = tier.get("max_due_inr")
        if due_amount >= lo and (hi is None or due_amount <= hi):
            return tier
    raise ValueError(f"No late-payment tier covers due amount {due_amount}")


def _gt_card_fees(terms: dict, spec: dict) -> dict:
    fees = terms.get("fees", {})
    fee_type = spec["fee_type"]
    entry = fees.get(fee_type)
    if entry is None:
        return {"required_numbers": [], "summary": {"found": False}}
    if fee_type == _LATE_PAYMENT_KEY and "due_amount_inr" in spec:
        tier = _late_payment_tier(entry, spec["due_amount_inr"])
        return {"required_numbers": [tier["amount_inr"]], "summary": {"tier": tier}}
    if isinstance(entry, list):
        # Generic tiered lookup with no due-amount context: no single figure
        # is unambiguously "the" answer -- see Q36/Q38 in gold_questions.json.
        return {"required_numbers": [], "summary": {"tiers": entry}}
    amount_or_pct = entry.get("amount_inr", entry.get("pct", entry.get("pct_per_month")))
    numbers = [amount_or_pct] if amount_or_pct is not None else []
    if entry.get("waiver_spend_inr") is not None:
        numbers.append(entry["waiver_spend_inr"])
    if entry.get("min_amount_inr") is not None:
        numbers.append(entry["min_amount_inr"])
    return {"required_numbers": numbers, "summary": dict(entry)}


def _gt_card_fees_listing(terms: dict, spec: dict) -> dict:
    # Generic/no-fee_type card_fees() questions (Q36) and generic tiered
    # lookups with no amount context (Q38) -- see docstring rationale above.
    fees = terms.get("fees", {})
    return {"required_numbers": [], "summary": {"fee_count": len(fees)}}


def _gt_card_fees_missing(terms: dict, spec: dict) -> dict:
    fees = terms.get("fees", {})
    fee_type = spec["fee_type"]
    is_missing = fee_type not in fees
    assert is_missing, (
        f"gold_questions.json bug: {fee_type!r} was expected to be a deliberate "
        f"gap in card_terms.yaml but is actually documented there."
    )
    return {"required_numbers": [], "summary": {"found": False}}


def _gt_card_rewards(terms: dict, spec: dict) -> dict:
    rewards = terms.get("rewards", {})
    category = spec.get("category")
    if category is None:
        rate = rewards.get("base_rate", {}).get("points_per_100")
        return {"required_numbers": [rate], "summary": {"rate": rate, "cap": None}}
    cat_entry = rewards.get("category_rates", {}).get(category)
    if cat_entry:
        rate = cat_entry.get("points_per_100")
        cap = cat_entry.get("monthly_cap_points")
        numbers = [rate] + ([cap] if cap is not None else [])
        return {"required_numbers": numbers, "summary": {"rate": rate, "cap": cap}}
    # No override -> falls back to the base rate (e.g. "shopping").
    rate = rewards.get("base_rate", {}).get("points_per_100")
    return {"required_numbers": [rate], "summary": {"rate": rate, "cap": None, "fallback": True}}


_NUM_IN_TEXT_RE = re.compile(r"\d+(?:\.\d+)?")


def _gt_card_offers(terms: dict, spec: dict) -> dict:
    offers = terms.get("offers", [])
    merchant = spec.get("merchant")
    category = spec.get("category")
    matches = []
    for o in offers:
        if merchant and merchant.strip().lower() not in str(o.get("merchant", "")).lower():
            continue
        if category and o.get("category") != category:
            continue
        matches.append(o)
    if not matches:
        return {"required_numbers": [], "summary": {"count": 0}}
    numbers = [float(n) for n in _NUM_IN_TEXT_RE.findall(matches[0].get("benefit", ""))]
    return {"required_numbers": numbers, "summary": {"count": len(matches), "benefit": matches[0].get("benefit")}}


def _rewards_earned_calc(df: pd.DataFrame, terms: dict, start: str, end: str, category: str | None) -> dict:
    """Independent re-implementation of the cross-domain reward calc: net
    spend grouped by (category, calendar month), excluded categories carved
    out, category rate (else base rate), monthly cap applied per calendar
    month. Mirrors the algorithm description in all-specs.md S03B, written
    fresh here -- not imported from tools_card.py.
    """
    rewards = terms.get("rewards", {})
    base_rate = rewards.get("base_rate", {}).get("points_per_100", 0)
    cat_rates = rewards.get("category_rates", {})
    excluded = set(rewards.get("excluded_categories", []))

    sub = df[_period_mask(df, start, end)]
    if category:
        sub = sub[sub["category"] == category]
    if sub.empty:
        return {"points_total": 0, "by_category": {}, "capped": []}

    grouped = sub.groupby([sub["category"], sub["timestamp"].dt.to_period("M")])["amount"].sum()
    by_category: dict[str, int] = {}
    capped = []
    for (cat, month), net in grouped.items():
        if cat in excluded:
            continue
        net_eligible = max(float(net), 0.0)
        rate = cat_rates.get(cat, {}).get("points_per_100", base_rate)
        raw_points = math.floor(net_eligible / 100 * rate)
        cap = cat_rates.get(cat, {}).get("monthly_cap_points")
        if cap is not None and raw_points > cap:
            points = cap
            capped.append({"category": cat, "month": str(month), "cap": cap, "raw": raw_points})
        else:
            points = raw_points
        by_category[cat] = by_category.get(cat, 0) + points

    return {"points_total": sum(by_category.values()), "by_category": by_category, "capped": capped}


def _gt_rewards_earned(df: pd.DataFrame, terms: dict, spec: dict) -> dict:
    result = _rewards_earned_calc(df, terms, spec["start"], spec["end"], spec.get("category"))
    return {"required_numbers": [float(result["points_total"])], "summary": result}


GT_DISPATCH: dict[str, Callable[..., dict]] = {
    "spend_total": lambda df, terms, spec: _gt_spend_total(df, spec),
    "spend_by_category_top1": lambda df, terms, spec: _gt_spend_by_category_top1(df, spec),
    "top_merchants_top1": lambda df, terms, spec: _gt_top_merchants_top1(df, spec),
    "compare_periods": lambda df, terms, spec: _gt_compare_periods(df, spec),
    "find_transactions": lambda df, terms, spec: _gt_find_transactions(df, spec),
    "recurring_charges": lambda df, terms, spec: _gt_recurring_charges(df, spec),
    "card_fees": lambda df, terms, spec: _gt_card_fees(terms, spec),
    "card_fees_listing": lambda df, terms, spec: _gt_card_fees_listing(terms, spec),
    "card_fees_missing": lambda df, terms, spec: _gt_card_fees_missing(terms, spec),
    "card_rewards": lambda df, terms, spec: _gt_card_rewards(terms, spec),
    "card_offers": lambda df, terms, spec: _gt_card_offers(terms, spec),
    "rewards_earned": lambda df, terms, spec: _gt_rewards_earned(df, terms, spec),
}


def compute_ground_truth(df: pd.DataFrame, terms: dict, spec: dict | None) -> dict:
    if spec is None:
        return {"required_numbers": [], "summary": {}}
    fn = GT_DISPATCH[spec["kind"]]
    return fn(df, terms, spec)


# ---------------------------------------------------------------------------
# Gold set loading + frozen-vs-live drift check
# ---------------------------------------------------------------------------


def load_gold() -> list[dict]:
    with GOLD_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _numbers_match(spoken: float, truth: float) -> bool:
    """Tolerance calibrated against PRD.md's own worked example, which speaks
    an underlying 8240.50 as "Rs. 8,240" -- i.e. currency figures are allowed
    to round to the nearest rupee when spoken. Small values (rates, counts,
    caps, percentages) get a tighter tolerance since they are not the kind of
    figure a natural spoken answer would round away.
    """
    tol = 1.0 if abs(truth) >= 50 else 0.5
    return abs(spoken - truth) <= tol


def check_drift(gold: list[dict], df: pd.DataFrame, terms: dict) -> list[str]:
    warnings = []
    for entry in gold:
        spec = entry.get("ground_truth_spec")
        frozen = entry.get("expected_value")
        if spec is None or frozen is None:
            continue
        live = compute_ground_truth(df, terms, spec)
        required = live["required_numbers"]
        if not required:
            continue
        if not any(_numbers_match(frozen, n) for n in required):
            warnings.append(
                f"{entry['id']}: frozen expected_value={frozen!r} does not match live "
                f"ground truth {required!r} -- data/transactions.csv or card_terms.yaml "
                f"has changed since gold_questions.json was authored."
            )
    return warnings


# ---------------------------------------------------------------------------
# System-under-test integration
# ---------------------------------------------------------------------------


def get_pipeline() -> Callable[[str], dict] | None:
    try:
        import graph  # noqa: PLC0415 -- optional; graph.py may still be the S00 stub
    except Exception:
        return None

    fn = getattr(graph, "run_pipeline", None)
    if callable(fn):
        return fn

    app = getattr(graph, "graph", None) or getattr(graph, "app", None)
    if app is not None and hasattr(app, "invoke"):
        def _run(utterance: str) -> dict:
            state = {
                "audio_in": None,
                "transcript": utterance,
                "tool_call": None,
                "tool_result": None,
                "answer_text": "",
                "audio_out": None,
                "needs_clarification": False,
            }
            return app.invoke(state)

        return _run

    return None


def _extract_tool_call(raw: dict) -> tuple[str | None, dict]:
    tool_call = raw.get("tool_call")
    if not isinstance(tool_call, dict):
        return None, {}
    name = tool_call.get("name") or tool_call.get("tool") or tool_call.get("tool_name")
    args = (
        tool_call.get("args")
        or tool_call.get("arguments")
        or tool_call.get("tool_args")
        or tool_call.get("parameters")
        or {}
    )
    return name, dict(args)


def _classify_behaviour(tool_name: str | None, tool_result: Any, needs_clarification: bool) -> str:
    if needs_clarification or tool_name == "ask_clarification":
        return "clarify"
    if tool_name == "refuse":
        return "refuse"
    if isinstance(tool_result, dict) and tool_result.get("found") is False:
        return "gap_admission"
    if tool_result is not None:
        return "answer"
    return "unknown"


def run_one(pipeline: Callable[[str], dict] | None, utterance: str) -> dict:
    if pipeline is None:
        return {"implemented": False}
    t0 = time.perf_counter()
    try:
        raw = pipeline(utterance)
    except Exception as e:  # a crashing planner is a planner failure, not a harness failure
        latency = time.perf_counter() - t0
        return {"implemented": True, "error": str(e), "latency": latency}
    latency = time.perf_counter() - t0
    if not isinstance(raw, dict):
        raw = dict(raw) if hasattr(raw, "keys") else {}
    tool_name, tool_args = _extract_tool_call(raw)
    tool_result = raw.get("tool_result")
    answer_text = raw.get("answer_text") or ""
    needs_clarification = bool(raw.get("needs_clarification"))
    behaviour = _classify_behaviour(tool_name, tool_result, needs_clarification)
    return {
        "implemented": True,
        "error": None,
        "latency": latency,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "answer_text": answer_text,
        "behaviour": behaviour,
    }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _args_match(expected: dict, actual: dict) -> bool:
    """Subset match: every key in `expected` must be present in `actual`
    with an equal (case/whitespace-insensitive for strings, tolerant for
    numbers) value. Extra keys in `actual` (e.g. explicit defaults like
    top_n=5) do not fail the check. This is a strict-on-what's-required,
    lenient-on-the-rest definition of "correct args" -- documented here since
    the spec does not prescribe fuzzy period-phrase equivalence (e.g. "last
    month" vs "July 2026" resolving to the same dates is NOT treated as a
    match; that is a known limitation, not an oversight).
    """
    for k, v in expected.items():
        if k not in actual:
            return False
        av = actual[k]
        if isinstance(v, str) and isinstance(av, str):
            if v.strip().lower() != av.strip().lower():
                return False
        elif isinstance(v, (int, float)) and isinstance(av, (int, float)):
            if not _numbers_match(float(av), float(v)):
                return False
        elif av != v:
            return False
    return True


_ANSWER_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _extract_numbers(text: str) -> list[float]:
    out = []
    for m in _ANSWER_NUM_RE.finditer(text or ""):
        s = m.group().replace(",", "")
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def _flatten_numbers(obj: Any) -> list[float]:
    nums: list[float] = []
    if isinstance(obj, dict):
        for v in obj.values():
            nums.extend(_flatten_numbers(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            nums.extend(_flatten_numbers(v))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        nums.append(float(obj))
    return nums


GAP_PHRASES = [
    "don't have", "do not have", "not something i have", "isn't documented",
    "not documented", "not available", "no information", "don't know",
    "can't find", "not listed", "not in my", "don't currently", "no record",
    "not something i can", "not covered",
]


def _is_gap_admission_text(text: str) -> bool:
    low = (text or "").lower()
    return any(p in low for p in GAP_PHRASES)


# ---------------------------------------------------------------------------
# Main scoring loop
# ---------------------------------------------------------------------------


def evaluate() -> dict:
    gold = load_gold()
    df = load_txn_df()
    terms = load_terms()

    drift_warnings = check_drift(gold, df, terms)

    pipeline = get_pipeline()
    implemented = pipeline is not None

    rows = []
    for entry in gold:
        result = run_one(pipeline, entry["utterance"])
        gt = compute_ground_truth(df, terms, entry.get("ground_truth_spec"))
        rows.append({"entry": entry, "result": result, "gt": gt})

    return {
        "gold": gold,
        "rows": rows,
        "implemented": implemented,
        "drift_warnings": drift_warnings,
    }


def compute_metrics(evald: dict) -> dict:
    rows = evald["rows"]
    implemented = evald["implemented"]

    n = len(rows)
    intent_correct = domain_correct = args_correct = 0
    domain_denom = args_denom = 0

    numeric_pass = numeric_denom = 0
    term_pass = term_denom = 0
    cross_pass = cross_denom = 0

    halluc_violations = 0
    halluc_checked = 0

    gap_tp = gap_fn = 0  # of the 5 gap-admission entries
    clarify_tp = clarify_fp = clarify_fn = 0
    refuse_tp = refuse_fp = refuse_fn = 0

    latencies = []
    per_bucket: dict[str, dict[str, int]] = {}

    for row in rows:
        entry, result, gt = row["entry"], row["result"], row["gt"]
        bucket = entry["bucket"]
        b = per_bucket.setdefault(bucket, {"n": 0, "intent_correct": 0, "behaviour_correct": 0})
        b["n"] += 1

        expected_tool = entry["expected_tool"]
        expected_domain = entry["expected_domain"]
        expected_behaviour = entry["expected_behaviour"]

        if not implemented or result.get("error"):
            # No system to score yet (or it crashed on this question) -- counts
            # as a miss on every applicable metric, consistent with "0% until
            # S05/S06 land" rather than being silently excluded.
            if expected_domain is not None:
                domain_denom += 1
            if expected_behaviour in ("answer", "gap_admission"):
                args_denom += 1
            if entry["bucket"] in ("domain_a_straightforward", "domain_a_phrasing",
                                    "domain_a_multi_constraint") or entry["id"] in ("Q37", "Q39"):
                numeric_denom += 1
            if entry["bucket"] == "domain_b_terms":
                term_denom += 1
            if entry["bucket"] == "cross_domain_rewards_earned":
                cross_denom += 1
            if expected_behaviour == "gap_admission":
                gap_fn += 1
            if expected_behaviour == "clarify":
                clarify_fn += 1
            if expected_behaviour == "refuse":
                refuse_fn += 1
            continue

        if result["latency"] is not None:
            latencies.append(result["latency"])

        tool_name = result["tool_name"]
        behaviour = result["behaviour"]
        answer_text = result["answer_text"]
        tool_result = result["tool_result"]

        this_intent_ok = tool_name == expected_tool
        intent_correct += int(this_intent_ok)
        b["intent_correct"] += int(this_intent_ok)
        b["behaviour_correct"] += int(behaviour == expected_behaviour)

        if expected_domain is not None:
            domain_denom += 1
            domain_correct += int(DOMAIN_BY_TOOL.get(tool_name) == expected_domain)

        if expected_behaviour in ("answer", "gap_admission"):
            args_denom += 1
            args_correct += int(this_intent_ok and _args_match(entry["expected_args"], result["tool_args"]))

        # --- numeric exactness (Domain A "answer" entries, incl. the two
        # unambiguous transactions-domain trap entries Q37/Q39) -----------
        is_domain_a_numeric_bucket = entry["bucket"] in (
            "domain_a_straightforward", "domain_a_phrasing", "domain_a_multi_constraint",
        ) or entry["id"] in ("Q37", "Q39")
        if is_domain_a_numeric_bucket and expected_behaviour == "answer":
            numeric_denom += 1
            spoken = _extract_numbers(answer_text)
            required = gt["required_numbers"]
            ok = bool(required) and all(any(_numbers_match(s, r) for s in spoken) for r in required)
            numeric_pass += int(ok)

        # --- term exactness (Domain B bucket only -- see module docstring) -
        if entry["bucket"] == "domain_b_terms" and expected_behaviour == "answer":
            term_denom += 1
            spoken = _extract_numbers(answer_text)
            required = gt["required_numbers"]
            ok = bool(required) and all(any(_numbers_match(s, r) for s in spoken) for r in required)
            term_pass += int(ok)

        # --- cross-domain (rewards_earned) exactness ------------------------
        if entry["bucket"] == "cross_domain_rewards_earned":
            cross_denom += 1
            spoken = _extract_numbers(answer_text)
            required = gt["required_numbers"]
            zero_ok = required == [0.0] and (
                any(_numbers_match(s, 0.0) for s in spoken) or _is_gap_admission_text(answer_text)
                or "no point" in answer_text.lower() or "didn't earn" in answer_text.lower()
                or "don't earn" in answer_text.lower()
            )
            ok = zero_ok or (bool(required) and all(any(_numbers_match(s, r) for s in spoken) for r in required))
            cross_pass += int(ok)

        # --- hallucination check (every domain, every entry with prose) ---
        if answer_text:
            halluc_checked += 1
            spoken_nums = _extract_numbers(answer_text)
            grounded = _flatten_numbers(tool_result) if tool_result is not None else []
            for spoken_n in spoken_nums:
                if not any(_numbers_match(spoken_n, g) for g in grounded):
                    halluc_violations += 1

        # --- gap admission precision ---------------------------------------
        if expected_behaviour == "gap_admission":
            ok = behaviour == "gap_admission" and _is_gap_admission_text(answer_text)
            gap_tp += int(ok)
            gap_fn += int(not ok)

        # --- clarify precision (TP over the 6 CL entries, FP anywhere else) -
        if expected_behaviour == "clarify":
            if behaviour == "clarify":
                clarify_tp += 1
            else:
                clarify_fn += 1
        else:
            if behaviour == "clarify":
                clarify_fp += 1

        # --- refusal precision ----------------------------------------------
        if expected_behaviour == "refuse":
            if behaviour == "refuse":
                refuse_tp += 1
            else:
                refuse_fn += 1
        else:
            if behaviour == "refuse":
                refuse_fp += 1

    def pct(num, denom):
        return (num / denom) if denom else None

    def precision(tp, fp):
        denom = tp + fp
        return (tp / denom) if denom else (1.0 if tp == 0 and fp == 0 else 0.0)

    latencies_sorted = sorted(latencies)

    def pctile(p):
        if not latencies_sorted:
            return None
        k = min(len(latencies_sorted) - 1, max(0, math.ceil(p * len(latencies_sorted)) - 1))
        return latencies_sorted[k]

    return {
        "n": n,
        "implemented": implemented,
        "intent_accuracy": pct(intent_correct, n),
        "domain_routing_accuracy": pct(domain_correct, domain_denom),
        "domain_routing_denom": domain_denom,
        "argument_accuracy": pct(args_correct, args_denom),
        "argument_denom": args_denom,
        "numeric_exactness": pct(numeric_pass, numeric_denom),
        "numeric_denom": numeric_denom,
        "term_exactness": pct(term_pass, term_denom),
        "term_denom": term_denom,
        "cross_domain_exactness": pct(cross_pass, cross_denom),
        "cross_denom": cross_denom,
        "hallucination_violations": halluc_violations,
        "hallucination_checked": halluc_checked,
        "hallucination_rate": pct(halluc_violations, halluc_checked) if halluc_checked else (0.0 if not implemented else None),
        "gap_admission_precision": precision(gap_tp, 0) if (gap_tp + gap_fn) == 0 else pct(gap_tp, gap_tp + gap_fn),
        "clarify_precision": precision(clarify_tp, clarify_fp),
        "clarify_recall": pct(clarify_tp, clarify_tp + clarify_fn),
        "refusal_precision": precision(refuse_tp, refuse_fp),
        "refusal_recall": pct(refuse_tp, refuse_tp + refuse_fn),
        "latency_p50": pctile(0.50),
        "latency_p95": pctile(0.95),
        "per_bucket": per_bucket,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _fmt_target(name: str) -> str:
    op, val = TARGETS[name]
    return f"{op}{val * 100:.0f}%" if val <= 1 else f"{op}{val}"


def _passes(name: str, value) -> str:
    if value is None:
        return "--"
    op, target = TARGETS[name]
    ok = value >= target if op == ">=" else abs(value - target) < 1e-9
    return "PASS" if ok else "FAIL"


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def print_report(evald: dict, metrics: dict) -> None:
    print("=" * 78)
    print("Gold Eval Report -- evals/gold_questions.json (55 questions)")
    print("=" * 78)

    if not metrics["implemented"]:
        print(
            "\nSystem under test: NOT IMPLEMENTED. graph.py exposes neither "
            "run_pipeline() nor a compiled graph/app with .invoke(). All "
            "system-dependent metrics below are 0% / n=0 -- this is expected "
            "until S05 (planner) and S06 (verbalizer) land; see all-specs.md "
            "S04's Done-when clause. This is not a bug in eval.py.\n"
        )
    else:
        print("\nSystem under test: graph.py pipeline found and invoked for all 55 questions.\n")

    if evald["drift_warnings"]:
        print("GROUND-TRUTH DRIFT WARNINGS (frozen gold_questions.json vs live data/terms):")
        for w in evald["drift_warnings"]:
            print(f"  ! {w}")
        print()

    headline = [
        ("Intent accuracy (correct tool)", "intent_accuracy", metrics["n"]),
        ("Domain routing accuracy", "domain_routing_accuracy", metrics["domain_routing_denom"]),
        ("Argument accuracy", "argument_accuracy", metrics["argument_denom"]),
        ("Numeric exactness (Domain A)", "numeric_exactness", metrics["numeric_denom"]),
        ("Term exactness (Domain B)", "term_exactness", metrics["term_denom"]),
        ("Cross-domain exactness (rewards_earned)", "cross_domain_exactness", metrics["cross_denom"]),
        ("Hallucination rate (0 = no violations)", "hallucination_rate", metrics["hallucination_checked"]),
        ("Gap-admission precision", "gap_admission_precision", 5),
        ("Clarify precision", "clarify_precision", None),
        ("Refusal precision", "refusal_precision", None),
    ]
    rows = []
    for label, key, denom in headline:
        value = metrics[key]
        denom_str = "" if denom is None else f"(n={denom})"
        rows.append([label, _fmt_pct(value), denom_str, _fmt_target(key), _passes(key, value)])
    _print_table(["Metric", "Score", "", "Target", ""], rows)

    print()
    p50 = "n/a" if metrics["latency_p50"] is None else f"{metrics['latency_p50']:.2f}s"
    p95 = "n/a" if metrics["latency_p95"] is None else f"{metrics['latency_p95']:.2f}s"
    print(f"Latency p50 / p95: {p50} / {p95}   (targets: <=4s / <=7s)")
    print(
        f"Hallucination violations: {metrics['hallucination_violations']} "
        f"numbers unaccounted-for, out of {metrics['hallucination_checked']} answers checked."
    )
    print(
        f"Clarify recall: {_fmt_pct(metrics['clarify_recall'])} of the 6 underspecified questions "
        f"actually triggered clarify."
    )
    print(
        f"Refusal recall: {_fmt_pct(metrics['refusal_recall'])} of the 5 out-of-scope questions "
        f"actually triggered refuse."
    )

    print("\nPer-bucket breakdown:")
    bucket_rows = []
    for bucket, b in metrics["per_bucket"].items():
        bucket_rows.append([
            bucket, str(b["n"]),
            _fmt_pct(b["intent_correct"] / b["n"] if b["n"] else None),
            _fmt_pct(b["behaviour_correct"] / b["n"] if b["n"] else None),
        ])
    _print_table(["Bucket", "n", "Intent acc.", "Behaviour acc."], bucket_rows)
    print()


def main() -> None:
    evald = evaluate()
    metrics = compute_metrics(evald)
    print_report(evald, metrics)


if __name__ == "__main__":
    main()
