# Project State

_Last updated: 2026-08-11T20:45:18+05:30 by state-tracker (full from-scratch inspection; prior file contents were not trusted)_

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | All S00 files present: `app.py`, `graph.py`, `tools_txn.py`, `tools_card.py`, `voice.py`, `data_loader.py`, `mapping.yaml`, `card_terms.yaml`, `generate_data.py`, `eval.py`, `data/`, `evals/`, `requirements.txt`, `README.md`. `app.py` is still exactly the S00 stub (`st.title` + `st.write("hello")` + env-key check). `.env` exists locally, is git-ignored, has `OPENAI_API_KEY` set. **`.env.example` is still deleted in the working tree, uncommitted** — see Open items (unchanged from last pass).|
| S01 | `generate_data.py`, `data/transactions.csv` | done | `data/transactions.csv` has 2,014 data rows (2,015 lines incl. header), correct canonical columns, no changes since last verified pass. |
| S02 | `data_loader.py`, `mapping.yaml` | done | `data_loader.py` (251 lines) and `mapping.yaml` (37 lines) unchanged since last pass. |
| S03 | `tools_txn.py` (6 tools) | done | `tools_txn.py` (689 lines), all six tools present, unchanged since last pass. |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | `card_terms.yaml` (193 lines), `tools_card.py` (692 lines), all four tools present, unchanged since last pass. |
| S04 | `evals/gold_questions.json`, `eval.py` | **done** | Verified directly, not just claimed. `evals/gold_questions.json`: valid JSON, **55 entries, 55 unique ids**, bucket counts — `domain_a_straightforward` 8, `domain_a_phrasing` 8, `domain_a_multi_constraint` 4, `domain_b_terms` 10, `cross_domain_rewards_earned` 5, `domain_routing_trap` 4, `missing_terms_gap` 5, `underspecified_clarify` 6, `out_of_scope_refuse` 5 (sums to 55, 9 buckets as claimed). Each sampled entry carries `expected_domain`/`expected_tool`/`expected_args`/`expected_behaviour`/`expected_value`/`ground_truth_spec`. `eval.py` (941 lines, parses clean via `ast.parse`) implements independent ground truth computed directly from `data/transactions.csv` (pandas) and `card_terms.yaml` (yaml) — does **not** import `tools_txn.py`/`tools_card.py`, per its own stated policy (confirmed by reading the module, no such imports present). Contains `check_drift()`, wired into `evaluate()` (line 624), plus separate `_gt_*` functions per tool including `_rewards_earned_calc`/`_gt_rewards_earned` for the cross-domain case, `_extract_tool_call`, `_classify_behaviour`, `_args_match`, `_is_gap_admission_text`, `compute_metrics`, `_print_table`, `print_report`. **Ran `python eval.py` this pass** (exit code 0, no drift warnings printed — the 55 frozen `expected_value` snapshots match live-recomputed ground truth against the current CSV/YAML, i.e. no drift). Output: intent accuracy 0.0% (n=55), domain routing 0.0% (n=44), argument accuracy 0.0% (n=44), numeric exactness 0.0% (n=22), term exactness 0.0% (n=10), cross-domain exactness 0.0% (n=5), hallucination rate 0.0% PASS (n=0, vacuously true — no answers to check yet), gap-admission precision 0.0% (n=5), clarify precision 100% PASS (n=0 false positives), refusal precision 100% PASS (n=0 false positives), latency n/a. Report explicitly states: *"System under test: NOT IMPLEMENTED. graph.py exposes neither run_pipeline() nor a compiled graph/app with .invoke()."* **This is the correct, expected state per S04's done-when gate** (eval harness must exist and run cleanly before the planner does) — it is not a failure of S04, and not evidence of a bug in `eval.py`. `.claude/agents/eval-harness-builder.md`'s claims (55 questions/9 buckets, full metric suite, drift detector) are confirmed accurate by direct inspection and execution, not just by report. |
| S05 | `graph.py` planner node + assembly | not started | `graph.py` still the verbatim S00 stub (4-line docstring only, confirmed by reading it this pass). Next unblocked spec now that S04 is done. |
| S06 | verbalizer node | not started | Same file as S05; no verbalizer code exists. |
| S07 | `voice.py`, fuzzy merchant correction | not started | `voice.py` still the verbatim S00 stub (docstring only, confirmed by reading it this pass). Per CLAUDE.md's hard rule, must not start until S05+S06 pass their text-input eval gate. |
| S08 | `app.py`, Streamlit deploy | not started (beyond S00 skeleton) | `app.py` unchanged — still the S00 "hello" placeholder, confirmed by reading it this pass. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | not started | No `EVAL_REPORT.md` anywhere in the repo. `README.md` still references the (currently broken, see below) `.env.example` quickstart step. No Loom outline found. |

