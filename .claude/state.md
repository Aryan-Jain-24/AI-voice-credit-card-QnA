# Project State

_Last updated: 2026-08-11 (from-scratch inspection; prior file contents were not
trusted — every claim below was re-verified directly against the repo: files read,
`git diff`/`git log`/`git status` run, full `pytest` suite executed, and `eval.py`
executed twice end-to-end against the real OpenAI API in this pass)_

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | `app.py` and `voice.py` re-read this pass: still the verbatim S00 stubs (title/hello + API-key check; STT/TTS docstring only) — correct, S07/S08 not started yet. `.env` present locally (git-ignored), `.env.example` present, tracked, no diff vs HEAD. |
| S01 | `generate_data.py`, `data/transactions.csv` | done | Unchanged this pass. |
| S02 | `data_loader.py`, `mapping.yaml` | done | Unchanged this pass. |
| S03 | `tools_txn.py` (6 tools) | done | **Modified this pass** (see below) — docstring-only change to `top_merchants`, no behavior change. 694 lines (was 689). |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | **Modified this pass** (see below) — additive scalar fields only, no behavior change to existing fields. `tools_card.py` 750 lines (was 692). |
| S04 | `evals/gold_questions.json`, `eval.py` | done | `evals/gold_questions.json` unchanged (still 55 questions, no diff). `eval.py` **modified this pass** (see below) — one regex fix, no gold-question changes. 950 lines (was 941). |
| S05 | `graph.py` planner node + assembly | **done — verified this pass, not yet committed** | See full verification below. |
| S06 | verbalizer node | **done — verified this pass, not yet committed** | Same file as S05, same verification. |
| S07 | `voice.py`, fuzzy merchant correction | not started | `voice.py` still the S00 stub. **Now unblocked**: CLAUDE.md's hard rule ("do not start S07 until S05+S06 pass their gate via text input") is satisfied — see gate table below. |
| S08 | `app.py`, Streamlit deploy | not started (beyond S00 skeleton) | `app.py` still the S00 "hello" placeholder. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | not started | No `EVAL_REPORT.md` anywhere in the repo. `README.md` unchanged. |

## S05/S06 verification (this pass)

Read `graph.py` in full (942 lines, up from the 4-line S00 docstring stub). This is
a real, complete implementation, not a stub:

- **State**: `TypedDict` with the exact 6+2 fields from PRD §7.2
  (`audio_in, transcript, tool_call, tool_result, answer_text, audio_out,
  needs_clarification`).
- **`build_graph()`**: a real `langgraph.graph.StateGraph` with nodes
  `plan → {query, clarify} → verbalize → END` / `clarify → END`, matching the
  module-docstring diagram and the spec shape exactly. `graph = build_graph()`,
  `app = graph` (alias), and `run_pipeline(utterance)` (the entry point `eval.py`
  looks for first) are all present and wired at module scope.
- **`plan_node`**: `ChatOpenAI("gpt-4o-mini", temperature=0).bind_tools(ALL_TOOLS,
  tool_choice="required")` — the planner never sees transaction data or
  card_terms.yaml, only the transcript; it can only pick a tool name + args, never
  a fact. Falls back to `ask_clarification` if the API somehow returns zero tool
  calls (fail-safe, not silent-guess).
- **`query_node`**: plain function invoking the planner's chosen tool via
  `tool.invoke(args)`, returning the tool's native dict (not a serialized
  ToolNode message) into `tool_result`. Filters out any arg name the tool doesn't
  declare; catches tool exceptions into a tagged `error_kind: tool_error` result
  rather than crashing.
- **`clarify_node`**: terminal node for both `ask_clarification` and `refuse`,
  answers are drawn from small fixed digit-free template dicts
  (`CLARIFY_QUESTIONS`, `REFUSE_MESSAGES`) — never LLM-authored, so a clarify/
  refuse turn can never accidentally contain an ungrounded number.
