# Project State

_Last updated: 2026-08-12 (from-scratch inspection — the prior `state.md` was
**not** trusted; every claim below was re-verified directly against the repo
this pass). This pass's mandate: scrutinize graph-engineer's THIRD fix attempt
on `graph.py`'s planner (round 3, on top of round 1 which fixed Q31 but broke
Q10, and round 2 which fixed Q31+Q10 but broke Q50). Verified directly this
pass: `git status`, `git log`, `git diff HEAD --stat`, `git diff HEAD --
graph.py` (full 178-line diff read in full), a line-by-line diff of the six
numbered planner rules against `HEAD` (byte-identical), the gold-question
text for Q10/Q25/Q26/Q27/Q31/Q45–Q50 read directly from
`evals/gold_questions.json`, **three full live `python eval.py` runs against
the real OpenAI API**, **two additional targeted live `run_pipeline()` checks**
isolating Q10/Q25/Q26/Q27/Q31/Q45–Q50 specifically, and one live
`python -m pytest -q` run (128 tests). **Verdict: round 3 is a clean win — see
"Planner fix chain review" below. Safe to ship.**_

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | — |
| S01 | `generate_data.py`, `data/transactions.csv` | done | `data/transactions.csv` present (180,297 bytes). |
| S02 | `data_loader.py`, `mapping.yaml` | done | Both present at repo root. |
| S03 | `tools_txn.py` (6 tools) | done | Confirmed 6 public tools present: `spend_total`, `spend_by_category`, `top_merchants`, `compare_periods`, `find_transactions`, `recurring_charges`, plus `resolve_period`. |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | Both present; untouched by this pass's `graph.py` diff. |
| S04 | `evals/gold_questions.json`, `eval.py` | done | 55 gold questions confirmed (9 buckets), `eval.py` runs and reports live against the real pipeline. Untouched by this pass's diff. |
| S05 | `graph.py` planner node + assembly | **done — round-3 fix verified clean, ready to commit** | See "Planner fix chain review" below. Uncommitted, sitting on top of `origin/main`'s `157f46d`. |
| S06 | verbalizer node | done | Same file (`graph.py`) as S05, untouched by any of the three fix rounds — diff is 100% confined to the planner (few-shot builder + one new prose paragraph). |
| S07 | `voice.py`, fuzzy merchant correction | done | Untouched by this pass's diff. |
| S08 | `app.py`, Streamlit deploy (code) | done, committed and pushed | `HEAD` = `origin/main` = `157f46d`. Untouched by this pass's diff. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | not started | `EVAL_REPORT.md` absent from repo root. `README.md` still the S00-stage placeholder (explicitly says "mid-build, S00 skeleton stage" and defers the real README to S09). Should start now that S05/S06 are clean, once `git-syncer` has shipped the round-3 `graph.py`. |

## Planner fix chain review — THE FINDING THIS PASS EXISTS TO PRODUCE

### Fix chain recap (for context, not re-litigated this pass except where it bears on round 3)

1. **Round 1** (prior session): fixed Q31 (rewards misroute → `ask_clarification`)
   with two same-themed few-shot examples, but introduced a reproducible
   regression on Q10 ("Food spend in July?" → misrouted to `rewards_earned`).
   Caught by a prior state-tracker pass. **Not committed.**
