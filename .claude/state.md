# Project State

_Last updated: 2026-08-10T19:46:36Z by state-tracker_

Note: the previous run of this agent in this session failed mid-way (connection
error) before writing this file, so the version of `state.md` this replaces was
stale (it still showed S02 done / S03 & S03B not started). This snapshot is a
full from-scratch re-inspection — nothing carried over from that failed run.

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | All S00-tree files exist and the repo is committed (`75e5756` → `94e3a74` → `04d6137`). One regression since the last commit: `.env.example` is **deleted in the working tree, unstaged** (`git status` shows `deleted: .env.example`) — it still exists in `HEAD`/git history, so it's recoverable with `git checkout -- .env.example`, but as of right now the file is missing from disk even though `README.md` and `app.py`'s warning message both still reference it. Flagged under Open items. |
| S01 | `generate_data.py`, `data/transactions.csv` | done | Verified this pass by calling `build_dataset()` + `run_assertions(df)` directly (no file write) — all realism assertions pass: 2,014 rows, includes the dining reward-cap breach (≥2 months over threshold, ≥1 under), ≥8 `cash_advance` rows, ≥8 `fees_interest` rows, spike month, etc. `data/transactions.csv` on disk independently confirmed at 2,014 rows with the canonical 9-column header, matching the in-memory rebuild exactly (deterministic/seeded generator, unchanged since commit `94e3a74`). |
| S02 | `data_loader.py`, `mapping.yaml` | done | `data_loader.py` (252 lines) is a real mapping-driven `load_transactions()`: resolves `source:` relative to `mapping.yaml`'s own location, validates all 6 `REQUIRED_FIELDS` are declared *and* present (collects every problem before raising `MappingError`, naming both the canonical field and the `mapping.yaml` key to fix), coerces `timestamp`/`amount`, wrapped in `@st.cache_data`. `mapping.yaml` is fully documented and identity-maps the 6 canonical fields onto `data/transactions.csv`. `test_data_loader.py` (5 tests, all passing per this run's full suite) includes the literal schema-swap proof from the spec's done-when (rename every column to nonsense, point a fresh mapping at it, assert identical canonical output). |
| S03 | `tools_txn.py` (6 tools) | done | Verified by reading the full file (690 lines, real implementation, not a stub) and running the test suite. Contains `resolve_period` (Python-only date resolution, LLM never computes dates) plus all six tools (`spend_total`, `spend_by_category`, `top_merchants`, `compare_periods`, `find_transactions`, `recurring_charges`), each a thin `@tool`-decorated wrapper around a private, directly-testable `_..._core` function. `tests/test_tools_txn.py` collected **39 tests**, all passing. Every tool returns a flat dict of scalars with `period_label` where applicable, matches the S03 tool-table shapes. |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | `card_terms.yaml` (194 lines) is fully authored — real fees (annual, joining, forex markup, tiered late payment, cash advance fee + finance charge, over-limit, EMI processing/foreclosure, card replacement, cheque bounce, reward redemption), reward schedule (base rate + 6 category overrides with caps, exclusions, redemption, milestone bonus), 7 merchant offers — every leaf carries a `clause` string, and 3 deliberate gaps (`railway_surcharge`, `wallet_load_fee`, `balance_transfer_fee`) are genuinely absent for gap-admission testing. `tools_card.py` (693 lines) implements all 4 tools (`card_rewards`, `card_fees`, `card_offers`, `rewards_earned`), plus its own independently-tested `resolve_period` (intentionally not importing S03's, since the two were built in parallel — a documented, low-risk consolidation is left for S05). `rewards_earned` groups by (category, calendar month) so caps apply per-month not per-query-period, nets refunds off before flooring at 0, excludes `cash_advance`/`fees_interest`, and returns `capped_categories`. Missing `fee_type` returns `{"found": false, ...}`, verified by tests. `test_tools_card.py` collected **63 tests**, all passing. |
| S04 | `evals/gold_questions.json`, `eval.py` | not started | `evals/gold_questions.json` is still `[]` (0 of 55 entries). `eval.py` is still an 8-line docstring-only stub with no scoring logic. **Now the next unblocked spec** — S01/S02/S03/S03B (its only dependencies per the build-order diagram) are all done, so the 55-question gold set can be written against real tool signatures. |
| S05 | `graph.py` planner node + assembly | not started | `graph.py` (5 lines) is still docstring-only — no `StateGraph`, no nodes, no planner prompt. Blocked on S04 (build gold questions before the planner exists, so questions don't bend toward what the model already handles). |
| S06 | verbalizer node | not started | Same file (`graph.py`) as S05, same status — no verbalizer logic present. |
| S07 | `voice.py`, fuzzy merchant correction | not started | `voice.py` (8 lines) is still docstring-only — no `transcribe`/`synthesize`, no `rapidfuzz` usage. Per the hard rule, must not start until S05+S06 pass their text-input eval gate. |
| S08 | `app.py`, Streamlit deploy | not started | `app.py` (21 lines) still only implements the S00 "hello" + `OPENAI_API_KEY`-loaded check, not the real UI. No deploy yet. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | not started | No `EVAL_REPORT.md` exists. `README.md` (29 lines) still explicitly self-describes as the S00-stage placeholder pointing to `PRD.md`/`all-specs.md`/`CLAUDE.md` as source of truth. |

## Hard gates (from PRD §8)

Not yet measurable — `eval.py` is a docstring-only stub with no scoring logic, and
`evals/gold_questions.json` is an empty array (S04 not started). Nothing to run yet.

| Metric | Target | Current | Notes |
|---|---|---|---|
| Numeric exactness (Domain A) | ≥95% | — | not yet measurable |
| Term exactness (Domain B) | 100% | — | not yet measurable |
| Hallucinated facts | 0 | — | not yet measurable |
| No-invention on missing terms | 100% | — | not yet measurable |
| Clarify on underspecified | 100% | — | not yet measurable |
| Out-of-scope refusal | 100% | — | not yet measurable |

## Recent activity

- S03 and S03B both landed in this session, built in parallel by dedicated
  builder subagents, and both independently verified this pass:
  - S03: `tools_txn.py` went from a 7-line docstring stub to a 690-line real
    implementation (`resolve_period` + 6 tools). `tests/test_tools_txn.py`
    added (39 tests).
  - S03B: `card_terms.yaml` went from a 29-line TODO skeleton to a 194-line
    fully-authored terms file; `tools_card.py` went from a 6-line docstring
    stub to a 693-line implementation of the 4 card/rewards tools.
    `test_tools_card.py` added (63 tests).
- Ran the full suite this pass (`python -m pytest -q` from `venv`):
  **107 passed** (5 in `test_data_loader.py`, 63 in `test_tools_card.py`, 39
  in `tests/test_tools_txn.py`). Matches the "107 passed" figure reported by
  the builder subagents — independently reproduced, not taken on faith.
- **Dining reward-cap placeholder issue (carried over from the prior
  snapshot) is now reconciled.** `generate_data.py`'s
  `REFERENCE_DINING_CAP_SPEND` placeholder (5 pts/₹100, 2,000-pt monthly cap
  → ₹40,000/month breach threshold, from the PRD §7.3 worked example) matches
  S03B's real authored `card_terms.yaml` dining terms exactly
  (`rewards.category_rates.food_dining`: `points_per_100: 5`,
  `monthly_cap_points: 2000`) — confirmed by reading both files and by
  `card_terms.yaml`'s own header comment, which explicitly documents the
  match. No regeneration of `data/transactions.csv` is needed.
- None of the S03/S03B work is committed yet. `git status` shows
  `card_terms.yaml`, `tools_card.py`, `tools_txn.py` as modified (tracked),
  and `test_tools_card.py` + `tests/` (containing `test_tools_txn.py`) as
  untracked. A new `.claude/agents/git-syncer.md` subagent definition was
  also added (untracked) — its job is to run tests and commit/push once a
  spec's deliverable lands cleanly, which fits this exact situation.
- `.env.example` is deleted in the working tree (unstaged) — not something
  any spec's done-when depends on directly, but a live discrepancy against
  the committed S00 skeleton. See Open items.

## Open items / blockers

- **Nothing from S03/S03B is committed to git yet.** Working tree has real,
  passing, uncommitted work (`card_terms.yaml`, `tools_card.py`,
  `tools_txn.py` modified; `test_tools_card.py`, `tests/test_tools_txn.py`
  untracked). This is exactly what `git-syncer` exists to pick up next —
  tests are green (107/107), so there's no reason to hold off on
  committing/pushing.
- **`.env.example` needs restoring.** `git status` shows it deleted, unstaged,
  from the working tree, even though it's still present in `HEAD` and is
  referenced by both `README.md`'s quickstart and `app.py`'s
  key-not-loaded warning. Likely accidental (not attributable to either the
  S03 or S03B builder subagent's stated scope). Simplest fix is
  `git checkout -- .env.example` before the next commit — flagging here
  rather than fixing it myself, per this agent's scope.
- **Minor structural inconsistency, not a blocker:** test files are split
  between the repo root (`test_data_loader.py`, `test_tools_card.py`) and a
  `tests/` subdirectory (`test_tools_txn.py`). `pytest -q` collects and runs
  all of them correctly either way, so this doesn't block anything, but
  whoever picks up S04/S09 may want to consolidate the layout for the
  README's "run tests" step to read cleanly.
- **S04 is the next unblocked spec.** All of its stated dependencies (S01
  synthetic data, S02 loader, S03 six transaction tools, S03B four card/
  rewards tools) are now done and verified. The 55-question gold set and
  `eval.py` harness can be built against the real tool signatures now in
  place — per the spec, this should happen *before* S05's planner exists.
