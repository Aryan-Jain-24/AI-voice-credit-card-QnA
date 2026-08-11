# Project State

_Last updated: 2026-08-12 (from-scratch inspection; the prior state.md was **not**
trusted — every claim below was re-verified directly against the repo this pass:
`git status`/`git diff --stat`/`git log`/`git rev-parse` executed directly,
`app.py` read in full, `graph.py`/`tools_txn.py`/`tools_card.py`/`card_terms.yaml`/
`eval.py`/`evals/gold_questions.json` diffed against `HEAD` directly,
`python -m pytest -q` run once directly, and `eval.py` run **five separate times**
live against the real OpenAI API — not fewer — specifically to settle an open
question about whether a previously-reported intermittent failure is noise or a
reproducible bug. It is neither pure noise nor a blanket bug — see the dedicated
section below. Per-question detail was obtained by writing a throwaway script in
the session scratchpad (outside the repo) that imports `eval.py`'s own
`evaluate()`/`compute_metrics()`/`print_report()` unmodified and additionally
prints per-row detail for two buckets; `eval.py` itself was never edited, and
nothing from that investigation was committed.)_

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | — |
| S01 | `generate_data.py`, `data/transactions.csv` | done | Unchanged this pass (no diff vs `HEAD`). |
| S02 | `data_loader.py`, `mapping.yaml` | done | Unchanged this pass. |
| S03 | `tools_txn.py` (6 tools) | done | Unchanged this pass (confirmed via `git diff --stat HEAD -- tools_txn.py`, empty). |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | Unchanged this pass. |
| S04 | `evals/gold_questions.json`, `eval.py` | done | Unchanged this pass. |
| S05 | `graph.py` planner node + assembly | done | Unchanged this pass. **See eval flakiness section — not unconditionally durable.** |
| S06 | verbalizer node | done | Same file (`graph.py`) as S05, same caveat. |
| S07 | `voice.py`, fuzzy merchant correction | done | Unchanged this pass. |
| S08 | `app.py`, Streamlit deploy | **done this pass — NOT yet committed/pushed** | See verification below. `app.py` is a real, substantial rewrite (278 lines; +266/-8 vs the old S00 stub per `git diff --stat`), not a stub. Sits uncommitted in the working tree — `git status` shows `app.py` modified, `HEAD` (`0f68f62`, S07) still equals `origin/main`. **Next action is `git-syncer`**, pending the gate decision below. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | not started | No `EVAL_REPORT.md` in the repo (`ls` confirms). `README.md` still the S00-stage placeholder pointing to PRD/specs, not the full S09 doc. |

## S08 verification (this pass)

- `git diff --stat HEAD -- app.py`: 274 lines changed (266 insertions, 8
  deletions) — a real rewrite, not a one-line edit or a stub swap.
- Read `app.py` in full (278 lines): implements `st.audio_input` mic capture,
  a `run_turn()` orchestrator that sequences `voice.py`'s own node functions
  (`listen_node`, `plan_node`, `route`, `query_node`, `clarify_node`,
  `verbalize_node`, `speak_node`) one at a time with real per-stage
  `st.status()` labels ("Listening…" / "Thinking…" / "Answering…"), an
  expander ("How it got this answer") showing tool name/args/raw result dict,
  a grouped sidebar of example questions (Your spending / Your card / Your
  rewards) that exercise the same `run_turn()` path with a typed transcript,
  and a dataset summary sidebar read live from `load_transactions()` +
  `card_terms.yaml`. Matches the S08 spec's seven required elements. Contains
  no planning/tool/ASR/TTS logic of its own — confirmed it only calls into
  `voice.py`, never reimplements graph/tool behavior.
- **Scope check — confirmed clean.** `git diff --stat HEAD -- graph.py
  tools_txn.py tools_card.py card_terms.yaml eval.py evals/gold_questions.json
  voice.py` is **empty** — voice-ui-engineer touched only `app.py` this pass, as
  required (S07's `voice.py` was already committed in `0f68f62` and is untouched
  now).
- `.env.example` exists on disk, tracked, and clean vs `HEAD` (the `D
  .env.example` seen in the very first snapshot at conversation start is stale
  and not reflected in current `git status`).

## Test suite (run directly this pass)

`python -m pytest -q`: **128 passed, 0 failed, 3.69s.** `--collect-only` also
reports 128 collected. Matches voice-ui-engineer's reported figure exactly.

## eval.py — five live runs this pass (raw, per-run — NOT averaged)

Ran `python eval.py` (or an import-only wrapper calling `eval.py`'s own
`evaluate()`/`compute_metrics()`/`print_report()` unmodified) five separate times
against the live OpenAI API. Every run scored all 55 gold questions. Full per-run
numbers for the two contested metrics, plus whether all six **literal PRD §8**
hard gates passed (numeric exactness, term exactness, hallucination=0,
gap-admission precision, clarify **recall**, refusal recall/precision — note the
PRD's "clarify on underspecified" gate is a recall metric over the 6
`underspecified_clarify` questions, a distinct number from `eval.py`'s own
"clarify precision" metric discussed below):

