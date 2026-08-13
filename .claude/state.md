# Project State

_Last updated: 2026-08-14 — from-scratch inspection, prior snapshot NOT
trusted; every claim below was re-derived directly from the repo this pass._

## Headline status

**v1 (S00–S09) and v2 (S10–S12) are both fully built, shipped to
`origin/main`, AND now live-verified post-review.** The `PRD-02.md` §11/§12
Day 4 post-review live testing checkpoint has been completed: a live
55-question `eval.py` regression run, a live Deepgram Nova-3/Aura-2 voice
round-trip latency check, a live merchant-name recognition parity check, and
a live LangSmith trace-coverage check were all run against real
`DEEPGRAM_API_KEY`/`OPENAI_API_KEY`/`LANGSMITH_API_KEY` credentials, and
`EVAL_REPORT.md` has been updated (new §7/§8) to record the results. This
was verified this pass by reading the actual current `EVAL_REPORT.md`
content (964 lines, `git diff --stat` shows +379/-33 vs. the committed
version), not by trusting the task description alone.

Working tree is **not** clean: `EVAL_REPORT.md` has this pass's live-test
update staged as an unstaged modification, and this file (`.claude/state.md`)
is also modified. Both are uncommitted as of this snapshot — the git-syncer
step for this update has not run yet.

## Git state

- Branch: `main`, up to date with `origin/main`
- `HEAD` = `f852afc` ("S12: add LangSmith observability (tracing +
  eval-run logging)")
- `git status --porcelain`: `EVAL_REPORT.md` and `.claude/state.md` modified
  (unstaged); nothing else
- Last 5 commits:
  - `f852afc` S12: add LangSmith observability (tracing + eval-run logging)
  - `a84a824` S11: restyle mic input as floating circular button, slim
    example questions
  - `9f24370` v2 planning: add PRD-02 and S10-S12 subagent docs, update
    orchestrator for v2 build order
  - `17495b2` S10: swap voice.py STT/TTS from OpenAI whisper-1/tts-1 to
    Deepgram Nova-3/Aura-2
  - `c6bdb47` S08: clean up Streamlit UI status box and remove debug
    expander

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
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | done | `EVAL_REPORT.md` §1–§6 is the v1 section, now extended (not replaced) by v2's §7/§8 — see below |

## v2 build order (S10–S12, per `PRD-02.md`) — done AND live-verified post-review

