# Project State

_Last updated: 2026-08-13 — from-scratch inspection, prior snapshot not trusted.
Verified directly this pass: full repo file listing, `git status`, `git log
--oneline -15`, `git diff` on every file `git status` reported as modified
(`.env.example`, `eval.py`, `requirements.txt`, `voice.py`), a full read of the
new `test_langsmith.py`, `pip show langsmith` in the active venv, and a live
offline `python -m pytest -q` run (151 passed, no live API calls). No live
Deepgram/OpenAI/LangSmith network calls were made; `eval.py`'s live 55-question
gate was not run, per `PRD-02.md` §11._

## v1 status: DONE (S00–S09), shipped through commit c6bdb47

All of S00–S09 are present and unchanged this pass: `generate_data.py`,
`data/transactions.csv`, `data_loader.py`, `mapping.yaml`, `tools_txn.py`,
`card_terms.yaml`, `tools_card.py`, `evals/gold_questions.json`, `eval.py`
(later modified again by S12 — see below), `graph.py`, `voice.py` (modified by
S10, then S12), `app.py` (modified by S11), `EVAL_REPORT.md`, `README.md`,
`LOOM_SCRIPT.md`.

## v2 status: S10 done and pushed, S11 done and pushed, S12 implemented and uncommitted

`PRD-02.md` defines v2 as three workstreams: S10 (Deepgram STT/TTS swap in
`voice.py`), S11 (frontend redesign — floating mic button + slimmer sidebar in
`app.py`), S12 (LangSmith observability, depends on S10).

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S10 | Deepgram Nova-3/Aura-2 swap in `voice.py` | **done, committed and pushed** | Shipped in `17495b2`. On `origin/main`. |
| S11 | mic button + sidebar rework in `app.py` | **done, committed and pushed** | Shipped in `a84a824` ("S11: restyle mic input as floating circular button, slim example questions"). On `origin/main`. Not re-verified line-by-line this pass since it's not the subject of this check — confirmed via `git log` that the commit is present and `main` is up to date with `origin/main` as of before this pass's S12 changes. |
| S12 | LangSmith tracing + eval-run logging | **implemented this pass, uncommitted** | See detailed verification below. |

### S12 verification detail (this pass, direct inspection)

- **`voice.py`** (diff read in full): imports `from langsmith import
  traceable`. Both raw Deepgram SDK calls are wrapped:
  `@traceable(run_type="tool", name="deepgram_transcribe")` on `transcribe()`
  and `@traceable(run_type="tool", name="deepgram_synthesize")` on
  `synthesize()`. A new module docstring block explains the rationale: these
  two functions are the only non-LangChain/non-LangGraph primitives in the
  pipeline, so they're the only spots needing an explicit wrap — the rest
  (`listen_node`, `plan_node`, `query_node`, `verbalize_node`, `clarify_node`,
  `speak_node`, the compiled `voice_graph`) trace automatically once the
  `LANGSMITH_*` env vars are set, no code changes needed. With tracing env
  vars unset, `@traceable` is documented as a no-op passthrough. No other
  behavior in `voice.py` changed.
- **`eval.py`** (diff read in full): new `_langsmith_enabled()` gate — returns
  `True` only when both `LANGSMITH_API_KEY` is set and
  `LANGSMITH_TRACING` is truthy (`"true"/"1"/"yes"`, case-insensitive).
  New `log_run_to_langsmith(evald, metrics)`: no-ops immediately (no import,
  no network) when the gate is off; when on, lazily imports `langsmith.Client`
  inside a `try`, upserts a dataset (`credit-card-chatbot-gold-questions`)
  with one example per gold question keyed by a deterministic
  `uuid5`-derived id (so re-runs don't duplicate examples), then logs one
  `create_run(...)` per gold-question row under a timestamped experiment
  name, tagged by the question's `bucket` field (the same 9 buckets
  `gold_questions.json` already uses). Every external call is wrapped so a
  LangSmith outage/bad-import/bad-creds degrades to a logged warning, never a
  crashed eval run. `main()` now calls `log_run_to_langsmith(evald, metrics)`
  as the last line, strictly after `print_report(...)` — additive only, does
  not gate or alter the printed PASS/FAIL report or hard-gate metrics.
