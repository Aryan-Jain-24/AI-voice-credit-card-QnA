# Project State

_Last updated: 2026-08-13 — from-scratch inspection, prior snapshot not trusted.
Verified directly this pass: full repo file listing, `git status`, `git log
--oneline -10`, `git diff --stat` on the working tree, full read of `voice.py`,
grep/read of `test_voice.py`, `requirements.txt`, `.env.example`, the
`orchestrator.md` diff, a live offline `python -m pytest -q` run (131 passed, no
live API calls — deepgram client is mocked in `test_voice.py`), and confirmation
that `app.py`/`graph.py` are untouched since v1's last commit (`c6bdb47`). No live
Deepgram/OpenAI/LangSmith calls were made, and `eval.py`'s 55-question gate was
NOT run, per `PRD-02.md` §11's build-stage policy._

## v1 status: DONE (S00–S09), shipped as of commit c6bdb47

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | `requirements.txt`, `.gitignore`, `app.py`, `.env.example` all present at root. |
| S01 | `generate_data.py`, `data/transactions.csv` | done | Both present. |
| S02 | `data_loader.py`, `mapping.yaml` | done | Both present; `test_data_loader.py` passing. |
| S03 | `tools_txn.py` (6 tools) | done | Present; covered by `tests/test_tools_txn.py`. |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | Both present; `test_tools_card.py` passing. |
| S04 | `evals/gold_questions.json`, `eval.py` | done | Present at root/`evals/`. |
| S05 | `graph.py` planner node + assembly | done | `graph.py` present, unmodified since `c6bdb47`. |
| S06 | verbalizer node | done | Same file as S05. |
| S07 | `voice.py`, fuzzy merchant correction | superseded by S10 | See v2 section — S07's deliverable file now carries the S10 Deepgram swap. |
| S08 | `app.py`, Streamlit deploy (code) | done | `app.py` present, last touched by `c6bdb47` — no changes this pass. |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | done | All three present at root, shipped in `deda7cb`/`c6bdb47`. |

v1's own test suite (unit tests, not `eval.py`) is included in the 131-pass run
below; no v1 code changed this pass.

## v2 status: S10 implemented (uncommitted), S11 and S12 not started