| Spec | Deliverable | Status | Verified evidence |
|---|---|---|---|
| S10 | `voice.py` STT/TTS swapped to Deepgram Nova-3 (STT) / Aura-2 (TTS) | **done, live-verified** | Code-complete as before (`DeepgramClient`, `nova-3`, `aura-2-thalia-en`), and now confirmed working end-to-end against real credentials: `EVAL_REPORT.md` §7.2 records a live 10-round-trip `synthesize()`→`transcribe()` latency measurement (p50 2.07s / p95 2.51s), and §7.3 a live merchant-parity measurement — both against the real Deepgram API, not mocked. |
| S11 | `app.py` mic button CSS restyle, slimmed sidebar | **done** | Unchanged this pass; `MIC_BUTTON_CSS`, sidebar rework present and offline-tested. Not itself a target of the live testing pass (no voice-latency-relevant UI logic), so no new live evidence needed beyond what already existed. |
| S12 | LangSmith tracing + `eval.py` dataset/experiment logging | **done, live-verified** | Code-complete as before (`@traceable` on `voice.py`'s Deepgram calls, `log_run_to_langsmith()` in `eval.py`), and now confirmed live: `EVAL_REPORT.md` §7.4 records 20/20 (100%) gold questions producing a LangSmith trace via `graph.run_pipeline()` with 0 errors, correctly nested spans for both the text pipeline (8 runs/question type) and full voice pipeline (12 runs, `deepgram_transcribe`/`deepgram_synthesize` nested under `listen`/`speak`), and a graceful-degradation check under a deliberately invalid `LANGSMITH_API_KEY` — pipeline still returned the correct answer (exit 0) with only stderr warnings, no interruption. |

### Live post-review testing pass (PRD-02.md §11/§12 Day 4) — COMPLETE

Recorded in `EVAL_REPORT.md` §7 (new section, added this pass) and
summarized in §8. All four required live checks ran against real
`DEEPGRAM_API_KEY`/`OPENAI_API_KEY`/`LANGSMITH_API_KEY` credentials:

| Check | Result | Target | Status |
|---|---|---|---|
| 55-question `eval.py` regression (text pipeline, unchanged `graph.py`) | all 10 `eval.py` metrics at 100% (intent, domain routing, numeric/term/cross-domain exactness, hallucination, gap-admission, clarify, refusal); argument accuracy 90.9% (n=44, not a hard gate) | 6 hard gates must stay green | **PASS** — §7.1 |
| Voice round-trip latency, Nova-3 (STT) + Aura-2 (TTS) | p50 2.07s / p95 2.51s (10 live round trips) | ≤4s p50 / ≤7s p95 | **PASS**, wide margin — §7.2 |
| Merchant-name recognition parity, Nova-3 vs. v1's `whisper-1` baseline | 94.4% word accuracy (v1 was 97.5%, both above floor); merchant-name accuracy 4/4 (100%), exact parity with v1 | ≥90% word-accuracy floor | **PASS** — §7.3 |
| LangSmith trace coverage | 20/20 (100%) gold questions traced, 0 errors; graceful degradation confirmed under an invalid API key (pipeline still returns correct answer, exit 0, only stderr warnings) | 100% of graph runs traced | **PASS** — §7.4 |

`EVAL_REPORT.md`'s v1 §1–§6 content is preserved unchanged as the historical
baseline; the v2 results are appended as new §7 (full detail) and §8
(combined v1+v2 summary), per the document's own stated methodology at the
top of the file. Verified directly by reading the full 964-line file this
pass, not by trusting the commit/task description.

### Known issue — latent bug found and flagged, NOT fixed (open item)

`EVAL_REPORT.md` §7.5 documents, and this pass independently confirmed by
reading the source directly, a real latent `load_dotenv()` ordering bug:

- **`voice.py`**: line 102 `from deepgram import DeepgramClient`, then line
  103 `from dotenv import load_dotenv` — but `load_dotenv()` itself is not
  called until line 118, *after* the Deepgram import has already executed.
- **`app.py`**: line 53 `import voice` (which triggers `voice.py`'s
  module-level Deepgram import), then `load_dotenv()` not called until line
  66 — again after the import.

Because `DeepgramClient()`'s `api_key` parameter defaults to
`os.getenv("DEEPGRAM_API_KEY")`, and the `deepgram` package appears to
evaluate this once at first import rather than per-call, if
`DEEPGRAM_API_KEY` is not already present in `os.environ` before that first
`import deepgram` (e.g. it only lives in `.env` and nothing has loaded `.env`
yet), `DeepgramClient()` can raise `ApiError` regardless of the later
`load_dotenv()` call. This did **not** manifest in any of the live tests
behind §7 because the test environment already had the required env vars
set in the process/shell environment before any import ran — so the failure
path was never exercised, but it is real and reachable under a plausible
local-setup or fresh-deploy sequence where `.env` is the only place
`DEEPGRAM_API_KEY` lives.

**Status: flagged, not fixed.** Recommended fix (from `EVAL_REPORT.md` §7.5,
not applied here): move `load_dotenv()` to the very top of both `voice.py`
and `app.py`, before any provider SDK import. This is an open item for a
future pass — do not silently drop it from tracking.

A second, unrelated open item is also noted in `EVAL_REPORT.md` §8: the
Croma → "Thyme Microoma" Nova-3 transcription mangling found in §7.2 was not
re-tested against the full `correct_merchants()` correction chain (only
`synthesize()`/`transcribe()` in isolation) — whether fuzzy correction would
catch it is an open question for a follow-up probe.

## Offline test gate — last measured

`python -m pytest -q` (project `venv/`, no network calls, no live API
credentials used): **151 passed** (per prior pass; not re-run this pass,
which focused on verifying the live-testing update to `EVAL_REPORT.md`).
Live `eval.py`/Deepgram/LangSmith results are new this pass and are recorded
above and in `EVAL_REPORT.md` §7, not from the offline suite.

## Hard gates (from PRD v1 §8 / CLAUDE.md) — now live-verified post-Deepgram-swap

| Metric | Target | v2 live result |
|---|---|---|
| Numeric exactness (Domain A) | ≥ 95% | 100.0% |
| Term exactness (Domain B) | 100% | 100.0% |
| Hallucinated facts | 0 | 0 |
| No-invention on missing terms | 100% | 100.0% |
| Clarify on underspecified | 100% | 100.0% |
| Out-of-scope refusal | 100% | 100.0% |

All six confirmed via the live §7.1 `eval.py` run against `f852afc` with real
credentials — no longer resting on the pre-swap `whisper-1`/`tts-1` numbers.

## What's next

Everything through the Day 4 post-review live testing checkpoint (PRD-02.md
§11/§12) is now complete. The only remaining item:

1. **Redeploy to Streamlit Community Cloud** with `DEEPGRAM_API_KEY` and
   `LANGSMITH_*` secrets added alongside the existing `OPENAI_API_KEY` under
   Settings → Secrets. Caveat: given the §7.5 `load_dotenv()` ordering bug
   above, a fresh container start on Streamlit Cloud is exactly the kind of
   environment where `.env`-only credential loading could bite — Streamlit
   Cloud injects secrets as real process env vars (not via a `.env` file), so
   the ordering bug likely does *not* trigger in that specific deployment
   path, but this has not been verified live on an actual Streamlit Cloud
   container and should not be assumed safe without a real post-deploy smoke
   test of the voice path specifically.

Also still uncommitted: this state.md refresh and the `EVAL_REPORT.md` update
itself — both need a git-syncer pass (test/eval gate then commit+push) after
this snapshot is reviewed.
