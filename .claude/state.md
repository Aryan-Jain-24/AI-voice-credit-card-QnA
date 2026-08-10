# Project State

_Last updated: 2026-08-10T19:11:19Z by state-tracker_

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | All deliverables from the S00 tree exist: `app.py`, `graph.py`, `tools_txn.py`, `tools_card.py`, `voice.py`, `data_loader.py`, `eval.py`, `card_terms.yaml`, `mapping.yaml`, `generate_data.py` (real, see S01), `data/`, `evals/gold_questions.json`, `requirements.txt`, `.env.example`, `.gitignore`, `README.md`. `app.py` still only implements the "hello" + key-check gate (unchanged). Repo still has zero commits (`git log` reports "your current branch 'master' does not have any commits yet"; `git status` shows every project file untracked) — a git-hygiene gap, not a skeleton gap. |
| S01 | `generate_data.py`, `data/transactions.csv` | done | Not re-run this pass (no reason to believe it changed; out of scope for this snapshot which is S02-focused). Spot-checked instead: `generate_data.py` is still 787 lines with 36 `assert` statements; `data/transactions.csv` is still 2,015 lines (1 header + 2,014 data rows), header still the canonical 9-column shape (`txn_id,timestamp,amount,merchant,category,card_id,txn_type,city,currency`). Matches the fully-verified state from the prior snapshot (which did re-run the generator and confirmed "All realism assertions passed"). |
| S02 | `data_loader.py`, `mapping.yaml` | done | Verified this pass, not taken on faith. `data_loader.py` is now 251 lines with a real `load_transactions()`: parses `mapping.yaml` (source path resolved relative to the mapping file, not cwd), validates all 6 `REQUIRED_FIELDS` are declared and present as real CSV columns (collects *every* problem before raising, not just the first), renames to canonical schema, coerces `timestamp` via `pd.to_datetime` and `amount` via `pd.to_numeric` (with a currency/comma-stripping fallback for non-numeric columns), raises `MappingError` naming both the canonical field and the `mapping.yaml` key to fix, and is wrapped in `@st.cache_data`. `mapping.yaml` (37 lines) is fully documented and points `source: data/transactions.csv` at the real 6 canonical fields (currently identity-mapped since S01's CSV already uses canonical names). New `test_data_loader.py` (147 lines, 5 tests) actually run this pass via `venv/Scripts/python.exe -m pytest test_data_loader.py -v`: **all 5 passed** — canonical schema/dtype checks against the real CSV, both `MappingError` message-content paths (missing declaration; declared-but-absent column), currency-string amount coercion, and — critically — `test_schema_swap_promise_identical_canonical_output`, which renames every column in the real CSV to nonsense (`zz_ref_code`, `qux_moment`, etc.), points a fresh `mapping.yaml` at the new names, and asserts the resulting canonical frame is `pd.testing.assert_frame_equal`-identical to loading the real unmodified CSV. This *is* the literal S02 done-when test (all-specs.md: "rename every column in the CSV to nonsense, edit only `mapping.yaml`... this is the proof"), automated and passing. S02 done-when is met. |
| S03 | `tools_txn.py` (6 tools) | not started | Still 7-line docstring-only — no `resolve_period`, no tool implementations, no `@tool` decorators. **Now unblocked**: S02's canonical DataFrame loader is real and passing, so the six transaction tools have a real contract to build against. |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | not started | `card_terms.yaml` (29 lines) is still an empty-value skeleton (`name: "TODO"`, empty fee/reward dicts, no clauses, no dining cap authored). `tools_card.py` is still 6-line docstring-only. Was already unblocked on S01's category list; S02 landing doesn't add a new dependency for S03B (it only needs `data_loader` transitively for `rewards_earned`'s spend lookups, which now also has a real implementation to build against). Not yet picked up. |
| S04 | `evals/gold_questions.json`, `eval.py` | not started | `gold_questions.json` is still `[]` (0 of 55 entries). `eval.py` is still 8-line docstring-only — no scoring logic. Blocked on S03/S03B for real tool surfaces to write gold questions against. |
| S05 | `graph.py` planner node + assembly | not started | `graph.py` (4 lines) is still docstring-only — no `StateGraph`, no nodes. Blocked on S03/S03B/S04. |
| S06 | verbalizer node | not started | Same file (`graph.py`) as S05, same status — no verbalizer logic present. |
| S07 | `voice.py`, fuzzy merchant correction | not started | `voice.py` (7 lines) is still docstring-only — no `transcribe`/`synthesize`, no rapidfuzz usage. Per the hard rule, must not start until S05+S06 pass their text-input gate. |
| S08 | `app.py`, Streamlit deploy | not started | `app.py` (20 lines) still only implements the S00 "hello" + key-check gate, not the real UI. No deploy yet. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | not started | No `EVAL_REPORT.md` exists. `README.md` (28 lines) still explicitly self-describes as the S00-stage placeholder pointing to PRD/all-specs/CLAUDE.md as source of truth. |

