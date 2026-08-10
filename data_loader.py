"""Canonical transaction loader — S02.

    load_transactions(mapping_path="mapping.yaml") -> pd.DataFrame

This is the entire implementation of the schema-swappability promise:

    real_data.csv --> mapping.yaml --> canonical DataFrame --> tools (unchanged)

`mapping.yaml` is the ONLY place that knows a source CSV's file path or its
real column names. Everything downstream — every tool in `tools_txn.py` (S03)
and `tools_card.py` (S03B) — reads the canonical DataFrame this module
returns and only ever sees the six canonical field names below. If a tool
needs a new field, that field has to be added to the canonical contract
here, not read directly off the source CSV.

Canonical schema produced by `load_transactions()`:
    txn_id     str            e.g. "TXN000001"
    timestamp  datetime64[ns]
    amount     float          positive = spend, negative = refund
    merchant   str
    category   str
    card_id    str

Any other columns present in the source CSV (e.g. this repo's synthetic data
also carries `txn_type`, `city`, `currency`) pass through unchanged, under
their original names. They are NOT part of the swap contract — a differently
shaped source is not required to have them, and no S03/S03B tool may depend
on them being present. Only the six fields above are guaranteed.

See all-specs.md S02, PRD.md §7.4, and .claude/agents/data-loader.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

# The six canonical fields every mapping.yaml must declare under `fields:`.
# Load-bearing for every later spec — do not rename these.
REQUIRED_FIELDS: list[str] = [
    "txn_id",
    "timestamp",
    "amount",
    "merchant",
    "category",
    "card_id",
]


class MappingError(ValueError):
    """Raised when mapping.yaml (or the CSV it points at) can't produce the
    canonical schema.

    The message always names both the canonical field that's missing/broken
    and the exact `mapping.yaml` key that would fix it. This error message
    *is* the swap-guide UX per S02 — a generic "column not found" is not
    acceptable here.
    """


# --------------------------------------------------------------------------
# mapping.yaml parsing
# --------------------------------------------------------------------------

def _read_mapping_config(mapping_path: str) -> tuple[dict[str, Any], Path]:
    """Parse mapping.yaml and return (config dict, resolved source CSV path).

    The source path is resolved relative to mapping.yaml's own location, not
    the process's current working directory, so `load_transactions()` behaves
    identically whether invoked from the repo root, a test runner, or a
    Streamlit Cloud deployment that may cwd somewhere else.
    """
    mapping_file = Path(mapping_path)
    if not mapping_file.exists():
        raise MappingError(
            f"mapping.yaml not found at '{mapping_path}'. The loader needs a "
            f"mapping file with a top-level 'source:' path and a 'fields:' "
            f"block mapping each of {REQUIRED_FIELDS} to a column name in "
            f"your CSV. See PRD.md §7.4 for an example."
        )

    with mapping_file.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    if "source" not in config or not config["source"]:
        raise MappingError(
            f"'{mapping_path}' is missing a top-level 'source:' key naming "
            f"the CSV to load, e.g. 'source: data/transactions.csv'."
        )
    if "fields" not in config or not isinstance(config["fields"], dict):
        raise MappingError(
            f"'{mapping_path}' is missing a 'fields:' block. Add a 'fields:' "
            f"mapping with one entry per canonical field: {REQUIRED_FIELDS}."
        )

    source_path = Path(str(config["source"]))
    if not source_path.is_absolute():
        source_path = mapping_file.resolve().parent / source_path

    return config, source_path


# --------------------------------------------------------------------------
# validation + rename
# --------------------------------------------------------------------------

def _validate_and_rename(
    df: pd.DataFrame,
    fields: dict[str, Any],
    mapping_path: str,
    source_path: Path,
) -> pd.DataFrame:
    """Rename `df`'s columns to canonical names per `fields`, after checking
    every required canonical field is both declared in mapping.yaml and
    actually present as a column in the loaded CSV.

    Raises `MappingError` naming exactly what's wrong and which
    `mapping.yaml` key fixes it — collecting every problem found rather than
    stopping at the first, so a stranger swapping in real data sees the
    whole punch list in one run.
    """
    problems: list[str] = []

    # 1. every canonical field must have a non-empty entry under fields:
    missing_declarations = [
        c for c in REQUIRED_FIELDS if c not in fields or not fields[c]
    ]
    for canonical in missing_declarations:
        problems.append(
            f"  - canonical field '{canonical}' has no entry under 'fields:' "
            f"in '{mapping_path}'. Add e.g. '{canonical}: <column_name_in_your_csv>'."
        )

    # 2. every declared raw column name must actually exist in the CSV
    declared = {
        canonical: fields[canonical]
        for canonical in REQUIRED_FIELDS
        if canonical not in missing_declarations
    }
    available = list(df.columns)
    missing_columns = {
        canonical: raw for canonical, raw in declared.items() if raw not in available
    }
    for canonical, raw in missing_columns.items():
        problems.append(
            f"  - mapping.yaml maps canonical field '{canonical}' to column "
            f"'{raw}', but '{raw}' was not found in {source_path}. "
            f"Available columns: {available}. Fix the '{canonical}:' entry "
            f"under 'fields:' in '{mapping_path}'."
        )

    if problems:
        raise MappingError(
            f"load_transactions() cannot build the canonical schema from "
            f"'{mapping_path}':\n" + "\n".join(problems)
        )

    ok_fields = {
        canonical: raw for canonical, raw in declared.items() if canonical not in missing_columns
    }
    rename_map = {raw: canonical for canonical, raw in ok_fields.items()}
    renamed = df.rename(columns=rename_map)

    # canonical fields first (stable, predictable order), any pass-through
    # extras after, in their original order.
    passthrough = [c for c in renamed.columns if c not in REQUIRED_FIELDS]
    return renamed[REQUIRED_FIELDS + passthrough]


# --------------------------------------------------------------------------
# type coercion
# --------------------------------------------------------------------------

def _coerce_timestamp(series: pd.Series, mapping_path: str) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="raise")
    except (ValueError, TypeError) as exc:
        raise MappingError(
            "the column mapped to canonical field 'timestamp' could not be "
            f"parsed as a datetime ({exc}). Check the 'timestamp:' entry in "
            f"'{mapping_path}' points at a column of parseable dates."
        ) from exc


def _coerce_amount(series: pd.Series, mapping_path: str) -> pd.Series:
    cleaned = series
    if not pd.api.types.is_numeric_dtype(cleaned):
        # Forgiving of common real-world bank-export formatting: thousands
        # separators and a currency symbol prefix ("₹1,234.50" -> "1234.50").
        # Deliberately checked via is_numeric_dtype rather than `dtype ==
        # object`: pandas >=3.0 infers CSV text columns as its new "str"
        # extension dtype by default, not the legacy "object" dtype, so an
        # `== object` check silently never fires and this cleanup is skipped.
        cleaned = cleaned.astype(str).str.replace(r"[₹$,]", "", regex=True).str.strip()
    try:
        return pd.to_numeric(cleaned, errors="raise").astype(float)
    except (ValueError, TypeError) as exc:
        raise MappingError(
            "the column mapped to canonical field 'amount' could not be "
            f"coerced to float ({exc}). Check the 'amount:' entry in "
            f"'{mapping_path}' points at a numeric column."
        ) from exc


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------

def _load_transactions_impl(mapping_path: str) -> pd.DataFrame:
    config, source_path = _read_mapping_config(mapping_path)
    fields = config["fields"]

    if not source_path.exists():
        raise MappingError(
            f"'{mapping_path}' points 'source:' at '{source_path}', but that "
            f"file does not exist. Fix the 'source:' path in '{mapping_path}'."
        )

    raw_df = pd.read_csv(source_path)
    df = _validate_and_rename(raw_df, fields, mapping_path, source_path)

    df["timestamp"] = _coerce_timestamp(df["timestamp"], mapping_path)
    df["amount"] = _coerce_amount(df["amount"], mapping_path)
    for col in ("txn_id", "merchant", "category", "card_id"):
        df[col] = df[col].astype(str).str.strip()

    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return df


@st.cache_data
def load_transactions(mapping_path: str = "mapping.yaml") -> pd.DataFrame:
    """Returns a canonical DataFrame regardless of source column names.

    Reads `mapping_path` for the source CSV path and the field mapping,
    loads the CSV, renames its columns to the six canonical names
    (`txn_id, timestamp, amount, merchant, category, card_id`), coerces
    `timestamp` to datetime and `amount` to float, and validates all six
    canonical fields are present — raising `MappingError` naming both the
    missing canonical field and the `mapping.yaml` key that would fix it if
    not.

    Cached with `st.cache_data` so it loads once per Streamlit session; call
    `load_transactions.clear()` to force a reload (e.g. after editing
    `mapping.yaml` mid-session).
    """
    return _load_transactions_impl(mapping_path)
