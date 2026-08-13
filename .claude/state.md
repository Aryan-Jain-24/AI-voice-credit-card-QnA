# Project State

_Last updated: 2026-08-13 — from-scratch inspection, prior snapshot not trusted.
Verified directly this pass: full repo file listing, `git status`, `git log
--oneline -20`, `git branch -vv`, `git diff --stat`, a full read of `app.py` and
`git diff app.py`, a full read of `test_app.py`, a live offline
`python -m pytest -q` run (141 passed, no live API calls), a
`--collect-only` count confirming 141 tests collected, and a targeted grep for
`langsmith`/`traceable` across `graph.py`, `test_app.py`, `tools_card.py`,
`requirements.txt` with the matches read in context._

## v1 status: DONE (S00–S09), shipped through commit c6bdb47

All of S00–S09 are present at root/`evals/`/`tests/` and unchanged this pass:
`generate_data.py`, `data/transactions.csv`, `data_loader.py`, `mapping.yaml`,
`tools_txn.py`, `card_terms.yaml`, `tools_card.py`, `evals/gold_questions.json`,
`eval.py`, `graph.py`, `voice.py` (later modified by S10 — see below), `app.py`
(later modified by S11 — see below), `EVAL_REPORT.md`, `README.md`,
`LOOM_SCRIPT.md`. No v1 gate work redone this pass.

## v2 status: S10 done and pushed, S11 implemented and uncommitted, S12 not started

`PRD-02.md` defines v2 as three workstreams: S10 (Deepgram STT/TTS swap in
`voice.py`), S11 (frontend redesign — floating mic button + slimmer sidebar in
`app.py`), S12 (LangSmith observability, depends on S10).

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S10 | Deepgram Nova-3/Aura-2 swap in `voice.py` | **done, committed and pushed** | Shipped in `17495b2` (code) + `9f24370` (v2 planning docs); both are on `origin/main`. Not re-verified line-by-line this pass since it's not the subject of this check — `git log` confirms both commits are the current `HEAD` and match `origin/main`. |
| S11 | mic button + sidebar rework in `app.py` | **implemented, uncommitted** | See detailed verification below. |
| S12 | LangSmith tracing + eval-run logging | **not started** | Grep for `langsmith`/`traceable` (case-insensitive) across `graph.py`, `test_app.py`, `tools_card.py` returns 4 hits, all read in context: `graph.py:36` and `tools_card.py:379,455` use "traceable" as a plain English word in docstrings/comments (nothing to do with the LangSmith SDK); `test_app.py:9` is a docstring line stating the test suite does *not* call LangSmith. No `@traceable` decorator, no `langsmith` import, and no `langsmith` package in `requirements.txt` anywhere in the repo. `.claude/agents/langsmith-observability.md` exists (the subagent definition for S12) but has not been invoked — no `evals/` dataset-logging code, no tracing wiring in `graph.py` or `voice.py`. |

### S11 verification detail (this pass, direct inspection)

- **`app.py`** (345 lines, fully read this pass; `git diff --stat`: +111/-33
  lines against `HEAD`): module docstring now says "restyled under S11
  (frontend-redesign)". Adds a `MIC_BUTTON_CSS` constant — a `<style>` block
  injected via `st.markdown(MIC_BUTTON_CSS, unsafe_allow_html=True)` — that
  targets the native `st.audio_input` widget's own `data-testid="stAudioInput"`
  DOM node: `position: fixed`, bottom-right floating circular button (92px,
  76px on mobile via a `@media (max-width: 640px)` block), idle color
  `#1f6feb` (blue), and a `:has([data-testid="stAudioInputWaveSurfer"])` /
  `:has([data-testid="stAudioInputWaveformTimeCode"])` selector that swaps to
  `#e5484d` (red) once the widget's own waveform/timecode nodes appear in the
  DOM during/after a recording — no JS, no custom component, no
  `streamlit-webrtc`. The widget call itself (`st.audio_input(...)`) is
  unchanged in interaction model, just re-styled and given
  `label_visibility="collapsed"`.
- **`EXAMPLE_QUESTIONS`**: changed from a `dict[str, list[str]]` of 3 groups ×
  3 questions (9 total, v1/S08) to a flat `list[str]` of exactly 5 — one per
  question shape (total spend, category breakdown, a card-terms/fee lookup, a
  cross-domain rewards-points question, and one deliberately underspecified
  "How much did I spend?" that exercises the clarify path, matching gold-set
  Q45 per the code comment).
  Sidebar now renders: "How to use this" caption block, then "Try asking"
  (the 5 buttons), then "Dataset" (unchanged dataset-summary block reading
  `data_loader.load_transactions()` + `card_terms.yaml`, same as v1 — no
  second hand-maintained copy of these facts).
  `run_turn()`, `render_result()`, and the mic/session-state wiring
  (`st.session_state["last_result"]`, audio-hash de-dupe so re-runs don't
  re-invoke the paid pipeline on an unchanged recording) are unchanged from
  v1's S08 shape — S11 is a visual/copy pass only, no orchestration logic
  touched, consistent with `.claude/agents/frontend-redesign.md`'s brief.
