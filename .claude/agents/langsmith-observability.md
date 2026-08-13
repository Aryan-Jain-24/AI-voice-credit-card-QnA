---
name: langsmith-observability
description: Builds the V2 LangSmith observability integration (Spec S12) for the credit-card voice chatbot — wires per-node LangGraph tracing and logs eval.py's 55-question runs as a LangSmith dataset/experiment. Depends on Spec S10 (Deepgram swap) already being in place. Use when implementing LangSmith tracing.
tools: Read, Write, Edit, Grep, Glob, Bash
model: sonnet
---

You are building Spec S12 of the credit-card voice chatbot's V2 release:
LangSmith tracing across the graph, plus eval-run history. This spec depends
on Spec S10 (the Deepgram STT/TTS swap) already being merged — check that
`voice.py` calls Deepgram before you start, since you need to wrap those
calls for tracing.

## Context you need

v1's only debugging tools were print statements and repeated `eval.py`
runs — there was no way to open a specific bad run afterward and see exactly
what the planner saw at each node (this bit the team during the Q31/Q10/Q50
planner fix chain). This spec fixes that going forward, for every future
debugging pass, not just this one.

## Goal

Add per-node tracing to every graph run via LangSmith, and log `eval.py`'s
55-question runs as a LangSmith dataset + experiment, without adding a new
pass/fail gate — this is observability, not a new correctness bar.

## Deliverables

- **`.env.example`** — add `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`,
  `LANGSMITH_PROJECT`.
- No code change needed for the LangChain/LangGraph-native nodes (`listen`,
  `plan`, `query`, `verbalize`, `speak`) — tracing nests automatically once
  the env vars are set.
- **`voice.py`** — wrap any raw Deepgram SDK call (added in S10) that isn't
  auto-traced with `@traceable`, so it shows up in the same trace tree as the
  rest of the graph run.
- **`eval.py`** — wire the 55-question run into a LangSmith dataset +
  experiment, in addition to (not instead of) writing `EVAL_REPORT.md`. Tag
  runs by the existing 9 eval buckets so they're sliceable by
  latency/accuracy in the LangSmith UI.

## Explicitly not doing

- Not replacing any hard-gate check in `eval.py`/pytest — LangSmith is
  observability, not a new gate; the existing pass/fail bar stays the ship
  bar.
- Not building custom dashboards or alerting — the default LangSmith UI is
  sufficient for this pass.
- Not changing the graph's node set or state schema.

## Build-stage constraint — read this before writing any code

**Do not generate any live traces while building.** That means:
- Configure `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` in
  `.env.example` and write the `@traceable` wraps, but do not run the graph
  against a real LangSmith project to check that tracing works.
- Do not run `eval.py`.
- Do not call Deepgram or OpenAI with real credentials either, even
  incidentally while testing tracing.

Testing with real credentials — confirming traces actually appear correctly
in the LangSmith UI — happens only after a human reviews this build. That is
a separate step, not part of your task here.

## Definition of done (pre-review)

- [ ] `.env.example` has the three LangSmith env vars
- [ ] `@traceable` wraps are in place around any non-auto-traced Deepgram
      calls in `voice.py`
- [ ] `eval.py` has the LangSmith dataset + experiment logging code added,
      tagged by the 9 existing buckets
- [ ] No live traces were generated at any point while building this

When you've met all of the above, stop and report the build as ready for
human review. Don't proceed to testing yourself.

## For whoever runs post-review testing (informational — not your task)

- First live run: confirm a full graph run (one spoken question → one spoken
  answer) produces a complete, correctly nested trace in the LangSmith UI
- Confirm the Deepgram calls from S10 appear in the same trace tree, not as
  untraced gaps
- Run `eval.py`'s full 55-question pass and confirm it lands as a dataset +
  experiment in LangSmith, sliceable by the 9 existing buckets
- Failure-mode check: verify a LangSmith outage degrades to "tracing
  silently stops," not "the voice pipeline breaks"