- **`verbalize_node`** (S06): `_build_facts()` deterministically renders an
  already-correct draft sentence per tool (one branch per each of the 10 data
  tools) with every number copied verbatim out of `tool_result`; the LLM
  (`gpt-4o-mini`, temperature 0) is asked only to smooth phrasing; `_validate()`
  independently re-checks the LLM's rewrite using logic that deliberately mirrors
  `eval.py`'s own `_extract_numbers`/`_flatten_numbers`/hallucination check, and
  falls back to the deterministic draft verbatim if the rewrite fails validation.
  Gap-admission (`found: false`) path is fully deterministic, no LLM call,
  guaranteed to contain "don't have" (matches eval.py's `GAP_PHRASES`).
- Confirmed the one-tool-call-per-turn rule, the never-guess-a-period rule, the
  card-terms-only-from-tools rule, and the refuse/clarify routing are all encoded
  in `PLANNER_SYSTEM_PROMPT`, not left to model discretion.

This is a real implementation fulfilling S05 and S06, not a stub or partial
placeholder.

## Test/eval verification (this pass, independent of graph-engineer's report)

- **`python -m pytest -q`**: **107 passed, 0 failed**, 1.91s. Matches the
  reported pre-existing count exactly — the tool-file changes below did not
  break anything.
- **`python eval.py` run 1** (real OpenAI API): system-under-test detected
  (`graph.py pipeline found and invoked for all 55 questions`).
  Intent accuracy 100.0% (n=55), domain routing 100.0% (n=44), argument accuracy
  88.6% (n=44, target >=85%, PASS — this metric is not one of CLAUDE.md's six
  hard gates), numeric exactness Domain A 100.0% (n=22), term exactness Domain B
  100.0% (n=10), cross-domain rewards_earned exactness 100.0% (n=5),
  hallucination rate 0.0% (0 violations / 55 answers), gap-admission precision
  100.0% (n=5), clarify precision 100.0% + recall 100.0% (6/6), refusal precision
  100.0% + recall 100.0% (5/5). Latency p50 2.04s / p95 2.67s (targets <=4s/<=7s,
  both met this run).
- **`python eval.py` run 2** (real OpenAI API, immediately after, to check this
  isn't a one-off lucky run): **identical results on every metric** — 100% on
  every accuracy/correctness/precision/recall metric listed above, 0
  hallucination violations, argument accuracy 88.6% again. Latency p50 1.96s /
  p95 2.98s, again within target.
- Two independent live runs in this pass reproduce graph-engineer's reported
  100%-on-every-hard-gate result exactly (their 4 runs also reported 100% on
  every accuracy/hallucination/precision metric each time, with only p95 latency
  — not a hard gate — crossing 7s once). Combined evidence (this pass's 2 runs +
  their reported 4 runs = 6 consistent full runs) is strong reproducibility
  evidence, not a single lucky pass.

**CLAUDE.md's hard rule — "do not start S07 (voice) until S05+S06 pass their gate
via text input" — is satisfied.** All six PRD §8 hard gates pass via text input
through `eval.py`, verified independently in this pass, not just taken on
graph-engineer's word.

## Hard gates (from PRD §8) — current status

| Metric | Target | Current (this pass, 2 live runs) | Status |
|---|---|---|---|
| Numeric exactness (Domain A) | >=95% | 100.0% (n=22), both runs | PASS |
| Term exactness (Domain B) | ==100% | 100.0% (n=10), both runs | PASS |
| Hallucinated facts | ==0 | 0 violations / 55 answers, both runs | PASS |
| No-invention on missing terms (gap-admission) | 100% | 100.0% (n=5), both runs | PASS |
| Clarify on underspecified | 100% | 100.0% precision + 100.0% recall (6/6), both runs | PASS |
| Out-of-scope refusal | 100% | 100.0% precision + 100.0% recall (5/5), both runs | PASS |

Latency (informal, not a hard gate): p50 ~2.0s / p95 ~2.7-3.0s in this pass's two
runs, comfortably under the <=4s/<=7s targets. graph-engineer separately reported
p50 1.98-8.37s and p95 exceeding 7s in one of their four runs — not reproduced in
this pass's two runs, and not a hard gate either way per PRD §8.

## Uncommitted changes in the working tree right now

`git status --porcelain` (5 modified files, no untracked files, no deletions):

- **`graph.py`** — new: S05 planner node + graph assembly, S06 verbalizer node
  (942 lines, was a 4-line docstring stub). This is the main S05/S06 deliverable.
- **`tools_card.py`** (+62/-5 net per `git diff --stat`) — additive only, no
  existing field removed or changed:
  - `card_rewards` now also returns `rate_basis_inr: 100` (the fixed "points per
    Rs. 100" basis quoted in every rewards clause).
  - `card_fees`' per-fee summary now also returns `waiver_spend_inr` and
    `min_amount_inr` (each `None` when the underlying yaml entry has no such
    term — never invented).
  - `card_offers` now also returns `benefit_numbers` on each offer: every number
    parsed out of that offer's `benefit` prose string, as a list of plain floats.
  - Rationale (stated in the code comments): `eval.py`'s hallucination check only
    trusts numeric leaves in the tool's return dict (`_flatten_numbers`), never
    digits parsed out of a prose string. Since S06's verbalizer speaks numbers
    straight out of `clause`/`benefit` text, those same numbers now also exist as
    literal scalars so they pass the grounding check by construction rather than
    by string-parsing coincidence.
  - Confirmed via `git diff tools_card.py`: no existing key removed, no existing
    return value's computation changed.
- **`tools_txn.py`** (+11/-4) — docstring-only change to `top_merchants`: added
  example utterances and an explicit instruction not to guess a period when none
  is given. No code/logic change. Confirmed via `git diff tools_txn.py`.
- **`eval.py`** (+10/-3) — one regex fix: `_NUM_IN_TEXT_RE` changed from
  `r"\d+(?:\.\d+)?"` to `r"\d[\d,]*(?:\.\d+)?"` (plus the one call site updated to
  `.replace(",", "")` the match before `float()`), so comma-grouped thousands
  like "1,000" parse as one number (1000.0) instead of splitting into "1" and
  "000" (1.0 and 0.0). Fixes a phantom unsatisfiable ground-truth value on the
  `domain_b_terms` gold question about the BigBasket offer ("...above Rs.
  1,000."). `evals/gold_questions.json` itself has no diff — only the parsing
  logic changed, not the gold data.
- **`.claude/state.md`** — this file, being overwritten by this pass.

None of these are committed yet. **git-syncer's next job**: run the test/eval
gate (already done in this pass — 107/107 pytest, 2 clean live eval runs) and
commit+push all five files above as the S05/S06 deliverable landing. The
tools_card.py/tools_txn.py/eval.py changes are incidental to S05/S06 (made by
graph-engineer while wiring the verbalizer against the existing tools and harness)
and should land in the same commit/push as graph.py, not be treated as a separate
unrelated change — they have no independent spec of their own and every line is
in direct service of making S05/S06's gate pass honestly.

## Recent activity

`git log --oneline -6` (still 6 commits on `main`, HEAD matches `origin/main` —
no new commits made this pass, only working-tree changes inspected/verified):

- `cf6ef16` S04: gold eval harness + 55-question gold set
- `457d983` Add orchestrator and git-syncer subagent definitions
- `09c7f2a` S03/S03B: transaction tools + card terms/rewards tools
- `04d6137` Merge initial LICENSE commit from GitHub
- `94e3a74` S00-S02: repo skeleton, synthetic transaction data, schema-swappable loader
- `75e5756` Initial commit

`requirements.txt` already listed `langgraph`, `langchain`, `langchain-openai`,
`openai` from S00 — no dependency changes needed for S05/S06, confirmed no diff.

## Open items / blockers

- **None blocking.** S05+S06 are functionally complete and verified passing
  every hard gate live, twice, in this pass.
- **Not yet committed/pushed** — `graph.py`, `tools_card.py`, `tools_txn.py`,
  `eval.py` all show modified-but-uncommitted in `git status`. This is the one
  concrete action item: **git-syncer should commit and push these four files
  (plus this state.md refresh) as the S05/S06 deliverable**, now that the gate
  has been independently reproduced twice against the real API in this pass.
- **S07 is now unblocked** per CLAUDE.md's hard rule, owned by
  `voice-ui-engineer` — but should only start after the above commit/push lands,
  so the verified-passing graph.py is what voice gets built around.
- **Minor test-layout inconsistency** (unchanged, non-blocking, carried over
  from prior passes) — `test_tools_txn.py` lives under `tests/`, while
  `test_data_loader.py` and `test_tools_card.py` live at repo root. All 107
  tests pass regardless of location.
- No `test_graph.py` / eval-adjacent unit tests were added for `graph.py` itself
  — `eval.py` is the verification surface for S05/S06 per the build order (S04
  was built specifically to gate S05/S06), and it passed live twice. Not treated
  as a gap since this matches the spec's intended verification path, but noting
  it explicitly for `voice-ui-engineer`/`git-syncer` visibility.