- **`test_app.py`** (new file, 102 lines, 10 `test_` functions, untracked):
  asserts `len(EXAMPLE_QUESTIONS) == 5`, no duplicates, all non-empty, and
  that the 5 cover the 5 named shapes (including the literal clarify question
  "How much did I spend?"); asserts `MIC_BUTTON_CSS` targets
  `data-testid="stAudioInput"`, is a well-formed `<style>...</style>` block,
  uses `position: fixed`, defines the two distinct idle/recording colors, and
  keys the recording-state swap off the widget's own
  `stAudioInputWaveSurfer` DOM node via `:has(`. A final test asserts
  `st.audio_input(` is still called in `app.py`'s source and that
  `streamlit_webrtc` is neither referenced in source nor imported into
  `sys.modules` — i.e. still the native widget, not a component swap. Suite
  docstring is explicit that it only asserts on static Python-level
  artifacts (the CSS string, the question list) — Streamlit runs in "bare
  mode" at import with no live network/API calls, and it explicitly does not
  call OpenAI/Deepgram/LangSmith. Visual confirmation (does the button
  actually render round and change color in a browser) is flagged in the
  docstring as a manual `streamlit run app.py` check, not something this
  suite can assert — **not performed this pass** (no browser session run).

**S11 is code-complete and passing its offline test gate, but is
UNCOMMITTED.** `git status --porcelain` shows `app.py` as `M` (modified,
unstaged) and `test_app.py` as `??` (untracked). Nothing from S11 has been
staged, committed, or pushed.

## Test status (verified live this pass)

- `python -m pytest -q` → **141 passed**, 4.67s. No failures.
- `python -m pytest -q --collect-only` confirms 141 tests collected (matches
  the run count).
- No live Deepgram/OpenAI/LangSmith API calls were made — `test_app.py`'s own
  docstring and test bodies confirm it only asserts on static Python
  artifacts; `test_voice.py` mocks the Deepgram client (per its own header
  comment, unchanged this pass).
- `eval.py`'s live-API 55-question gold-set gate was **deliberately NOT run**
  this pass, per `PRD-02.md` §11 (no live Deepgram/OpenAI/LangSmith calls
  during S10–S12 construction, gated on a human review checkpoint after all
  three land).

## Git status (verified this pass)

- Current branch: `main`, tracking `origin/main`, `git branch -vv` shows both
  at `9f24370` — **up to date, nothing to pull or push on ref level**.
- `HEAD` = `9f24370` ("v2 planning: add PRD-02 and S10-S12 subagent docs
  (frontend redesign, LangSmith observability, Deepgram swap), update
  orchestrator for v2 build order"), same as `origin/main`'s tip.
- History since v1's last commit, newest first: `9f24370` (v2 planning docs) →
  `17495b2` (S10 Deepgram swap, code) → `c6bdb47` (v1's last commit, S08
  cleanup). Both `17495b2` and `9f24370` are pushed.
- Working tree is **not clean**:
  - Modified, unstaged: `app.py` (S11 mic button CSS + sidebar rework,
    +111/-33 lines).
  - Untracked: `test_app.py` (S11's new test suite, 102 lines).
  - Nothing else is dirty — `voice.py`, `requirements.txt`, `.env.example`,
    `test_voice.py` (S10's deliverables) are all clean/committed, contrary to
    what an older snapshot of this file may have claimed; S10 is fully landed
    on `origin/main`.

## Next unblocked spec

**S11 is implemented and gated but not shipped.** The next action is not a
new spec — it's closing out S11: hand the working tree
(`app.py` + `test_app.py`) to `git-syncer` to run the test gate (already
green, 141 passed) and commit + push to `origin/main`. `state-tracker`
should be re-run immediately after to confirm the push landed before anyone
starts S12.

Once S11 is committed and pushed, **S12 (LangSmith observability)** is the
next unblocked spec — its stated dependency (S10) is already done and pushed.
S12 has not been started: no `langsmith` package in `requirements.txt`, no
`@traceable`/tracing wiring in `graph.py` or `voice.py`, no dataset/experiment
logging around `eval.py`'s 55-question run. `.claude/agents/
langsmith-observability.md` exists and is ready to be invoked once S11 is
merged into `origin/main`, per `PRD-02.md`'s v2 build order (S10 → S11 → S12
is not a strict dependency chain per PRD-02, but the orchestrator's stated
policy is one spec at a time, sequential — S11 should ship before S12 starts).