2. **Round 2** (earlier this session, per graph-engineer's own report):
   discovered the round-1 few-shot set had eval contamination (one example was
   the verbatim text of gold Q31). Rewrote with three paraphrased examples,
   fixing Q31 and Q10 — but their own isolation testing found the mere
   *presence* of few-shot history made the model stop clarifying on Q50
   ("What's the rate?").
3. **Round 3** (this diff, under review now): added a fourth few-shot example
   demonstrating the `ask_clarification(missing="category")` case, plus one
   new prose paragraph in `PLANNER_SYSTEM_PROMPT`. Reported as fixing all
   three (Q31, Q10, Q50) simultaneously.

### What changed, verified via full `git diff HEAD -- graph.py` (178 lines, read in full this pass)

Confirmed directly, not taken on the report's word:

- **Import line**: `AIMessage` and `ToolMessage` added to the
  `langchain_core.messages` import (needed to construct few-shot tool-call
  turns as real conversation history).
- **One new prose paragraph** inserted into `PLANNER_SYSTEM_PROMPT`,
  immediately after the existing month-resolution guidance and before the
  12-canonical-categories list. It states that terse/verb-less phrasing is
  never itself a routing signal — the tool is decided by the question's topic
  word ("spend"/"spent"/"blew"/"paid"/"charged" → transactions domain;
  "points"/"earn"/"earned"/"reward" → `rewards_earned`), and that presence or
  absence of a period only decides tool-call-at-all vs. `ask_clarification`,
  never *which* tool.
  - **The six original numbered planner rules (lines 239–280, rule 3 = the
    clarify-on-missing-argument rule) are byte-for-byte unchanged** — verified
    with a direct line-range diff against `git show HEAD:graph.py`, zero
    differences. The new paragraph is appended after rule 6, not interleaved
    with or renumbering the existing rules.
- **`PLANNER_FEWSHOT_EXAMPLES`**: now a list of **four** `(utterance,
  tool_name, tool_args)` tuples (confirmed by direct count in the diff):
  1. `"Utility spend in June?"` → `spend_total` — same terse
     category+period *shape* as Q10, but resolves to the Domain-A tool. This
     is the round-2 fix for the round-1 Q10 regression.
  2. `"How many reward points have I racked up this month?"` →
     `rewards_earned` — paraphrase of the Q31 pattern (period stated, rewards
     topic → call directly).
  3. `"How many total reward points do I have on this card?"` →
     `ask_clarification(missing="period")` — rewards topic, no period.
  4. `"Is there a cap on my rewards?"` → `ask_clarification(missing="category")`
     — **new this round**: demonstrates the category-missing clarify reason
     specifically, which round 2's three examples never demonstrated (they only
     ever showed `missing="period"`), leaving nothing for Q50 to anchor to.
  - **None of the four is verbatim gold-question text** — checked directly
    against `evals/gold_questions.json`'s Q10, Q25, Q26, Q27, Q31, Q49, Q50
    text this pass: closest matches are paraphrases with different
    wording/category/month in every case (e.g. example 1 uses "Utility... June"
    vs. Q10's "Food... July"; example 4 uses "Is there a cap on my rewards?"
    with no category, vs. Q26's "...dining reward points?" which names one).
    No eval-contamination risk found.
- **`_build_planner_messages()`**: unchanged in structure from round 2 — still
  prepends the few-shot set as real Human→AI(tool_call)→Tool turns before the
  actual transcript, with a placeholder `ToolMessage` per call to satisfy
  OpenAI's API pairing requirement.
- **`plan_node()`**: still just calls `_build_planner_messages()` instead of
  building a bare `[SystemMessage, HumanMessage]` list — unchanged from round 2.
- **Diff stat**: `graph.py | 151 +++++++++++--`, 148 insertions / 3 deletions.
  The 3 deletions are exactly the one changed import line and the two lines in
  `plan_node()` replaced by the `_build_planner_messages()` call — accounted
  for, nothing untracked.

### Confirmed: no other product file touched

`git diff HEAD --stat` shows only `.claude/state.md` (this refresh) and
`graph.py` differ from `HEAD` (`157f46d`). `app.py`, `voice.py`,
`tools_txn.py`, `tools_card.py`, `card_terms.yaml`, `eval.py`, and
`evals/gold_questions.json` are all byte-identical to `HEAD` — confirmed via
`git diff HEAD --name-only` listing exactly two paths.

### Live verification: 3 full `python eval.py` runs + 2 targeted `run_pipeline()` checks, all against the real OpenAI API

All three full runs, **zero variance, all metrics identical**:

| Metric | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Intent accuracy (correct tool) | 100.0% (n=55) | 100.0% (n=55) | 100.0% (n=55) |
| Domain routing accuracy | 100.0% (n=44) | 100.0% (n=44) | 100.0% (n=44) |
| Argument accuracy (non-hard-gate) | 88.6% (n=44) | 88.6% (n=44) | 88.6% (n=44) |
| Numeric exactness (Domain A) | 100.0% (n=22) | 100.0% (n=22) | 100.0% (n=22) |
| Term exactness (Domain B) | 100.0% (n=10) | 100.0% (n=10) | 100.0% (n=10) |
| Cross-domain exactness (rewards_earned) | 100.0% (n=5) | 100.0% (n=5) | 100.0% (n=5) |
| Hallucination rate | 0.0% (0/55) | 0.0% (0/55) | 0.0% (0/55) |
| Gap-admission precision | 100.0% (n=5) | 100.0% (n=5) | 100.0% (n=5) |
| Clarify precision | 100.0% | 100.0% | 100.0% |
| Clarify recall | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) |
| Refusal precision | 100.0% | 100.0% | 100.0% |
| Refusal recall | 100.0% (5/5) | 100.0% (5/5) | 100.0% (5/5) |
| Latency p50 / p95 | 2.12s / 5.52s | 2.22s / 6.83s | 2.07s / 3.27s | 

