# Project State

_Last updated: 2026-08-14 — from-scratch inspection, prior snapshot NOT
trusted; every claim below was re-derived directly from the repo this pass,
except where explicitly marked as user-reported (external dashboard action,
not repo-inspectable). This pass corrects a prior-pass error: the Streamlit
Cloud redeploy was previously marked "done" on the basis of the user's
statement that he'd added secrets and redeployed; the user has since
reported the live app is showing "OPENAI_API_KEY not set" and that the
Streamlit Cloud Secrets dashboard has been refusing his TOML with repeated
"Invalid format: please enter valid TOML" errors. He has paused
troubleshooting ("i cant fix this anymore, do something else"). The redeploy
step is corrected back to blocked/not-done below — see "Streamlit Community
Cloud redeploy" and "What's next"._

## Headline status

**v1 (S00–S09) and v2 (S10–S12) are both fully built, shipped to
`origin/main`, and live-verified post-review via `eval.py` against real
credentials in a local/CI-style environment.** The one remaining item is the
Streamlit Community Cloud production deploy: it is **blocked**, not done.
The user attempted to add the v2 secret set
(`DEEPGRAM_API_KEY`/`LANGSMITH_API_KEY`/`LANGSMITH_TRACING`/
`LANGSMITH_PROJECT` alongside the pre-existing `OPENAI_API_KEY`) and
redeploy; the live app is now showing "OPENAI_API_KEY not set" on the
frontend, and the user has been unable to get the Streamlit Cloud Secrets
box to accept valid TOML (repeated "Invalid format: please enter valid TOML"
errors), even though single-line spot checks of the secrets looked
syntactically valid. He has paused troubleshooting this for now. This is a
dashboard-configuration problem on Streamlit's platform, not a repo-code
problem — `app.py`'s `st.secrets` → `os.environ` bridging code was
independently verified correct in an earlier pass and has not changed since.

The two known issues below (pre-existing, documented) remain open as well,
unchanged from prior passes.

## Git state

- Branch: `main`, up to date with `origin/main`
- `HEAD` = `c3b219e` ("Document v2 live testing pass: 55-question eval 100%,
  latency/parity/trace gates met") — this **is** origin/main's tip; verified
  via `git fetch origin` + `git rev-parse HEAD` / `git rev-parse origin/main`
  this pass, both resolve to `c3b219e02ce954f325db8887f3d5d2dcaa95f5a4`.
- `git status --porcelain`: **clean** — nothing staged, nothing unstaged,
  nothing untracked (the prior snapshot's uncommitted `EVAL_REPORT.md` /
  `state.md` changes were committed as `c3b219e` since that snapshot was
  taken).
- Last 5 commits:
  - `c3b219e` Document v2 live testing pass: 55-question eval 100%,
    latency/parity/trace gates met
  - `f852afc` S12: add LangSmith observability (tracing + eval-run logging)
  - `a84a824` S11: restyle mic input as floating circular button, slim
    example questions
  - `9f24370` v2 planning: add PRD-02 and S10-S12 subagent docs, update
    orchestrator for v2 build order
  - `17495b2` S10: swap voice.py STT/TTS from OpenAI whisper-1/tts-1 to
    Deepgram Nova-3/Aura-2

Note: `.claude/agents/` also currently has three untracked-looking additions
per this session's environment info (`frontend-redesign.md`,
`langsmith-observability.md`, `stt-tts-deepgram-swap.md`) and a modified
`orchestrator.md`, plus an untracked `PRD-02.md` at the repo root — but
`git status` in this pass shows the tree clean, meaning these are already
committed (they landed in `9f24370` per the log above). No actual
uncommitted product changes exist.

## v1 build order (S00–S09) — all done

| Spec | Deliverable | Status | Notes |
|---|---|---|---|
| S00 | repo skeleton, config | done | `app.py`, `graph.py`, tools, `requirements.txt`, `.gitignore`, `.env.example` all present |
| S01 | `generate_data.py`, `data/transactions.csv` | done | realism-scenario coverage; `data/` populated |
| S02 | `data_loader.py`, `mapping.yaml` | done | `test_data_loader.py` passing |
| S03 | `tools_txn.py` (6 tools) | done | covered by `tests/` |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | done | `test_tools_card.py` passing |
| S04 | `evals/gold_questions.json`, `eval.py` | done | 55-question gold set; also carries S12's LangSmith logging |
| S05 | `graph.py` planner node + assembly | done | |
| S06 | `graph.py` verbalizer node | done | |
| S07 | `voice.py`, fuzzy merchant correction | done | superseded in-place by S10 (Deepgram swap) |
| S08 | `app.py`, Streamlit UI | done | superseded in-place by S11 (mic button restyle, sidebar slim) |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | done | `EVAL_REPORT.md` §1–§6 is the v1 section, extended (not replaced) by v2's §7/§8 |