## Hard gates (from PRD §8)

Not yet measurable — `eval.py` is a docstring-only stub with no scoring logic, and `evals/gold_questions.json` is an empty array (S04 not started). Nothing to run yet.

| Metric | Target | Current | Notes |
|---|---|---|---|
| Numeric exactness (Domain A) | ≥95% | — | not yet measurable |
| Term exactness (Domain B) | 100% | — | not yet measurable |
| Hallucinated facts | 0 | — | not yet measurable |
| No-invention on missing terms | 100% | — | not yet measurable |
| Clarify on underspecified | 100% | — | not yet measurable |
| Out-of-scope refusal | 100% | — | not yet measurable |

## Recent activity

- S02 is now done. `data_loader.py` went from a 9-line docstring stub to a
  251-line mapping-driven canonical loader (`load_transactions`, `MappingError`,
  full validation/coercion pipeline, `@st.cache_data`); `mapping.yaml` went
  from a 16-line skeleton to a 37-line fully-documented mapping pointing at
  the real `data/transactions.csv`. New `test_data_loader.py` (147 lines, 5
  tests) added.
- Verified this pass by actually running the test suite
  (`venv/Scripts/python.exe -m pytest test_data_loader.py -v`), not just
  trusting the handoff note: **5/5 passed**, including the automated version
  of the exact S02 done-when check — rename every CSV column to nonsense,
  point a fresh `mapping.yaml` at the new names, confirm the canonical
  DataFrame is identical to loading the real, unmodified data.
- S03 and S03B are now unblocked (S03 directly, on S02; S03B was already
  unblocked on S01 and gains a real `data_loader` to build `rewards_earned`
  against). Neither has been picked up yet — both remain docstring-only
  stubs, confirmed by re-reading `tools_txn.py`, `tools_card.py`, and
  `card_terms.yaml` this pass.
- S01 unchanged since last snapshot (spot-checked, not re-run — see S01 row).
  S04 through S09 unchanged since last snapshot (docstring-only stubs /
  empty scaffolding), confirmed by re-reading each this pass.
- Repo still has zero commits; `git status` still shows every project file as
  untracked (`.claude/`, `.env.example`, `.gitignore`, `CLAUDE.md`, `PRD.md`,
  `README.md`, `all-specs.md`, `app.py`, `card_terms.yaml`, `data/`,
  `data_loader.py`, `eval.py`, `evals/`, `generate_data.py`, `graph.py`,
  `mapping.yaml`, `requirements.txt`, `test_data_loader.py`, `tools_card.py`,
  `tools_txn.py`, `voice.py`).

## Open items / blockers

- **S03 and S03B are now the critical path** (both unblocked). S03
  (`tools_txn.py`: `resolve_period` + the 6 transaction tools) and S03B
  (`card_terms.yaml` real content + `tools_card.py`'s 4 tools) can proceed in
  parallel per the build-order diagram — S03B only needed S01's category
  list, which has been available since the last snapshot.
- **Dining reward-cap placeholder still needs reconciling against S03B's real
  authored value** (carried over, unresolved). `card_terms.yaml` still has no
  authored dining cap (empty `rewards` block), so `generate_data.py` used the
  PRD §7.3 worked example (5 pts/₹100 dining, capped at 2,000 pts/month →
  ₹40,000/month breach threshold) as a placeholder, exposed as the named
  constant `REFERENCE_DINING_CAP_SPEND` in `generate_data.py`. When S03B
  lands: confirm the real authored dining cap still makes the generated
  breach months (Oct 2025 at ₹54,504 and Nov 2025 at ₹47,027 dining spend)
  actually breach, and that at least one other month remains a clean
  non-breach month. If S03B's real cap differs substantially from ₹40k, the
  generated data's breach/non-breach months may need regenerating.
- **No commits yet.** The entire repo (S00 skeleton + S01 + S02 real
  deliverables + planning docs) is untracked. Not a spec blocker per se, but
  worth flagging since nothing is currently recoverable via git history if
  working-tree files are lost — this is now three specs' worth of real,
  uncommitted work.
- No other blockers observed — S04 through S09 are cleanly "not started" with
  no evidence of partial/broken work to clean up.