(Run 1 was triggered incidentally by an initial `python eval.py --help` probe —
`eval.py` has no argparse/CLI flags, so the unrecognized flag was ignored and
it ran the full live suite anyway. Treated as a legitimate first live run,
not discarded, since it exercised the real pipeline end-to-end identically to
runs 2 and 3.)

Per-bucket breakdown identical across all three runs — every one of the 9
buckets (`domain_a_straightforward`, `domain_a_phrasing`,
`domain_a_multi_constraint`, `domain_b_terms`, `cross_domain_rewards_earned`,
`domain_routing_trap`, `missing_terms_gap`, `underspecified_clarify`,
`out_of_scope_refuse`) at 100.0% intent accuracy and 100.0% behaviour accuracy,
all three runs.

### Q10 / Q31 / Q50 individually verified, twice, via direct `run_pipeline()` calls (bypassing `eval.py`'s aggregation)

A scratchpad-only script (`graph.run_pipeline(utterance)` called directly,
never touching `eval.py` or any tracked file) checked the three specific
historical failure points plus six adjacent boundary questions (Q25, Q26, Q27,
Q45–Q49) that stress the same clarify/answer decision from both sides. Run
twice, identical both times:

| ID | Utterance | expected_tool | expected_behaviour | actual_tool | actual_args | Match |
|---|---|---|---|---|---|---|
| Q10 | "Food spend in July?" | `spend_total` | answer | `spend_total` | `{period: "July 2026", category: "food_dining"}` | OK |
| Q25 | "What's the base reward rate on this card?" | `card_rewards` | answer | `card_rewards` | `{}` | OK |
| Q26 | "Is there a cap on my dining reward points?" | `card_rewards` | answer | `card_rewards` | `{category: "food_dining"}` | OK |
| Q27 | "What do I earn on fuel purchases?" | `card_rewards` | answer | `card_rewards` | `{category: "fuel"}` | OK |
| Q31 | "How many points did I earn last month?" | `rewards_earned` | answer | `rewards_earned` | `{period: "last month"}` | OK |
| Q45 | "How much did I spend?" | `ask_clarification` | clarify | `ask_clarification` | `{missing: "period"}` | OK |
| Q46 | "Where did my money go?" | `ask_clarification` | clarify | `ask_clarification` | `{missing: "period"}` | OK |
| Q47 | "Who do I spend the most with?" | `ask_clarification` | clarify | `ask_clarification` | `{missing: "period"}` | OK |
| Q48 | "Am I spending more than before?" | `ask_clarification` | clarify | `ask_clarification` | `{missing: "comparison"}` | OK |
| Q49 | "How many points have I earned?" | `ask_clarification` | clarify | `ask_clarification` | `{missing: "period"}` | OK |
| Q50 | "What's the rate?" | `ask_clarification` | clarify | `ask_clarification` | `{missing: "category"}` | OK |