- **`.env.example`** (diff read in full): adds `LANGSMITH_TRACING=false`,
  `LANGSMITH_API_KEY=ls-...`, `LANGSMITH_PROJECT=credit-card-voice-chatbot`,
  with a comment noting tracing defaults off and degrades gracefully.
- **`requirements.txt`** (diff read in full): adds `langsmith` as an explicit
  line (after `langchain-openai`, before `openai`). Confirmed installed in
  the active venv (`pip show langsmith` → version 0.10.17).
- **`test_langsmith.py`** (new file, 265 lines, untracked, read in full): 9
  tests. Covers: `transcribe()`/`synthesize()` still behave identically with
  tracing env vars explicitly unset (mocked Deepgram client, same pattern as
  `test_voice.py`); both functions carry `__wrapped__` (proof `@traceable` is
  actually applied) without needing live tracing; `_langsmith_enabled()`
  truth table (unset/unset, key-only, flag-only, both-set); and
  `log_run_to_langsmith` — no-op path makes no calls at all when disabled,
  and the enabled path drives a fully in-memory fake `langsmith.Client`
  (monkeypatched, never real) asserting dataset upsert + 2 examples + 2 runs
  created + correct bucket tags, plus a "Client() raises" test proving
  outages are swallowed, not propagated.

**S12 is code-complete and passing its offline test gate, but is
UNCOMMITTED.** `git status --porcelain` shows `.env.example`, `eval.py`,
`requirements.txt`, `voice.py` as `M` (modified, unstaged) and
`test_langsmith.py` as `??` (untracked). Nothing from S12 has been staged,
committed, or pushed.

## Test status (verified live this pass)

- `python -m pytest -q` → **151 passed**, 4.37s. No failures.
- No live Deepgram/OpenAI/LangSmith API calls were made — `test_langsmith.py`'s
  own docstring and test bodies confirm the enabled-path tests monkeypatch
  `langsmith.Client` to an in-memory fake, never a real client; the
  disabled-path tests assert no import/network happens at all.
- `eval.py`'s live-API 55-question gold-set gate was **deliberately NOT run**
  this pass, per `PRD-02.md` §11 (no live Deepgram/OpenAI/LangSmith calls
  during S10–S12 construction).

## Git status (verified this pass)

- Current branch: `main`, tracking `origin/main`, up to date at the ref level
  (`git status` reports "up to date with 'origin/main'" — all divergence is
  in the uncommitted working tree, not in unpushed commits).
- `HEAD` = `a84a824` ("S11: restyle mic input as floating circular button,
  slim example questions"), same as `origin/main`'s tip.
- History since v1's last commit, newest first: `a84a824` (S11, code) →
  `9f24370` (v2 planning docs) → `17495b2` (S10 Deepgram swap, code) →
  `c6bdb47` (v1's last commit, S08 cleanup). All four are pushed.
- Working tree is **not clean**:
  - Modified, unstaged: `.env.example`, `eval.py`, `requirements.txt`,
    `voice.py` (all S12 deliverables).
  - Untracked: `test_langsmith.py` (S12's new test suite).
  - Nothing else is dirty.

## Next unblocked spec

**S12 is implemented and gated but not shipped.** The next action is not a
new spec — it's closing out S12: hand the working tree (`.env.example`,
`eval.py`, `requirements.txt`, `voice.py`, `test_langsmith.py`) to
`git-syncer` to run the offline test gate (already green, 151 passed) and
commit + push to `origin/main`. `state-tracker` should be re-run immediately
after to confirm the push landed.

**Once S10, S11, and S12 are all committed and pushed, per the orchestrator's
v2 hard rule the build STOPS for human review** rather than proceeding to a
live `eval.py` regression pass (the 55-question gold-set gate with real
Deepgram/OpenAI/LangSmith credentials). That live gate is explicitly deferred
to a human-initiated checkpoint per `PRD-02.md` §11 — it is not something any
subagent or the orchestrator should trigger automatically after S12 lands.
There is no further spec in `PRD-02.md`'s v2 scope beyond S10/S11/S12, so once
S12 is pushed, this project has no next unblocked spec until a human either
(a) runs and reviews the live eval gate, or (b) defines new scope.
