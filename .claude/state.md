# Project State

_Last updated: 2026-08-12 (from-scratch inspection — the prior `state.md` was
**not** trusted; every claim below was re-verified directly against the repo
this pass). This pass's mandate: verify git-syncer's report that the round-3
planner robustness fix (Q31/Q10/Q50 few-shot interaction bug) is committed and
pushed as `d61bbed`, confirm a clean working tree, and add one independent
live-API confirmation run on top of the already-extensive prior verification
history. Verified directly this pass: `git log`, `git show --stat d61bbed`,
`git fetch origin` + `git log origin/main -1`, `git status` /
`git status --porcelain=2 -uall` (clean both ways), a live
`python -m pytest -q` run (128 passed), a live `python eval.py` run against
the real OpenAI API, a grep-level read of `graph.py`'s few-shot/prompt
machinery, and direct listing of the repo tree (including confirming
`EVAL_REPORT.md` still absent and `README.md` still the S00-stage
placeholder). **Verdict: fix is committed and pushed, tree is clean, gates are
green and stable. S09 is next and final.**_

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | `requirements.txt`, `.gitignore`, `app.py`, `.env.example` all present at repo root. |
| S01 | `generate_data.py`, `data/transactions.csv` | done | `data/transactions.csv` present (180,297 bytes); `generate_data.py` (32,725 bytes) at root. |
| S02 | `data_loader.py`, `mapping.yaml` | done | Both present at repo root; `test_data_loader.py` passing. |
| S03 | `tools_txn.py` (6 tools) | done | `spend_total`, `spend_by_category`, `top_merchants`, `compare_periods`, `find_transactions`, `recurring_charges`, plus `resolve_period`; covered by `tests/test_tools_txn.py`. |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | Both present; `test_tools_card.py` passing; untouched by the round-3 `graph.py` diff. |
| S04 | `evals/gold_questions.json`, `eval.py` | done | 55 gold questions, 9 buckets; `eval.py` runs live against the real pipeline (confirmed again this pass). Untouched by the round-3 diff. |
| S05 | `graph.py` planner node + assembly | **done, committed and pushed (`d61bbed`)** | Round-3 few-shot/prompt fix confirmed on `origin/main`. See "Planner fix — this pass's verification" below. |
| S06 | verbalizer node | done | Same file (`graph.py`) as S05; the round-3 diff is confined to the planner section (few-shot builder + one prose paragraph) — verbalizer untouched. |
| S07 | `voice.py`, fuzzy merchant correction | done | `voice.py` (18,663 bytes), `test_voice.py` passing; untouched by the round-3 diff. |
| S08 | `app.py`, Streamlit deploy (code) | done | `app.py` (11,184 bytes) present, wires `voice.py` into the graph; untouched by the round-3 diff. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | **not started — next and final spec** | `EVAL_REPORT.md` absent from repo root (confirmed via direct `ls` this pass). `README.md` still reads as the explicit S00-stage placeholder ("This repo is mid-build (currently at the S00 skeleton stage)... The full README... lands as part of the S09 handover spec") — confirmed by reading the file directly this pass, not assumed. Nothing now blocks starting it. |

## Planner fix — this pass's verification (independent confirmation of git-syncer's report)

