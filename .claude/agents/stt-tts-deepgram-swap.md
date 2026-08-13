---
name: stt-tts-deepgram-swap
description: Builds the V2 STT/TTS Deepgram swap (Spec S10) for the credit-card voice chatbot — replaces OpenAI whisper-1/tts-1 with Deepgram Nova-3/Aura-2 in voice.py, keeping v1's single-shot, push-to-talk call shape unchanged. Use when implementing the Deepgram STT/TTS integration.
tools: Read, Write, Edit, Grep, Glob, Bash
model: sonnet
---

You are building Spec S10 of the credit-card voice chatbot's V2 release:
swapping OpenAI `whisper-1` (STT) and `tts-1` (TTS) for Deepgram Nova-3 and
Aura-2, with no other behavior change.

## Context you need

v1 shipped a LangGraph voice pipeline (`listen → plan → query → verbalize →
speak`) with push-to-talk: the user holds a button, releases it, `whisper-1`
transcribes the full audio blob in one call, the planner/verbalizer
(`gpt-4o-mini`, unchanged in V2) does its typed-tool routing, and `tts-1`
synthesizes the full answer in one call before playback. V2 keeps that exact
interaction model — push-to-talk was considered for replacement with a
continuous/streaming session and explicitly decided against, so nothing about
turn-taking, barge-in, or session state should change here.

## Goal

Replace `whisper-1` and `tts-1` with Deepgram Nova-3 and Aura-2, preserving the
exact call shape v1 already has: one audio blob in → one transcript out; one
text in → one audio buffer out. Do not touch `gpt-4o-mini`'s role, the graph's
node set, or the state schema.

## Deliverables

- **`voice.py`**
  - STT: call Deepgram Nova-3 (`model="nova-3"`) via its prerecorded/single-shot
    endpoint. Input: the full audio blob captured on button release (same
    input source as today). Output: one transcript string (same downstream
    contract with the `listen` node).
  - TTS: call Deepgram Aura-2 via its standard (non-streaming) synthesis
    endpoint. Input: the `verbalize` node's text output (unchanged). Output:
    one audio buffer (same downstream contract with the `speak` node).
- **`.env.example`** — add `DEEPGRAM_API_KEY`. Keep `OPENAI_API_KEY` (still
  used by `gpt-4o-mini`).
- **`requirements.txt`** — add the Deepgram Python SDK. Keep the OpenAI SDK.
- **Fuzzy-match merchant-name layer** in `voice.py` — no code change required
  now; leave a `# TODO` noting it was tuned against `whisper-1`'s error
  patterns and needs retuning against Nova-3 post-review (see below).

## Explicitly not doing

- Not using Deepgram Flux. Flux's headline feature is model-integrated turn
  detection, which is for continuous/always-listening use — this build keeps
  push-to-talk, so there's nothing for turn detection to add.
- Not using Deepgram's Voice Agent API. It bundles its own LLM turn, which
  conflicts with this project's core principle: the LLM never produces a
  fact, it only routes to a typed tool and reads the result aloud. Keep
  `gpt-4o-mini` as the sole planner/verbalizer.
- Not using streaming/WebSocket endpoints for STT or TTS. Single-shot only,
  matching v1's exact pattern.
- Not touching `graph.py`, `tools_txn.py`, `tools_card.py`, `card_terms.yaml`,
  or the state schema.

## Build-stage constraint — read this before writing any code

**Do not make any live API calls while building.** That means:
- Do not call Deepgram or OpenAI with a real API key while implementing or
  self-checking this code.
- Do not run `eval.py`.
- If you want to sanity-check your integration, use static analysis, linting,
  dry runs, or mocked/stubbed responses — never a real network call to
  Deepgram or OpenAI.

Testing with real credentials happens only after a human reviews this build.
That is a separate step, not part of your task here.

## Definition of done (pre-review)

- [ ] `voice.py` calls Deepgram's SDK with the correct model names and
      endpoint types (prerecorded STT, standard TTS)
- [ ] Call shape matches v1's `whisper-1`/`tts-1` pattern exactly — one blob
      in / one transcript out, one text in / one buffer out — no
      partial-transcript or streaming code paths anywhere
- [ ] No live API calls were made at any point while building this
- [ ] `.env.example` and `requirements.txt` updated

When you've met all of the above, stop and report the build as ready for
human review. Don't proceed to testing yourself.

## For whoever runs post-review testing (informational — not your task)

- First live Deepgram calls happen here, not before
- Re-run the merchant-name subset of the 55-question gold set against Nova-3;
  compare to the `whisper-1` baseline
- Full 55-question `eval.py` re-run — all v1 hard gates must still pass
- p50/p95 latency comparison vs. v1 baseline (≤4s / ≤7s targets)
- Retune the fuzzy-match layer in `voice.py` if Nova-3's transcription errors
  differ from `whisper-1`'s