| Run | cross_domain_exactness (target ≥95%) | clarify precision (target ==100%) | All 6 literal PRD §8 gates? |
|---|---|---|---|
| 1 | **100.0%** PASS | **100.0%** PASS | PASS (6/6) |
| 2 | **80.0%** FAIL | **85.7%** FAIL | PASS (6/6) — failures are both non-literal-table metrics |
| 3 | **80.0%** FAIL | **85.7%** FAIL | PASS (6/6) |
| 4 | **80.0%** FAIL | **85.7%** FAIL | PASS (6/6) |
| 5 | **100.0%** PASS | **100.0%** PASS | PASS (6/6) |

**Raw pattern: 4 of 5 runs failed, identically, on the same two metrics with the
exact same scores (80.0% / 85.7%) every time; 1 of 5 (this pass's own "clean"
run) had every failing run's own scores flip to 100.0%/100.0%.** This is not
"mostly noise with one outlier" — it is the opposite: failure was the *majority*
outcome (4/5) this pass, with clean runs the minority. All six literal PRD §8
hard gates passed on every single run, all 5 times — the two contested metrics
are `eval.py`'s own additional (non-literal-PRD-table) metrics, not the PRD's
named gates themselves, though "clarify precision" is closely related in spirit
to the "no false clarifies" intent behind the PRD's clarify gate.

### Root cause, isolated to a single gold question (Q31)

Per-question instrumentation (temporary, scratchpad-only, not committed; reverted
by simply not touching `eval.py` — the investigation script only imported it)
shows that **in all four failing runs, exactly one question failed, and it was
the same question every time**:

- **Q31** — `"How many points did I earn last month?"` (bucket
  `cross_domain_rewards_earned`, `expected_tool="rewards_earned"`,
  `expected_behaviour="answer"`, required answer 2,912 points).
  - Runs 2, 3, 4 (all identical): the planner routed this to
    `ask_clarification(missing="period")` instead of calling `rewards_earned`,
    producing the answer *"Which time period are you asking about — for example
    this month, last month, or a specific month?"* — even though the utterance
    already names "last month" as the period. This single misroute is
    simultaneously: (a) the `cross_domain_rewards_earned` bucket's one failure
    (4/5 correct = 80.0%), and (b) `eval.py`'s one clarify **false positive**
    (an entry whose `expected_behaviour` is `"answer"` got scored as `"clarify"`),
    which drags `clarify_precision` from 6/6 to 6/7 = 85.7%. **The two failing
    metrics are not two independent bugs — they are the same single misroute
    counted by two different metrics.**
  - Run 5 (clean): the same utterance correctly routed to
    `rewards_earned(period="last month")` and produced *"You earned 2,912 points
    last month."*
  - Run 1 (clean, no per-question instrumentation captured, but consistent):
    both metrics scored 100%/100%, which is only possible if Q31 (the sole
    question ever observed to fail) was answered correctly that run too.
  - The other 4 `cross_domain_rewards_earned` questions (Q32–Q35) and all 6
    `underspecified_clarify` questions (Q45–Q50) passed in **every** run,
    5 for 5, with byte-identical answer text each time — the flakiness is
    entirely localized to Q31, not spread across the bucket.

`graph.py`'s planner prompt (read this pass) does explicitly instruct the model
to pass through a stated relative period like "last month" as the tool argument
rather than asking again, and explicitly gives `ask_clarification` as the
fallback only when "the question names NO time cue at all" — so this is a
genuine prompt-following failure at the model level, not a spec gap in the
prompt itself. `PLANNER_MODEL = "gpt-4o-mini"` at `temperature=0`
(`ChatOpenAI(model=PLANNER_MODEL, temperature=0)`), confirming OpenAI's
temperature-0 setting reduces but does not guarantee determinism — and here it
produced an 80% (4/5) failure rate on one specific phrasing, not rare noise.

### How this reconciles with the previous state-tracker's "1-of-3" finding

A previous pass ran `eval.py` three times and saw only 1 of 3 fail (33%). This
pass's larger sample (5 runs) saw 4 of 5 fail (80%). Combined across both
characterizations: 5 failures in 8 total live runs (62.5%). The two
characterizations are not in conflict — 3 runs is too small a sample to pin down
a rate this variable — but the combined, larger picture makes clear this is a
**real, recurring, majority-likelihood failure on one specific gold question**,
not rare intermittent noise that can be safely averaged away or attributed to
one bad run.