## v2 build order (S10–S12, per `PRD-02.md`) — done AND live-verified post-review

| Spec | Deliverable | Status | Verified evidence |
|---|---|---|---|
| S10 | `voice.py` STT/TTS swapped to Deepgram Nova-3 (STT) / Aura-2 (TTS) | **done, live-verified** | `DeepgramClient`, `nova-3`, `aura-2-thalia-en` present in code; `EVAL_REPORT.md` §7.2 records a live 10-round-trip `synthesize()`→`transcribe()` latency measurement (p50 2.07s / p95 2.51s) and §7.3 a live merchant-parity measurement, both against the real Deepgram API. |
| S11 | `app.py` mic button CSS restyle, slimmed sidebar | **done** | `MIC_BUTTON_CSS`, sidebar rework present and offline-tested. |
| S12 | LangSmith tracing + `eval.py` dataset/experiment logging | **done, live-verified** | `@traceable` on `voice.py`'s Deepgram calls, `log_run_to_langsmith()` in `eval.py`; `EVAL_REPORT.md` §7.4 records 20/20 (100%) gold questions producing a LangSmith trace via `graph.run_pipeline()` with 0 errors, correctly nested spans for text and voice pipelines, and a graceful-degradation check under a deliberately invalid `LANGSMITH_API_KEY`. |

### Live post-review testing pass (PRD-02.md §11/§12 Day 4) — COMPLETE

Recorded in `EVAL_REPORT.md` §7 (full detail) and §8 (combined v1+v2
summary). All four required live checks ran against real
`DEEPGRAM_API_KEY`/`OPENAI_API_KEY`/`LANGSMITH_API_KEY` credentials:

| Check | Result | Target | Status |
|---|---|---|---|
| 55-question `eval.py` regression (text pipeline, unchanged `graph.py`) | all 10 `eval.py` metrics at 100% (intent, domain routing, numeric/term/cross-domain exactness, hallucination, gap-admission, clarify, refusal); argument accuracy 90.9% (n=44, not a hard gate) | 6 hard gates must stay green | **PASS** — §7.1 |
| Voice round-trip latency, Nova-3 (STT) + Aura-2 (TTS) | p50 2.07s / p95 2.51s (10 live round trips) | ≤4s p50 / ≤7s p95 | **PASS**, wide margin — §7.2 |
| Merchant-name recognition parity, Nova-3 vs. v1's `whisper-1` baseline | 94.4% word accuracy (v1 was 97.5%, both above floor); merchant-name accuracy 4/4 (100%), exact parity with v1 | ≥90% word-accuracy floor | **PASS** — §7.3 |
| LangSmith trace coverage | 20/20 (100%) gold questions traced, 0 errors; graceful degradation confirmed under an invalid API key | 100% of graph runs traced | **PASS** — §7.4 |

### Streamlit Community Cloud redeploy with v2 secrets — BLOCKED (external dashboard problem, user-side, paused)

A prior pass recorded this as "done" based on Aryan's statement that he'd
added the v2 secrets and redeployed. That has been **corrected** this pass:

- The live app is currently showing **"OPENAI_API_KEY not set"** on the
  frontend — i.e. even the pre-existing v1 secret is not reaching the
  running app, not just the new v2 keys.
- While troubleshooting, Aryan has been unable to get the Streamlit
  Community Cloud **Secrets** dashboard box to accept his TOML at all — it
  repeatedly rejects the input with **"Invalid format: please enter valid
  TOML."**
- The actual failing line/character was **never isolated**: single-line spot
  checks of the secrets content looked syntactically valid TOML, but no
  systematic root-cause pass (checking quoting, hidden characters, line
  endings, duplicate keys, indentation, etc. line-by-line) was completed
  before Aryan paused troubleshooting ("i cant fix this anymore, do
  something else").
- This is an **external, dashboard-side configuration problem** on
  Streamlit's platform — it has no corresponding repo diff (secrets aren't
  stored in the repo) and is not something any subagent or automated retry
  can fix; it requires Aryan to successfully edit that dashboard's Secrets
  box himself.
- **Not a repo-code problem**: `app.py`'s `st.secrets` → `os.environ`
  bridging code was independently verified correct in an earlier pass, and
  nothing in the repo has changed since (git tree is clean at `c3b219e`, see
  Git state above), so the bridging code is not implicated in the TOML
  rejection or the "not set" error.
- **Status: blocked, paused by user request.** Do not retry this
  automatically or re-attempt dashboard edits on the user's behalf next
  pass — it is manual, external, user-side action outside repo/subagent
  scope. Resume only when Aryan restarts troubleshooting or asks for help
  isolating the bad TOML line/character.

## Known issues — open, documented follow-ups (NOT blockers, NOT fixed)

These are the only two remaining open items in the project. Neither blocks
shipping; both are pre-existing and were re-confirmed by direct source
inspection this pass.