All 11 matched expected tool in both targeted runs. **Q10 (round-1's
regression), Q31 (the original bug), and Q50 (round-2's regression) are all
independently confirmed fixed, individually, not just via aggregate metrics.**

### pytest

`python -m pytest -q`, run live this pass: **128 passed, 0 failed**, 3.96s.
(Same 128-test count as prior passes — no test files were touched by this
diff; test suite is unaffected by planner prompt/few-shot changes since none
of the 128 tests exercise `graph.py`'s planner directly — see "Open items"
below, carried over from prior passes, on the absence of a `test_graph.py`.)

### Historical context (for comparison — not re-run this pass, taken from the fix-chain report and consistent with what a prior state-tracker pass independently found for round 1)

- Round 1 (superseded): 3/3 and 5/5 live runs showed Q10 reproducibly misrouted
  to `rewards_earned`; `numeric_exactness` at 95.5% (21/22), `intent_accuracy`
  98.2%, `domain_routing_accuracy` 97.7% — a real regression, correctly caught
  and not shipped.
- Round 2 (superseded): fixed Q10/Q31 but Q50 flipped to `card_rewards()` under
  ANY single one of the three round-2 few-shot examples in isolation testing —
  not shipped.
- Round 3 (this diff): all three previously-failing questions now independently
  confirmed correct, 3 full-suite runs + 2 targeted runs, zero mismatches
  anywhere across all 55 gold questions in all 5 live checks this pass.

### Verdict

**Clean win. Safe to ship.** All three known failure points in this fix
chain (Q31, Q10, Q50) are independently verified fixed — both via full
55-question `eval.py` runs (3x, live, zero variance) and via direct
per-question `run_pipeline()` calls (2x, live) that bypass eval.py's
aggregation entirely. No fourth issue found: the nine adjacent boundary
questions checked alongside Q10/Q31/Q50 (Q25–Q27, Q45–Q49) — chosen
specifically because they stress the same clarify-vs-answer and
rewards-vs-transactions boundaries that broke in rounds 1 and 2 — all route
correctly too, both times. Every one of CLAUDE.md's six hard gates passes at
its target in all three full runs, with the two previously-unstable ones
(`numeric_exactness`, `cross_domain_exactness`) now at a clean 100% rather
than round 1's fragile 95.5%/one-question-from-failing. `argument_accuracy` is
stable at 88.6% across all three runs — unchanged from pre-fix history, not a
hard gate, not evidence of a new problem. The diff is confirmed confined to
`graph.py`'s planner section only (four few-shot examples + one prose
paragraph + the message-builder plumbing); the six numbered
`PLANNER_SYSTEM_PROMPT` rules and the verbalizer are untouched; no other
tracked file differs from `HEAD`.

**Recommendation: `git-syncer` should commit and push this `graph.py` diff.**

## Hard gates (PRD §8) — current status (uncommitted `graph.py`, i.e. this candidate fix)

| Metric | Target | Status | Basis |
|---|---|---|---|
| Numeric exactness (Domain A) | >=95% | **PASS, clean** | 100.0% (22/22) in all 3 live runs this pass — back to the historical baseline, no longer the fragile 95.5% seen after round 1. |
| Term exactness (Domain B) | ==100% | PASS (stable) | 100.0% (n=10) in all 3 runs this pass. |
| Hallucinated facts | ==0 | PASS (stable) | 0 violations, 55/55 answers checked, all 3 runs. |
| No-invention on missing terms (gap-admission) | 100% | PASS (stable) | 100.0% (n=5), all 3 runs. |
| Clarify on underspecified (recall) | 100% | **PASS, clean** | 100.0% of 6 `underspecified_clarify` questions, all 3 runs — includes Q50, individually re-verified twice via direct `run_pipeline()`. |
| Out-of-scope refusal | 100% | PASS (stable) | 100.0% of 5 `out_of_scope_refuse` questions, all 3 runs. |