**Status: OPEN. Given a measured ~50-80% failure rate concentrated in one
reproducible, root-caused misroute (not diffuse noise), this should NOT be left
for S09 to merely document — it is a strong candidate for a `graph-engineer` fix
pass** (e.g., a few-shot example in the planner prompt contrasting "How many
points did I earn last month?" — has a period, call the tool — against "How many
points have I earned?" — no period, clarify — since Q31 and Q49 are structurally
adjacent and the model appears to sometimes conflate them). If a fix pass is not
taken before handover, `handover-writer` must report `EVAL_REPORT.md` with the
full multi-run table above (not a single favorable run), since citing only a
clean run would misrepresent a ~50-80%-reproducible failure as resolved.

## Hard gates (PRD §8) — current status

| Metric | Target | Status | Basis |
|---|---|---|---|
| Numeric exactness (Domain A) | >=95% | PASS (stable) | 100% in all 5 runs this pass |
| Term exactness (Domain B) | ==100% | PASS (stable) | 100% in all 5 runs this pass |
| Hallucinated facts | ==0 | PASS (stable) | 0 in all 5 runs this pass |
| No-invention on missing terms (gap-admission) | 100% | PASS (stable) | 100% in all 5 runs this pass |
| Clarify on underspecified (recall) | 100% | PASS (stable) | 100% in all 5 runs this pass — all 6 `underspecified_clarify` questions triggered clarify every time |
| Out-of-scope refusal | 100% | PASS (stable) | 100% in all 5 runs this pass |

All six **literal** PRD §8 hard gates passed on all 5 live runs this pass — this
matches voice-ui-engineer's own pre-work gate check. The open issue is
`eval.py`'s own additional metrics (`cross_domain_exactness`, `clarify
precision`), which are not literal PRD-table gates but measure something the PRD
clearly cares about (no false clarifies; correct cross-domain reward answers) and
failed in 4 of 5 runs this pass — see dedicated section above. Do not report the
six hard gates as "fully durably green" without the caveat that a real,
reproducible planner misroute exists on at least one gold question and fails
most live runs.

## Commit/push status (this pass)

- `HEAD` = `origin/main` = `0f68f62` (S07). Working tree is **not** clean:
  `git status --porcelain` shows `app.py` modified (this pass's S08 work) and
  `.claude/state.md` modified (this refresh). Nothing else.
- S08's `app.py` rewrite is real and tested (128/128 pytest, 5 live eval runs
  above) but **uncommitted and unpushed** — needs `git-syncer` next.
- `.env` exists locally, git-ignored, does not appear in `git status` — correct
  per CLAUDE.md.

## Next unblocked spec / next action

1. **Immediate: `git-syncer`** to commit and push the S08 `app.py` work — pytest
   is 128/128 and all 6 literal PRD hard gates passed on every one of this pass's
   5 live eval runs, so the commit gate itself is not blocked. (git-syncer should
   still be told about the open `cross_domain_exactness`/`clarify precision`
   flakiness so it isn't silently lost, even though it's not one of the literal
   gates git-syncer checks.)
2. **After that: S09**, owned by `handover-writer` — but per the open item above,
   consider routing through a **`graph-engineer` fix pass on the Q31-class
   misroute first**, since S09's `EVAL_REPORT.md` will otherwise have to document
   a ~50-80%-reproducible failure on an explicitly-scored gold question rather
   than a clean pass.

## Open items / blockers

- **`eval.py` cross_domain_exactness / clarify_precision flakiness — OPEN,
  root-caused this pass to a single gold question (Q31, "How many points did I
  earn last month?") that the planner intermittently (4 of 5 runs this pass, 5 of
  8 across both characterizations) misroutes to `ask_clarification` instead of
  calling `rewards_earned`.** Not a blocker for committing S08 (UI wiring is
  orthogonal), but must be fixed or very explicitly multi-run-documented before
  `handover-writer` finalizes `EVAL_REPORT.md` in S09. See dedicated section
  above for full detail and a concrete fix suggestion.
- `eval.py` has no built-in `--verbose`/`--json`/per-question output mode; this
  pass isolated Q31 via a throwaway external script (scratchpad-only, imports
  `eval.py` unmodified, not committed) rather than editing `eval.py`. If
  `eval-harness-builder` is invoked again, adding a permanent per-question dump
  mode would make future root-causing much faster.
- **Minor test-layout inconsistency** (unchanged, non-blocking, carried over):
  `test_tools_txn.py` lives under `tests/`, while `test_data_loader.py`,
  `test_tools_card.py`, and `test_voice.py` live at repo root. All 128 tests pass
  regardless; purely cosmetic.
- No `test_graph.py` unit tests exist for `graph.py` itself — `eval.py` remains
  the only verification surface for S05/S06's planner/verbalizer behavior, which
  is precisely the surface the Q31 flakiness concerns.
- S09 (`EVAL_REPORT.md`, README swap guide, Loom outline) remains fully
  unstarted, last in build order.
