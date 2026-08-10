"""Tests for the S02 mapping-driven canonical loader (data_loader.py).

Covers:
- the canonical schema/dtypes produced from the real data/transactions.csv
- the two MappingError paths (field undeclared in mapping.yaml; field
  declared but pointing at a column the CSV doesn't have) name both the
  canonical field and the mapping.yaml key that fixes it
- amount coercion is forgiving of comma/currency-symbol formatting
- the actual schema-swap promise: rename every CSV column to nonsense, point
  a mapping.yaml at the new names, and get back an identical canonical
  DataFrame — this is the automated version of the manual proof required by
  all-specs.md S02's "done when".

Each test builds its own temp CSV + mapping.yaml (via pytest's `tmp_path`)
with a distinct path per test, so `st.cache_data`'s argument-based cache key
(on `mapping_path`) never collides between tests.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from data_loader import REQUIRED_FIELDS, MappingError, load_transactions

# Absolute path: `source:` in a mapping.yaml resolves relative to that
# mapping file's own directory (see data_loader._read_mapping_config), so a
# mapping.yaml written into pytest's tmp_path needs an absolute source path
# to reach the real repo-root CSV.
REAL_CSV = str((Path(__file__).parent / "data" / "transactions.csv").resolve())


def _write_mapping(path, source, fields):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"source": str(source), "fields": fields}, f)


def test_loads_real_data_with_canonical_schema():
    df = load_transactions("mapping.yaml")

    assert list(df.columns[:6]) == REQUIRED_FIELDS
    assert len(df) >= 1800
    assert str(df["timestamp"].dtype).startswith("datetime64")
    assert df["amount"].dtype == "float64"
    for col in ("txn_id", "merchant", "category", "card_id"):
        assert df[col].map(type).eq(str).all()
    assert df["txn_id"].is_unique
    assert df["card_id"].nunique() == 1


def test_missing_field_declaration_names_field_and_key(tmp_path):
    mapping_path = tmp_path / "mapping.yaml"
    fields = {c: c for c in REQUIRED_FIELDS if c != "card_id"}  # card_id omitted
    _write_mapping(mapping_path, REAL_CSV, fields)

    with pytest.raises(MappingError) as exc_info:
        load_transactions(str(mapping_path))

    message = str(exc_info.value)
    assert "card_id" in message
    assert "fields:" in message
    assert str(mapping_path) in message


def test_field_pointing_at_missing_column_names_both(tmp_path):
    mapping_path = tmp_path / "mapping.yaml"
    fields = {c: c for c in REQUIRED_FIELDS}
    fields["merchant"] = "does_not_exist_column"
    _write_mapping(mapping_path, REAL_CSV, fields)

    with pytest.raises(MappingError) as exc_info:
        load_transactions(str(mapping_path))

    message = str(exc_info.value)
    assert "merchant" in message
    assert "does_not_exist_column" in message
    assert str(mapping_path) in message


def test_amount_coercion_handles_currency_formatting(tmp_path):
    csv_path = tmp_path / "messy.csv"
    pd.DataFrame(
        {
            "txn_id": ["T1", "T2"],
            "timestamp": ["2026-01-01T10:00:00", "2026-01-02T11:00:00"],
            "amount": ["₹1,234.50", "2,000"],
            "merchant": ["Swiggy", "Amazon"],
            "category": ["food_dining", "shopping"],
            "card_id": ["XXXX0001", "XXXX0001"],
        }
    ).to_csv(csv_path, index=False)

    mapping_path = tmp_path / "mapping.yaml"
    _write_mapping(mapping_path, csv_path, {c: c for c in REQUIRED_FIELDS})

    df = load_transactions(str(mapping_path))

    assert df["amount"].tolist() == [1234.50, 2000.0]
    assert df["amount"].dtype == "float64"


def test_schema_swap_promise_identical_canonical_output(tmp_path):
    """The literal S02 done-when test, automated: rename every column in the
    source CSV to nonsense, point a mapping.yaml at the new names, and
    confirm the canonical DataFrame produced is byte-identical to loading
    the real, unmodified data through the real mapping.yaml.
    """
    baseline = load_transactions("mapping.yaml")

    raw = pd.read_csv(REAL_CSV, dtype=str, keep_default_na=False)
    nonsense_map = {
        "txn_id": "zz_ref_code",
        "timestamp": "qux_moment",
        "amount": "blah_val",
        "merchant": "nonsense_who",
        "category": "gribble_bucket",
        "card_id": "plonk_plastic",
        "txn_type": "flarp_kind",
        "city": "wobble_place",
        "currency": "zorp_money",
    }
    nonsense_csv = tmp_path / "nonsense_transactions.csv"
    raw.rename(columns=nonsense_map).to_csv(nonsense_csv, index=False)

    mapping_path = tmp_path / "swapped_mapping.yaml"
    _write_mapping(
        mapping_path,
        nonsense_csv,
        {
            "txn_id": "zz_ref_code",
            "timestamp": "qux_moment",
            "amount": "blah_val",
            "merchant": "nonsense_who",
            "category": "gribble_bucket",
            "card_id": "plonk_plastic",
        },
    )

    swapped = load_transactions(str(mapping_path))

    pd.testing.assert_frame_equal(
        baseline[REQUIRED_FIELDS].reset_index(drop=True),
        swapped[REQUIRED_FIELDS].reset_index(drop=True),
    )