`PRD-02.md` defines v2 as three workstreams: S10 (Deepgram STT/TTS swap in
`voice.py`), S11 (frontend redesign — standalone mic button + slimmer sidebar in
`app.py`), S12 (LangSmith observability, depends on S10).

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S10 | Deepgram Nova-3/Aura-2 swap in `voice.py` | **implemented, uncommitted** | See detailed verification below. |
| S11 | mic button + sidebar rework in `app.py` | **not started** | `app.py` unmodified since `c6bdb47` (v1's S08 cleanup commit, predates `PRD-02.md`). No mic-button CSS or sidebar-slimming work present. |
| S12 | LangSmith tracing + eval-run logging | **not started** | Grep for "langsmith"/"traceable" (case-insensitive) across `voice.py`, `app.py`, `graph.py`, `requirements.txt`: one hit, `graph.py`, the plain-English word "traceable" in a docstring — not an `@traceable` decorator or `langsmith` import. No `langsmith` package in `requirements.txt`. |

### S10 verification detail (this pass, direct inspection)

- **`voice.py`** (477 lines, fully read this pass): `transcribe()` now calls
  `client.listen.v1.media.transcribe_file(...)` with `model="nova-3"`, passing
  the full `ALL_MERCHANTS` list as Deepgram's `keyterm` parameter (the
  Nova-3-native replacement for whisper-1's free-text `prompt=`). `synthesize()`
  now calls `client.speak.v1.audio.generate(...)` with
  `model="aura-2-thalia-en"`, `encoding="mp3"`, draining the returned iterator
  into one `bytes` buffer. Client is a lazy singleton (`_get_client()` →
  `DeepgramClient()`), same pattern as v1's OpenAI client — importing the module
  never requires a live key. Zero references to `whisper-1`, `tts-1`, or OpenAI
  audio calls remain (grep-confirmed). `correct_merchants()` and the
  `listen_node`/`speak_node`/`build_voice_graph()`/`run_voice_pipeline()` call
  shapes are unchanged from S07 (single-shot, non-streaming, push-to-talk —
  matches `PRD-02.md`'s constraint not to change v1's call shape). Module
  docstring flags an open TODO: `FUZZY_THRESHOLD`/scorer/denylist were tuned
  against whisper-1's mangling patterns and haven't been retuned against real
  Nova-3 transcripts (blocked on live credentials, consistent with the
  no-live-calls policy).
- **`requirements.txt`**: `deepgram-sdk` added (one line, `git diff --stat`
  confirms `+1` line); `openai`/`langchain-openai` kept (still needed by
  `graph.py`'s planner/verbalizer, which S10 explicitly does not touch).
- **`.env.example`**: now documents both `OPENAI_API_KEY` (graph.py,
  "unchanged by S10") and `DEEPGRAM_API_KEY` (voice.py STT+TTS, "S10").
- **`test_voice.py`**: grew from its v1 form to 301 lines / 24 `test_` functions
  (`git diff --stat`: +146/-? net growth). Header comment states tests run
  "with the Deepgram client mocked out, so this suite still runs in CI/offline
  without network access or a real API key" — confirmed no live network calls
  occur; verified live by running the suite (see Test status below). Live
  end-to-end audio testing against real Deepgram credentials is explicitly
  deferred to a post-review step, per the file's own comment and
  `.claude/agents/stt-tts-deepgram-swap.md`.

**S10 is code-complete and passing its offline test gate, but is UNCOMMITTED.**
None of `voice.py`, `requirements.txt`, `.env.example`, or `test_voice.py` are
staged; `git status` shows all four as `modified` in the working tree only.

## Test status (verified live this pass)

- `python -m pytest -q` → **131 passed**, 3.71s. No failures, no live API calls
  (Deepgram client mocked in `test_voice.py`; no OpenAI/LangSmith calls in this
  suite either). Up from 128 passed at the last snapshot — the +3 net reflects
  `test_voice.py`'s growth to 24 test functions under S10.
- `eval.py`'s live-API 55-question gate was **deliberately not run** this pass,
  per `PRD-02.md` §11 (no live Deepgram/OpenAI/LangSmith calls during S10–S12
  construction, gated on a human review checkpoint after all three land) — this
  instruction explicitly reiterated the same constraint for this pass.

## Git status (verified this pass)

- Current branch: `main`, up to date with `origin/main`.
- `HEAD` = `c6bdb47` ("S08: clean up Streamlit UI status box and remove debug
  expander"), same as `origin/main`'s tip — **no v2 work has been pushed yet**.
- Working tree is **not** clean:
  - Modified, unstaged (S10 deliverable, from `stt-tts-deepgram-swap`):
    `voice.py`, `requirements.txt`, `.env.example`, `test_voice.py`
  - Modified, unstaged (v2 planning, carried over from before S10 started):
    `.claude/agents/orchestrator.md` — diff adds the S10–S12 rows to its spec
    table, v2 sequencing rules (S10 → S11 → S12, S12 gated on S10), the
    "continue into S10 once v1 is done and PRD-02.md exists" loop logic, the
    live-API ban during S10–S12 build, and updated "done" criteria
    distinguishing "v2 built, awaiting human review" from "fully complete."
  - Untracked (v2 planning, carried over, still untracked): `PRD-02.md`,
    `.claude/agents/frontend-redesign.md`,
    `.claude/agents/langsmith-observability.md`,
    `.claude/agents/stt-tts-deepgram-swap.md`.
  - `.claude/state.md` itself also shows as modified (this file, being
    overwritten this pass).
- No changes are staged. Nothing has been committed since `c6bdb47`.

**All five previously-uncommitted planning docs are still uncommitted**, exactly
as flagged in the prior snapshot — confirmed unchanged this pass. S10's four
code-deliverable files are now uncommitted alongside them.

## Recent commit history (most recent five)

```
c6bdb47 S08: clean up Streamlit UI status box and remove debug expander
deda7cb S09: fix planner third-party-brand fee misroute, ship handover docs
d61bbed Fix planner misroute of period-qualified rewards questions
157f46d S08: Streamlit UI wiring voice.py into a full voice Q&A app
0f68f62 S07: voice I/O wrappers, ASR merchant fuzzy-correction, voice-wrapped graph
```

## Next unblocked spec / next action

S10's code is done and its offline test gate is green, but **nothing is
committed**. The immediate next action is a `git-syncer` pass to commit+push
S10's deliverable (and, per the still-open question below, decide whether the
five pre-existing planning-doc changes ride along in the same commit or get
committed separately first) — running only the offline test gate (already
verified green this pass), never a live `eval.py` re-run, per `PRD-02.md` §11.

After S10 is committed and `state.md` is refreshed to reflect `done`, the next
unblocked spec is **S11** (`frontend-redesign`) — it has no dependency on S10 and
could in principle run in parallel, but the orchestrator's one-at-a-time rule
means S11 goes next regardless, per the default v2 order S10 → S11 → S12. **S12
(`langsmith-observability`) remains blocked until S10 is actually committed/done**
— its own agent doc requires the Deepgram swap already be in `voice.py`, which is
now true in the working tree but not yet true in the shipped `origin/main` state.

## Open items / carried-forward observations

1. **Five-plus-four uncommitted files, mixed provenance.** `git-syncer` (or
   whoever commits next) should be deliberate about whether S10's four files
   and the five pre-existing planning-doc changes land in one commit or are
   split — nothing in `CLAUDE.md`/`PRD-02.md` mandates either way. Flagging,
   not guessing.
2. **`PRD-02.md` §11's live-API ban is real project policy**, already reflected
   in the uncommitted `orchestrator.md` diff and honored again this pass (no
   live Deepgram/OpenAI/LangSmith calls made; `eval.py` not re-run). Any
   subsequent pass should keep honoring it through S11/S12 construction, up to
   the human review checkpoint.
3. **S10's own TODO**: `voice.py`'s fuzzy-correction tuning
   (`FUZZY_THRESHOLD`/scorer/denylist) was validated only against whisper-1's
   known mangling patterns, not real Nova-3 transcripts — flagged in the module
   docstring as needing retuning once live Deepgram credentials are available
   post-review. Not a blocker for shipping S10's code, but should not be
   forgotten before the live regression pass.
4. **No `test_graph.py` unit-test file exists for `graph.py`'s
   planner/verbalizer** — still true, by design (S04's `eval.py` is the
   regression net for that layer, per v1 build order). Unrelated to S10 but
   still worth carrying forward since nothing has changed it.
5. **Minor test-layout inconsistency** (cosmetic, non-blocking):
   `test_tools_txn.py` lives under `tests/`; `test_data_loader.py`,
   `test_tools_card.py`, `test_voice.py` live at repo root. All 131 tests pass
   regardless of layout.
6. **`requirements.txt` still has no `langsmith` package** — expected, S12
   hasn't started; the next pass building S12 needs to add it.
