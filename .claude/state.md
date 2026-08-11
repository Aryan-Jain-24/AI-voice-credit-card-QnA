# Project State

_Last updated: 2026-08-11 (from-scratch inspection; the prior state.md was **not**
trusted as a starting point — every claim below was re-verified directly against
the repo this pass: `git log`/`git status`/`git diff --stat` run, `voice.py` and
`test_voice.py` read in full, the full `pytest` suite executed, and `eval.py`
executed **three times** end-to-end against the real OpenAI API specifically to
check a flakiness report — see the flagged section below before treating S05/S06
as a durably green gate.)_

## Spec status

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | `app.py` still the verbatim S00 stub (title/hello + API-key check) — correct, S08 not started. `.env` present locally (git-ignored, untracked). `.env.example` tracked, clean vs HEAD. |
| S01 | `generate_data.py`, `data/transactions.csv` | done | 2,014 rows, confirmed by direct `pandas.read_csv` this pass. |
| S02 | `data_loader.py`, `mapping.yaml` | done | Unchanged this pass. |
| S03 | `tools_txn.py` (6 tools) | done | 6 `@tool`-decorated functions, confirmed by direct grep this pass. |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | 4 `@tool`-decorated functions, confirmed by direct grep this pass. |
| S04 | `evals/gold_questions.json`, `eval.py` | done | 55 gold questions, confirmed by direct `json.load` this pass. |
| S05 | `graph.py` planner node + assembly | done — committed and pushed (`d9c8e57`) | Unchanged this pass (`git diff --stat -- graph.py` empty). **See flakiness flag below — do not treat as unconditionally durable.** |
| S06 | verbalizer node | done — committed and pushed (`d9c8e57`) | Same file/commit as S05. Unchanged this pass. |
| S07 | `voice.py`, fuzzy merchant correction | **done — in working tree, not yet committed** | Verified real (not a stub) by reading both files in full this pass. See verification below. `git status` shows `voice.py` modified and `test_voice.py` untracked; HEAD is still `d9c8e57` (S05/S06) — **git-syncer has not run for S07 yet.** |
| S08 | `app.py`, Streamlit deploy | not started | `app.py` still the S00 "hello" placeholder, byte-for-byte the stub described in S00. Next unblocked spec — see below. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | not started | No `EVAL_REPORT.md` anywhere in the repo. `README.md` unchanged (still the S00 stub README). |

## S07 verification (this pass — read both files in full)

**`voice.py` (437 lines) is a real, complete implementation**, not a stub:

- `transcribe(audio_bytes, filename="audio.wav") -> str`: calls
  `client.audio.transcriptions.create(model="whisper-1", ...)`, passes
  `_MERCHANT_PROMPT` (every name in `generate_data.ALL_MERCHANTS`, ~50 merchants)
  as Whisper's `prompt` bias, logs the raw transcript at INFO, raises `ValueError`
  on empty input.
- `synthesize(text) -> bytes`: calls `client.audio.speech.create(model="tts-1",
  voice="nova", response_format="mp3")`, raises `ValueError` on empty input.