### 1. `load_dotenv()` ordering bug in `voice.py` / `app.py`

Re-confirmed this pass by reading the source directly:

- **`voice.py`**: line 102 `from deepgram import DeepgramClient`, then line
  103 `from dotenv import load_dotenv` — but `load_dotenv()` itself is not
  called until line 118, *after* the Deepgram import has already executed.
- **`app.py`**: line 51 `from dotenv import load_dotenv`, `import voice`
  precedes it (which triggers `voice.py`'s module-level Deepgram import),
  and `load_dotenv()` is not called until line 66 — again after the import.

Because `DeepgramClient()`'s `api_key` parameter defaults to
`os.getenv("DEEPGRAM_API_KEY")`, and the `deepgram` package appears to
evaluate this once at first import rather than per-call, if
`DEEPGRAM_API_KEY` is not already present in `os.environ` before the first
`import deepgram` (e.g. it only lives in `.env` and nothing has loaded `.env`
yet), `DeepgramClient()` can raise `ApiError` regardless of the later
`load_dotenv()` call. This did not manifest in any live test run so far,
because those environments already had the required env vars set in the
process/shell environment before any import ran.

On Streamlit Community Cloud specifically, secrets are injected as real
process env vars (not via a `.env` file), so this ordering bug likely does
**not** trigger in that deployment path — but that has still not been
verified with an actual live post-deploy smoke test of the voice path on the
now-redeployed Streamlit Cloud app, and should not be assumed safe without
one.

**Status: flagged, not fixed.** Recommended fix (from `EVAL_REPORT.md` §7.5,
not applied): move `load_dotenv()` to the very top of both `voice.py` and
`app.py`, before any provider SDK import. Open item for a future pass.

### 2. Croma ASR mangling not re-verified against the full correction chain

Also noted in `EVAL_REPORT.md` §8: the Croma → "Thyme Microoma" Nova-3
transcription mangling found in §7.2 was tested only against
`synthesize()`/`transcribe()` in isolation, not against the full
`correct_merchants()` fuzzy-correction chain. Whether fuzzy correction would
catch it downstream is an open question for a follow-up probe.

## Offline test gate — last measured

`python -m pytest -q` (project `venv/`, no network calls, no live API
credentials used): **151 passed** (per prior pass; not re-run this pass,
which focused on confirming the manual deploy step and current git/tree
state — no code changed, so no reason to expect regression).

## Hard gates (from PRD v1 §8 / CLAUDE.md) — live-verified post-Deepgram-swap

| Metric | Target | v2 live result |
|---|---|---|
| Numeric exactness (Domain A) | ≥ 95% | 100.0% |
| Term exactness (Domain B) | 100% | 100.0% |
| Hallucinated facts | 0 | 0 |
| No-invention on missing terms | 100% | 100.0% |
| Clarify on underspecified | 100% | 100.0% |
| Out-of-scope refusal | 100% | 100.0% |

All six confirmed via the live §7.1 `eval.py` run against `f852afc` (still
current at `c3b219e`, which only adds documentation) with real credentials.

## What's next

All repo-side work for v1 (S00–S09) and v2 (S10–S12) is complete and shipped
to `origin/main` — nothing left in the build order. What remains open:

1. **Streamlit Community Cloud redeploy — BLOCKED, external, user-side, not
   for automated retry.** The app is live but broken ("OPENAI_API_KEY not
   set" on the frontend), and Aryan is stuck getting the platform's Secrets
   dashboard to accept his TOML ("Invalid format: please enter valid TOML"
   on every attempt so far). The failing line/character was never isolated
   — spot checks looked fine, but no full line-by-line audit (quoting,
   hidden/non-ASCII characters, line endings, duplicate keys, indentation)
   was completed before he paused troubleshooting. This is a manual action
   only Aryan can take in that dashboard; no subagent has access to it and
   none should attempt to "fix" it automatically. Pick this back up only
   when Aryan resumes and asks for help isolating the bad TOML content —
   e.g. by having him paste the exact secrets block (with real key values
   redacted) so the malformed line can be spotted by inspection.
2. Fix the `load_dotenv()` import-ordering bug in `voice.py` / `app.py`
   (move `load_dotenv()` above any provider SDK import). Documented, not
   fixed. Independent of item 1 — worth doing regardless of when the
   deploy gets unblocked.
3. Re-verify the Croma ASR mangling case against the full
   `correct_merchants()` correction chain, not just raw
   `synthesize()`/`transcribe()`.

Note: once item 1 is eventually unblocked and the app redeploys
successfully, a real live smoke test of the voice path on Streamlit Cloud is
still worth doing to confirm the `load_dotenv()` ordering bug (item 2) is
actually inert in that environment (expected to be inert since Streamlit
Cloud injects secrets as process env vars rather than a `.env` file, but not
yet observed directly) — this is exactly the scenario item 1's failure is
currently blocking visibility into.