## Hard gates (from PRD §8)

`eval.py` now runs end-to-end and is measuring correctly, but every system-dependent
metric is 0%/FAIL because `graph.py` has no planner/verbalizer yet — this is the
expected pre-S05/S06 state, not a regression.

| Metric | Target | Current | Notes |
|---|---|---|---|
| Numeric exactness (Domain A) | >=95% | 0.0% (n=22) | FAIL — expected until S05/S06 land; harness itself is verified working |
| Term exactness (Domain B) | ==100% | 0.0% (n=10) | FAIL — same reason |
| Hallucinated facts | ==0 | 0.0% (n=0) | PASS — vacuous, no answers produced yet to hallucinate in |
| No-invention on missing terms (gap-admission) | 100% | 0.0% (n=5) | FAIL — same reason |
| Clarify on underspecified | 100% | 100.0% (n=0 triggered / 6 questions, precision only) | PASS on precision (no false clarifies); recall is 0% since there's no planner to trigger it |
| Out-of-scope refusal | 100% | 100.0% (n=0 triggered / 5 questions, precision only) | PASS on precision; recall 0% for the same reason |

## Recent activity

From `git log --oneline -20` (5 commits total on `main`, matches `origin/main` — **no new
commits since last state-tracker pass**; S04's deliverables are complete on disk but
**uncommitted**):

- `457d983` Add orchestrator and git-syncer subagent definitions (coordination subagents only, no product code)
- `09c7f2a` S03/S03B: transaction tools + card terms/rewards tools
- `04d6137` Merge initial LICENSE commit from GitHub
- `94e3a74` S00-S02: repo skeleton, synthetic transaction data, schema-swappable loader
- `75e5756` Initial commit

Working tree vs. `origin/main` (`git status --porcelain`):
- `M .claude/state.md` (this refresh)
- `D .env.example` (stray, pre-existing, still unresolved — see Open items)
- `M eval.py` (+943/-... — S04 harness landed, was previously a 9-line stub)
- `M evals/gold_questions.json` (+937/-... — was previously `[]`, now 55 entries)

S04's deliverables (`eval.py`, `evals/gold_questions.json`) are real, verified working,
and sitting in the working tree uncommitted. **This is now a git-syncer job**: run the
test/eval gate (both pass/run cleanly as documented above) and commit+push S04, per the
orchestrator's normal one-spec-at-a-time cadence.

## Open items / blockers

- **Uncommitted deletion of `.env.example`** — still present, unchanged from last pass.
  `git status` shows `deleted: .env.example`, not staged, not committed. `git show
  HEAD:.env.example` still returns its content (`OPENAI_API_KEY=sk-...` template).
  `README.md` line 21 still instructs `copy .env.example .env`, which breaks if this
  deletion is committed. Not fixed this pass per instruction — flagging only. Needs a
  decision: restore it, or remove the README reference if deletion is intentional.
- **S04 code is done but not committed** — `eval.py` and `evals/gold_questions.json`
  have real, verified content in the working tree but have not been committed to git.
  This should go through `git-syncer` next (test gate: 107 pytest passed; eval gate:
  `python eval.py` runs clean, exit 0, no drift warnings, and correctly reports
  0%/FAIL on system-dependent metrics because no planner exists yet — that 0%/FAIL is
  the expected state per S04's done-when clause and should NOT block the commit).
- **S05 is the next unblocked spec after S04 is committed** — `graph-engineer` should
  build the planner node + LangGraph assembly next per the build-order table.
- **Minor test-layout inconsistency** (unchanged, non-blocking) — `test_tools_txn.py`
  lives under `tests/`, while `test_data_loader.py` and `test_tools_card.py` live at
  repo root. All 107 tests pass regardless of location (verified this pass via both a
  targeted 3-file run and a full repo-root `pytest -q --ignore=venv` collection — both
  report exactly 107 passed, 0 failed, confirming no other stray test files exist).
- No other uncommitted product-code changes observed beyond the four paths listed
  above; nothing else diverges from `origin/main`.