git-syncer reported: round-3 planner robustness fix (few-shot + prose-paragraph
fix for the Q31/Q10/Q50 few-shot interaction bug found during post-S08 eval
testing) committed and pushed as `d61bbed` ("Fix planner misroute of
period-qualified rewards questions"), with pytest 128/128 and eval.py all hard
gates at 100% (argument accuracy 88.6%, non-hard-gate).

This pass independently confirmed, directly against the repo (not taken on
the report's word):

- **Commit exists and is reachable**: `git log --oneline -20` shows `d61bbed`
  as `HEAD`, one commit ahead of `157f46d` (S08).
- **Commit message matches the reported fix**: `git show --stat d61bbed`
  confirms author Aryan Jain, subject "Fix planner misroute of
  period-qualified rewards questions", touching exactly two files
  (`graph.py`: 151 changed lines; `.claude/state.md`: the refresh from the
  pass that produced this fix). Commit body describes the same Q31/Q10/Q50
  history, the four-few-shot-example approach, and the same pytest
  128/128 + eval.py 100%-hard-gates + 88.6%-argument-accuracy figures git-syncer
  reported.
- **Pushed to origin**: `git fetch origin` then `git log origin/main -1
  --oneline` returns `d61bbed` — confirmed on the remote, not just locally.
  `git status` reports "Your branch is up to date with 'origin/main'."
- **Working tree clean**: both `git status` and the stricter
  `git status --porcelain=2 -uall` (untracked files included) returned
  nothing to report — genuinely clean, no stray files, no uncommitted
  changes.
- **Fix content spot-checked in the live file**: grepped `graph.py` for the
  mechanism described in the commit message — `PLANNER_FEWSHOT_EXAMPLES` (list
  of few-shot tuples), `_build_planner_messages()` (the function that turns
  them into real `AIMessage`/`ToolMessage` conversation-history turns), the
  `AIMessage, ToolMessage` import addition, and the "topic word" routing
  language in the new prose paragraph (comment at line 373: "started keying
  off surface shape, not the question's own topic word" — matches the
  commit's stated fix rationale). All present as described.
- **pytest, run live this pass**: `python -m pytest -q` → **128 passed**,
  4.12s. Matches git-syncer's reported count exactly. `--collect-only` also
  confirms 128 tests collected, consistent.
- **eval.py, run live this pass against the real OpenAI API** (one
  confirmatory run, per instruction — this planner has now had over a dozen
  live runs across multiple agents/passes all showing 100% on hard gates
  post-fix, so an exhaustive multi-run repeat was not warranted):

  | Metric | Result | Target | Status |
  |---|---|---|---|
  | Intent accuracy (correct tool) | 100.0% (n=55) | >=90% | PASS |
  | Domain routing accuracy | 100.0% (n=44) | >=95% | PASS |
  | Argument accuracy (non-hard-gate) | 88.6% (n=44) | >=85% | PASS |
  | Numeric exactness (Domain A) | 100.0% (n=22) | >=95% | PASS |
  | Term exactness (Domain B) | 100.0% (n=10) | ==100% | PASS |
  | Cross-domain exactness (rewards_earned) | 100.0% (n=5) | >=95% | PASS |
  | Hallucination rate | 0.0% (0/55) | ==0% | PASS |
  | Gap-admission precision | 100.0% (n=5) | ==100% | PASS |
  | Clarify precision | 100.0% | ==100% | PASS |
  | Clarify recall | 100.0% (6/6 underspecified) | 100% | PASS |
  | Refusal precision | 100.0% | ==100% | PASS |
  | Refusal recall | 100.0% (5/5 out-of-scope) | 100% | PASS |
  | Latency p50 / p95 | 2.05s / 3.30s | <=4s / <=7s | PASS |

  Every per-bucket row (all 9 buckets: `domain_a_straightforward`,
  `domain_a_phrasing`, `domain_a_multi_constraint`, `domain_b_terms`,
  `cross_domain_rewards_earned`, `domain_routing_trap`, `missing_terms_gap`,
  `underspecified_clarify`, `out_of_scope_refuse`) reported 100.0% intent
  accuracy and 100.0% behaviour accuracy. Numbers match git-syncer's reported
  gate results exactly (identical to prior passes' repeated live runs — no
  variance observed across this now-extensive run history).

**Verdict: independently confirmed. The fix is genuinely committed and pushed
to `origin/main`, the working tree is clean, and one more live confirmatory
`eval.py` run reproduces 100% on every hard gate with no drift from prior
passes' figures. Nothing further to verify on S05/S06 — treat as closed and
stable.**

## Hard gates (PRD §8) — current status

| Metric | Target | Status | Basis |
|---|---|---|---|
| Numeric exactness (Domain A) | >=95% | PASS | 100.0% (22/22), live run this pass. |
| Term exactness (Domain B) | ==100% | PASS | 100.0% (10/10), live run this pass. |
| Hallucinated facts | ==0 | PASS | 0 violations, 55/55 answers checked, live run this pass. |
| No-invention on missing terms (gap-admission) | 100% | PASS | 100.0% (5/5), live run this pass. |
| Clarify on underspecified | 100% | PASS | 100.0% of 6 `underspecified_clarify` questions, live run this pass. |
| Out-of-scope refusal | 100% | PASS | 100.0% of 5 `out_of_scope_refuse` questions, live run this pass. |

All six literal hard gates pass cleanly, with no gate near its threshold.
`argument_accuracy` (88.6%) is explicitly a non-hard-gate metric per
`eval.py`'s own report and CLAUDE.md's gate table — tracked for visibility,
not a shipping blocker.

## Commit/push status (this pass)

- `HEAD` = `origin/main` = `d61bbed`. Working tree fully clean — confirmed via
  both plain `git status` and `git status --porcelain=2 -uall` (untracked
  files included), no output either way.
- `.env` exists locally, git-ignored, correctly absent from `git status`
  (confirmed: contains an `OPENAI_API_KEY` entry, used for this pass's live
  eval run). `.env.example` is tracked and clean vs. `HEAD`. (A stale `D
  .env.example` sometimes appears in an initial-snapshot artifact at session
  start that predates the session's own commands — not reflective of the
  actual tree; ignore it in favor of live `git status` output, consistent
  with prior passes' same finding.)
- Nothing to commit or push this pass. `git-syncer`'s work is done and
  verified; no further sync action needed before S09 starts.

## Next unblocked spec / next action

**S09 (`handover-writer`) is the next and final spec.** Nothing blocks it:
S00-S08 all read done, S05/S06's gate is confirmed green and stable (fresh
live run this pass, consistent with the extensive run history preceding it),
and the working tree is clean and pushed. `handover-writer` should produce:

- `EVAL_REPORT.md` (confirmed absent — write fresh, using this pass's live
  numbers above, or git-syncer's `d61bbed`-adjacent numbers, which are
  identical)
- `README.md` real version (confirmed current content is still the explicit
  S00-stage placeholder — replace with the architecture diagram, 5-command
  setup, and 30-minute data-swap guide per CLAUDE.md/PRD.md)
- Loom recording outline

## Open items / carried-forward observations (not blockers)

- **No `test_graph.py` unit-test file exists for `graph.py`'s
  planner/verbalizer** — confirmed again this pass via direct search (no
  match for `test_graph*` anywhere in the repo outside `venv/`) and via
  `pytest --collect-only` (128 tests collected, none from a `test_graph.py`).
  This is consistent with the project's own build-order design, not an
  oversight: CLAUDE.md's build order puts S04 (`eval-harness-builder`, the
  55-question gold set + `eval.py`) *before* S05/S06 (`graph-engineer`,
  the planner/verbalizer) specifically so the eval harness isn't built to
  match whatever the planner already does. In that design, `eval.py`'s live,
  API-backed, full-55-question runs *are* the planner's regression net by
  design — not a placeholder for a missing unit-test layer. Worth
  `handover-writer` stating this explicitly in `EVAL_REPORT.md`'s methodology
  section, so a reader doesn't mistake the absence of `test_graph.py` for a
  coverage gap: the three-round Q31/Q10/Q50 fix chain was in fact caught and
  verified entirely through this live-eval mechanism, working as intended.
- **`eval.py` has no built-in `--verbose`/`--json`/per-question output
  mode.** Each round of the planner fix chain (and every verification pass
  since, including this one) relied on `eval.py`'s aggregate report plus, when
  isolating a specific question, ad hoc direct `graph.run_pipeline()` calls
  outside the harness. A permanent per-question dump mode would make future
  root-causing faster. Not necessary for S09, but worth a mention in
  `EVAL_REPORT.md` or as a future-work note.
- **Minor test-layout inconsistency** (non-blocking, cosmetic): `test_tools_txn.py`
  lives under `tests/`, while `test_data_loader.py`, `test_tools_card.py`, and
  `test_voice.py` live at repo root. All 128 tests pass regardless of layout.