- `correct_merchants(text, merchants=None, threshold=75) -> str`: two-pass
  (exact-then-fuzzy, longest-window-first, non-overlapping) token-span matcher
  against `ALL_MERCHANTS` using `rapidfuzz.fuzz.ratio` on normalized strings, with
  a `_SKIP_SINGLE_WORD` denylist of ~120 in-domain/stopword tokens to suppress
  false positives. The module docstring documents empirical tuning: threshold 75
  (not the spec's approximate ~80) chosen because it's the smallest value that
  still catches the spec's own worked example ("Swiggie"->"Swiggy" scores 76.9)
  while staying above every measured false positive (e.g. "how"->"BookMyShow" 90
  under `WRatio`/`JaroWinkler`, which is why plain `fuzz.ratio` + denylist was
  chosen over those scorers instead).
- `build_voice_graph()` / `voice_graph` / `run_voice_pipeline()`: a **second**
  compiled LangGraph (`listen -> plan -> {query, clarify} -> verbalize/clarify ->
  speak -> END`) built from `graph.py`'s own unmodified `plan_node`, `route`,
  `query_node`, `clarify_node`, `verbalize_node` (imported, not copied). Confirmed
  by direct read that this does **not** touch `graph.py`'s own `build_graph()`,
  module-level `graph`/`app`, or `run_pipeline` — `git diff --stat -- graph.py`
  is empty this pass, confirming `graph.py` itself is byte-for-byte unchanged.
  `test_voice.py::test_voice_graph_is_a_separate_object_from_text_graph` asserts
  `voice.voice_graph is not graph.graph` and `is not graph.app` directly.

**`test_voice.py` (178 lines, 21 test functions, confirmed by
`grep -c '^def test_'` and by `pytest test_voice.py -q` collecting and passing 21)
is a real offline suite**, not a stub: true-positive merchant-correction cases
(Swiggie->Swiggy, Zomatoo->Zomato, split compounds, "Mac Donalds"->"McDonald's"),
false-positive guards (dining/amount/payment/rate/compare/number NOT corrected to
IndiGo/Amazon/Paytm/Airtel/Croma/Uber), an "already correct, left alone" case, a
merchant-prompt-completeness check, `transcribe`/`synthesize` empty-input
validation, and the voice-graph-isolation check above. No network/API-key calls —
runs fully offline, expectations hand-copied from `ALL_MERCHANTS`, not
round-tripped through the function under test.

**Files confirmed untouched this pass** (`git diff --stat -- graph.py
tools_txn.py tools_card.py eval.py card_terms.yaml requirements.txt app.py` —
empty): S07 touched only `voice.py` and added `test_voice.py`, exactly as
voice-ui-engineer reported. `requirements.txt` already listed `rapidfuzz`, no new
dependency needed.

## Test suite (run directly this pass)

**`python -m pytest -q`: 128 passed, 0 failed, 3.80s.** Matches voice-ui-engineer's
reported count exactly (107 pre-S07 + 21 new in `test_voice.py` = 128).
`test_voice.py` alone: 21/21 passed in isolation too.

## eval.py flakiness — investigated directly this pass, CONFIRMED REAL

**voice-ui-engineer's report is accurate.** Per the task instructions, `eval.py`
was run three separate times, live against the real OpenAI API, specifically to
get first-hand evidence rather than relying on their characterization. Full
metrics from all three runs:

### Run 1 (22:28-22:30)

| Metric | Score | Target | Status |
|---|---|---|---|
| Intent accuracy | 100.0% (n=55) | >=90% | PASS |
| Domain routing accuracy | 100.0% (n=44) | >=95% | PASS |
| Argument accuracy | 88.6% (n=44) | >=85% | PASS |
| Numeric exactness (Domain A) | 100.0% (n=22) | >=95% | PASS |
| Term exactness (Domain B) | 100.0% (n=10) | ==100% | PASS |
| Cross-domain exactness (rewards_earned) | 100.0% (n=5) | >=95% | PASS |
| Hallucination rate | 0.0% (n=55) | ==0% | PASS |
| Gap-admission precision | 100.0% (n=5) | ==100% | PASS |
| Clarify precision / recall | 100.0% / 100.0% (6/6) | ==100% | PASS |
| Refusal precision / recall | 100.0% / 100.0% (5/5) | ==100% | PASS |

Latency p50/p95: 1.99s / 7.31s (targets <=4s/<=7s — p95 passed but with almost no
headroom this run).

### Run 2 (22:31-22:32)

Identical to run 1 on every gate metric — all PASS, all 100% except argument
accuracy (88.6%, not a hard gate). Latency p50/p95: 2.10s / 3.18s (comfortable
this run).

### Run 3 (22:33-22:34) — **reproduces the reported failure**

| Metric | Score | Target | Status |
|---|---|---|---|
| Intent accuracy | 98.2% (n=55) | >=90% | PASS |
| Domain routing accuracy | 97.7% (n=44) | >=95% | PASS |
| Argument accuracy | 86.4% (n=44) | >=85% | PASS |
| Numeric exactness (Domain A) | 100.0% (n=22) | >=95% | PASS |
| Term exactness (Domain B) | 100.0% (n=10) | ==100% | PASS |
| **Cross-domain exactness (rewards_earned)** | **80.0% (n=5)** | **>=95%** | **FAIL** |
| Hallucination rate | 0.0% (n=55) | ==0% | PASS |
| Gap-admission precision | 100.0% (n=5) | ==100% | PASS |
| **Clarify precision** | **85.7%** | **==100%** | **FAIL** |
| Refusal precision / recall | 100.0% / 100.0% (5/5) | ==100% | PASS |

Clarify recall was still 100% (6/6 underspecified questions triggered clarify) —
the 85.7% precision failure means clarify fired 7 times total, i.e. **one false
positive**: some question that should have routed to a normal tool call instead
got clarified. `cross_domain_rewards_earned` bucket breakdown: 4/5 correct (one
`rewards_earned` question got a wrong number, a routing/argument slip, or a
tool-call miss — `eval.py` has no `--verbose`/`--json`/per-question dump flag, so
the exact failing question/args could not be isolated further without
instrumenting the harness, which was out of scope for this inspection pass).
Latency p50/p95: 2.06s / 3.09s (fine this run — the metric failures are
independent of latency).

### Assessment

**Real, intermittent, non-deterministic failure — 1 of 3 runs this pass (~33%)
failed two PRD §8 hard gates** (`cross_domain_rewards_earned` and, critically,
`clarify precision`, which is explicitly one of the six official hard gates in
CLAUDE.md's table). Numeric exactness (Domain A) and Term exactness (Domain B —
the one held to a strict 100% by design, since it's "a dictionary lookup") stayed
100% clean across all three runs; the failures are concentrated in the
LLM-planner-dependent buckets (tool routing / clarify-vs-tool-call decision and
the cross-domain rewards question), consistent with `temperature=0` not
fully eliminating run-to-run variance in `gpt-4o-mini` tool-call selection for a
handful of borderline gold questions. This is a plausible root cause but not
confirmed without per-question logging.

**This is exactly what CLAUDE.md's S07 gate condition was meant to catch before
voice was layered on.** The gate language is "S05+S06 pass their gate via text
input" — on any given run they usually do, but "usually" is not the same claim as
"pass," and 1-in-3 failing two hard gates (one of which is explicitly named in
CLAUDE.md's own hard-gate table) is not a gate a build should be waved through on
without comment. voice-ui-engineer's own work (S07) does not appear to be at fault
— they touched only `voice.py`/`test_voice.py`, `graph.py` is confirmed
byte-for-byte unchanged this pass, and S07's test suite is separately green and
deterministic (offline, no live API calls). The flakiness is in `graph.py`'s
planner/routing behavior against the live OpenAI API, pre-existing since S05/S06,
just not caught by the single live run each prior pass happened to execute.

**Recommendation to the orchestrator: do not treat S05/S06 as unconditionally,
durably green.** Before shipping further on top of it (or at minimum before S09's
`EVAL_REPORT.md` reports a single clean number as "the" result), either (a) run
`eval.py` several more times to characterize the true failure rate and pin down
which specific gold question(s) are borderline, (b) add per-question verbose/JSON
output to `eval.py` so a failing run can be root-caused instead of only scored, or
(c) have `graph-engineer` look at whether the planner prompt/tool-choice for the
`cross_domain_rewards_earned` bucket and the clarify-trigger decision can be made
more deterministic (e.g. stricter tool-choice constraints, a lower-ambiguity
prompt) — this is a routing non-determinism bug, not a hard problem, per
CLAUDE.md's own framing of why Domain B is held to 100%. This does **not** block
S08 from starting (S08 is Streamlit UI wiring, orthogonal to planner accuracy),
but it should be visible to whoever signs off on the hard gates before
`handover-writer` (S09) writes them up as settled.

## Commit/push status (this pass)

- `git log --oneline` HEAD: `d9c8e57` (S05/S06) — **unchanged this pass, S07 not
  yet committed.**
- `git status`: `.claude/state.md` modified (this refresh), `voice.py` modified
  (S07, from stub to real implementation), `test_voice.py` untracked (S07, new).
  No other files touched.
- `git branch -vv`: `main` tracking `origin/main` at `d9c8e57` — S07's changes
  exist only in the local working tree, not yet pushed.
- The `D .env.example` entry noted as stale in the prior pass remains stale/moot:
  `.env.example` is tracked, present, unmodified, `git diff --stat -- .env.example`
  empty this pass.

## Hard gates (PRD §8) — current status

| Metric | Target | This pass | Status |
|---|---|---|---|
| Numeric exactness (Domain A) | >=95% | 100.0% all 3 runs | PASS (stable) |
| Term exactness (Domain B) | ==100% | 100.0% all 3 runs | PASS (stable) |
| Hallucinated facts | ==0 | 0 all 3 runs | PASS (stable) |
| No-invention on missing terms (gap-admission) | 100% | 100.0% all 3 runs | PASS (stable) |
| Clarify on underspecified | 100% | 100%/100%/**85.7% precision** (run 3) | **FLAKY — 1/3 runs FAILED** |
| Out-of-scope refusal | 100% | 100.0% all 3 runs | PASS (stable) |

Five of six hard gates were rock-solid across all three live runs this pass. The
sixth — clarify precision, an explicitly-named PRD §8 hard gate — failed on one
of three runs. **Not all six hard gates can currently be called durably green.**

## Next unblocked spec

**S08 — `app.py` Streamlit UI + deploy, owned by `voice-ui-engineer`,** per
CLAUDE.md's build-order table (S08 is blocked only behind S07 landing, not
behind S05/S06 being perfectly flake-free — S08 is UI wiring around
`run_voice_pipeline()`/`run_pipeline()`, orthogonal to planner accuracy).

S07's deliverables are functionally complete and test-verified
(voice.py real, test_voice.py 21/21, full suite 128/128) but **not yet committed
or pushed** — `git-syncer` has not run for this spec yet. Per the standard cycle
(builder finishes -> state-tracker refreshes state -> git-syncer commits/pushes),
S07 should be committed/pushed before or alongside starting S08, gated on its own
test run (already green, confirmed this pass) — `git-syncer`'s job, not
`voice-ui-engineer`'s or this pass's.

## Open items / blockers

- **Flagged above, not a hard blocker for S08, but should not be silently
  carried forward: `eval.py` shows real run-to-run flakiness that failed two PRD
  §8 hard gates (cross-domain exactness, clarify precision) on 1 of 3 live runs
  this pass.** Confirmed independently, not solely on voice-ui-engineer's report.
  Recommend surfacing this to whoever/whatever gates S09's final sign-off, and
  ideally giving `graph-engineer` a follow-up pass and/or `eval-harness-builder`
  a per-question verbose output mode before `handover-writer` writes
  `EVAL_REPORT.md` off a single run.
- **S07 uncommitted.** `voice.py` (modified) + `test_voice.py` (new, untracked)
  sit in the working tree only; `git-syncer` has not run yet for this spec.
- **Minor test-layout inconsistency** (unchanged, non-blocking, carried over from
  prior passes): `test_tools_txn.py` lives under `tests/`, while
  `test_data_loader.py`, `test_tools_card.py`, and `test_voice.py` live at repo
  root. All 128 tests pass regardless of location.
- No `test_graph.py` unit tests exist for `graph.py` itself — `eval.py` remains
  the only verification surface for S05/S06's planner/verbalizer behavior, and
  per the section above, that surface itself is not fully stable run-to-run.
- S09 (`EVAL_REPORT.md`, README swap guide, Loom outline) remains fully
  unstarted, last in build order, behind S07 (uncommitted) and S08 (not started).