All six literal gates pass cleanly, with margin, in every run this pass — no
gate is running close to its threshold the way `numeric_exactness` was after
round 1.

## Commit/push status (this pass)

- `HEAD` = `origin/main` = `157f46d` (S08). Working tree is **not clean**:
  `git status --porcelain=2 -uall` shows `graph.py` modified (round-3 planner
  fix, reviewed above and judged clean) and `.claude/state.md` modified (this
  refresh). Nothing else — no stray files; the scratchpad verification script
  used this pass lives only under the session scratchpad directory, never
  inside the repo, and never touched by `git add`.
- `.env` exists locally, git-ignored, does not appear in `git status` — correct
  per CLAUDE.md. `.env.example` is tracked and clean vs. `HEAD` (a `D
  .env.example` sometimes appears in a stale opening snapshot at session start
  but does not reflect the actual tree — confirmed clean directly this pass
  via a fresh `git status --porcelain=2 -uall`, consistent with prior passes'
  same finding; this looks like a snapshot-timing artifact, not real drift).

## Next unblocked spec / next action

1. **Immediate: `git-syncer` should commit and push the current `graph.py`
   diff.** This pass found it clean across 3 full live eval runs + 2 targeted
   live checks of the three specific historically-flaky questions (Q10, Q31,
   Q50) plus 6 adjacent boundary questions, plus a live 128/128 pytest pass,
   plus a full read of the diff confirming no unintended file or rule changes.
2. Once committed and pushed: proceed to **S09** (`handover-writer`) — last in
   build order. Nothing now blocks it: S05/S06 are clean, all hard gates pass
   with margin, and there is no known open regression in `graph.py`.

## Open items / blockers

- **Not blocking, but worth doing before more planner prompt changes land**:
  `eval.py` has no built-in `--verbose`/`--json`/per-question output mode.
  All three rounds of this fix chain (and this pass's own verification) had to
  isolate individual failing questions via a throwaway external script that
  calls `graph.run_pipeline()` directly. A permanent per-question dump mode in
  `eval.py` would make future root-causing faster — this is now the third
  time a single-question regression needed manual isolation outside the
  harness's own reporting.
- **No `test_graph.py` unit tests exist for `graph.py`'s planner/verbalizer.**
  `eval.py` (an LLM-in-the-loop, non-deterministic, API-cost-incurring harness)
  remains the *only* verification surface for planner routing behavior. All
  three rounds of misroute (Q31, Q10, Q50) were prompt/few-shot regressions
  that only a full 55-question live run caught — a deterministic unit-test
  layer (even a handful of mocked-LLM-response tests asserting
  `_build_planner_messages()`'s shape, or fixture-based tests of `route()`/
  `query_node()`/`clarify_node()`) would catch structural regressions without
  burning API calls or being subject to LLM sampling variance. Worth raising
  with `graph-engineer` before a fourth prompt change is attempted.
- **Minor test-layout inconsistency** (unchanged, non-blocking, carried over
  from prior passes): `test_tools_txn.py` lives under `tests/`, while
  `test_data_loader.py`, `test_tools_card.py`, and `test_voice.py` live at
  repo root. All 128 tests pass regardless; purely cosmetic.
- S09 (`EVAL_REPORT.md`, README swap guide, Loom outline) remains fully
  unstarted — now unblocked once `git-syncer` ships the round-3 `graph.py`.
  `handover-writer` should write `EVAL_REPORT.md` against the eval numbers in
  this pass's table (3 full-suite runs, all metrics at target) rather than
  re-running from scratch, though a confirmation run before finalizing the
  report would be reasonable given the fix chain's history of self-reports
  missing regressions.
