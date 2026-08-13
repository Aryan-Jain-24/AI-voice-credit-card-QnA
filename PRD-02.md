# PRD — Voice Q&A over Credit Card Data — V2

**Owner:** Aryan Jain
**Requested by:** Chandresh Pancholi
**Version:** v2 (builds on v1, shipped and gates-green as of `d61bbed`)
**Status:** Ready to build — all open decisions confirmed in §10

---

## 0. Naming correction — confirmed

The original ask named four changes, one of which needed a small correction:
*"swap STT and TTS LLM from chat gpt 4o mini to deepgram."* In the v1 build,
`gpt-4o-mini` is the **planner + verbalizer** (text-only, tool-calling and
sentence generation) — it never touches audio. The actual audio models are
**`whisper-1`** (STT) and **`tts-1`** (TTS), both OpenAI. **Confirmed:** the
swap is `whisper-1` and `tts-1` → Deepgram's equivalents, with `gpt-4o-mini`
staying as the planner/verbalizer, unchanged. The rest of this document builds
around that.

---

## 1. What v2 changes and why

Three workstreams, after a fourth was reconsidered and dropped. Layered on top
of the v1 build without touching its core principle (§3 of the v1 PRD: *the LLM
never produces a fact, it only routes to one and reads it aloud*).

| # | Change | One-line reason |
|---|---|---|
| 1 | LangSmith observability | v1 debugging relied on ad hoc terminal output and re-running `eval.py`; no persistent, per-node trace history existed |
| 2 | Frontend: standalone round mic button + slimmer sidebar | Current mic control is bundled into the input row; sidebar FAQ is longer than a first-time user will read |
| 3 | STT/TTS swap: OpenAI → Deepgram | Better transcription accuracy (notably on Indian merchant names, v1 PRD §10's known risk) and natural-sounding TTS, without needing to change the interaction model |

**Continuous voice chat with streaming — considered, decided against.** The
original ask included replacing push-to-talk with an always-listening,
interruptible session. On review: **push-to-talk stays.** v1 PRD §9 already made
this call deliberately once — *"~4s round trip instead of ~1.5s... chosen
deliberately: the streaming version doubles the moving parts and makes
correctness harder to verify"* — and v2 keeps that reasoning rather than
reopening it. The STT/TTS vendor swap in item 3 stands on its own; it doesn't
require continuous listening to be worth doing. See §4.4 for the fuller note on
what was considered and why it's not happening in this pass.

---

## 2. Non-goals — carried forward, unchanged

Everything in v1 PRD §4 still holds, unchanged: no cross-card comparison, no
multi-card, no auth/multi-user, no real PII, no mobile native app, no financial
advice. An earlier draft of this PRD reversed one line from v1 — that reversal is
now undone. Push-to-talk stays, matching v1 PRD §9's original call:

> v1: *"Push-to-talk, not streaming... Chosen deliberately... It is a swap of the
> `listen` and `speak` nodes, not a rewrite."*

Still true in v2 — noted here so a future pass doesn't have to re-litigate it.
Scope otherwise unchanged: the ten question families, the two-domain split, the
refuse/clarify/admit-a-gap behaviors.

---

## 3. What's changing vs. staying the same

| Component | v1 | v2 | Status |
|---|---|---|---|
| STT | `whisper-1`, single-shot (full blob → one transcript) | Deepgram **Nova-3**, single-shot (same call pattern, new vendor) | Changed (vendor only) |
| TTS | `tts-1`, single-shot (full text → one mp3) | Deepgram **Aura-2**, single-shot (same call pattern, new vendor) | Changed (vendor only) |
| Planner + verbalizer | `gpt-4o-mini` | `gpt-4o-mini`, unchanged | Same — see §0 |
| Interaction model | push-to-talk (hold button, release to send) | push-to-talk, unchanged — see §1 | Same |
| Mic control | bundled into `st.audio_input` in the main input row | standalone round button, colored by state (idle / recording) | Changed |
| Sidebar | full FAQ list (all ten question families) | 5 example questions + a short "how to use this" block | Changed |
| Observability | none — debugging via console output and `eval.py` reruns | LangSmith tracing on every graph run, plus `eval.py` runs logged as LangSmith experiments | New |
| Graph shape, tools, data layer, YAML terms file | as shipped | unchanged | Same |
| Eval harness (55 gold questions, hard gates) | as shipped | unchanged pass/fail bar; re-run required post-swap (see §7) | Same, re-verified |

---

## 4. New / changed feature specs

### 4.1 LangSmith observability

**Why:** the three-round planner fix (Q31/Q10/Q50, documented in `state.md`) was
debugged with print statements and repeated `eval.py` runs — there was no way to
open a specific bad run afterward and see exactly what the planner saw at each
node. LangSmith fixes that going forward.

**What:**
- Enable tracing with three environment variables — `LANGSMITH_TRACING=true`,
  `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` — no code changes needed for the parts
  of the graph that already use LangChain/LangGraph primitives; LangGraph nests
  traces automatically per node (`listen`, `plan`, `query`, `verbalize`,
  `speak`) — the node set itself is unchanged from v1, since the STT/TTS swap
  only changes what each node calls internally, not the graph's shape.
- Any custom, non-LangChain call in the pipeline (e.g. a raw Deepgram SDK call)
  needs an explicit `@traceable` wrap to show up in the same trace tree — audit
  `voice.py` once the Deepgram swap lands and wrap what isn't auto-traced.
- Wire `eval.py`'s 55-question run into a LangSmith **dataset + experiment**
  instead of only writing `EVAL_REPORT.md` — gives a queryable run history across
  passes (this pass vs. last pass) instead of only the latest snapshot, and lets
  the existing 9 eval buckets be sliced by latency/accuracy in the LangSmith UI.
- Non-goal: LangSmith does not replace the hard-gate checks in `eval.py`/pytest.
  It's an added observability layer, not a new gate — the pass/fail bar in v1 PRD
  §8 stays the actual ship gate.
- Cost/dependency note: this adds a third external vendor relationship (alongside
  OpenAI and, post-swap, Deepgram) and a network call per traced run. A LangSmith
  outage must degrade to "tracing silently stops," never to "the voice pipeline
  breaks" — worth a specific test case.

### 4.2 Frontend changes

**a) Mic button**
- Detached from the chat/text input row into its own persistent circular button
  (floating-action-button style), colored by state: neutral/idle vs. an active
  color while recording. Interaction stays **hold-to-talk**, matching v1 (§1) —
  this is a styling change, not a UX change; the button lights up while held,
  same behavior as today, just visually separated and restyled.
- Build note, confirmed (§10): `st.audio_input`'s built-in widget has limited CSS
  hooks, but a CSS restyle via `st.markdown(unsafe_allow_html=True)` targeting
  the widget wrapper is the chosen approach — no custom component and no
  `streamlit-webrtc` needed for this button. If the native widget's DOM proves
  too restrictive to hit the round/colored look this way, fall back to a small
  custom Streamlit component wrapping the same hold-to-record behavior, but CSS
  is the first and expected path.

**b) Sidebar**
- Cut the FAQ list down to **5** example questions — one per major shape rather
  than one per family: a total-spend question, a category breakdown, a card-terms
  lookup (fee or reward rate), a cross-domain rewards-earned question, and one
  that demonstrates a refusal or clarify (e.g. shows the bot asking "which month?"
  or declining a cross-card comparison) so a first-time user sees the guardrails,
  not just the happy path.
- Replace the freed space with a short, first-time-user "how to use this" block —
  plain language, matching the push-to-talk interaction: *"Hold the mic button
  and ask your question. Release when you're done. One question at a time."*
  This is the block most likely to actually get read, so it should say less, not
  more.

### 4.3 STT/TTS swap to Deepgram

- **STT — `whisper-1` → Deepgram Nova-3, prerecorded endpoint:** same call shape
  as v1 — one full audio blob in (on button release), one transcript back.
  Nova-3 rather than Deepgram's newer Flux model, since Flux's headline feature
  (model-integrated end-of-turn/turn detection) is built for continuous,
  always-listening use, which §4.4 explicitly isn't building — the button
  release already marks the end of the utterance, the same way it did against
  `whisper-1`, so there's nothing for turn detection to add here.
- **TTS — `tts-1` → Deepgram Aura-2, standard synthesis endpoint:** one full
  text in, one audio buffer back out — the closest drop-in replacement for
  `tts-1`'s call pattern. (Aura-2 confirmed over Deepgram's newer "Flux TTS" —
  Flux TTS's advantage is mainly in continuous/streaming conversations, which
  isn't what this pass builds — §10.)
- **Not adopting Deepgram's Voice Agent API** (the fully bundled STT+LLM+TTS
  product) — it comes with its own LLM turn in the loop, which doesn't fit v1's
  core principle of a constrained, typed-tool-only planner (v1 PRD §3). Using
  Nova-3 and Aura-2 directly, with the existing LangGraph planner/verbalizer in
  between, keeps that principle intact.
- **Indian merchant-name accuracy — re-verify, don't assume:** v1 PRD §10 flagged
  ASR mangling names like "Swiggy," mitigated by fuzzy-matching transcript tokens
  in `voice.py`. That fuzzy-match logic was tuned against `whisper-1`'s specific
  mistakes. Re-run the merchant-name subset of the 55-question gold set against
  Nova-3 before trusting it blind — Deepgram's own benchmarks claim it was
  preferred over Whisper in head-to-head testing, but that's Deepgram's number,
  not this project's eval, and the fuzzy-match layer may need retuning either way.
- **`gpt-4o-mini` unchanged** for planner + verbalizer — confirmed §0.
- Not in scope for this pass, noted only for completeness: both Nova-3 and
  Aura-2 also support streaming (partial transcripts / chunked audio). Nothing
  in this PRD depends on that — it's available if a future pass revisits
  continuous mode (§4.4), not something this version needs.

### 4.4 Continuous voice chat — considered, decided against

- **What was considered:** an always-listening session — tap once, speak
  freely, the bot's answer can be interrupted mid-sentence (barge-in) — built on
  Deepgram Flux for model-integrated end-of-turn detection and streaming Aura-2
  for lower time-to-first-audio.
- **Why it's not happening in this pass:** keeps push-to-talk's explicit
  end-of-utterance signal (the button release) instead of trading it for
  endpointing-threshold tuning, barge-in false-positive risk from background
  noise, and a genuinely harder failure surface to verify — the same tradeoff v1
  PRD §9 named explicitly the first time this was deferred.
- **Not foreclosed permanently:** v1 PRD §9's original framing still applies —
  *"It is a swap of the `listen` and `speak` nodes, not a rewrite"* — so this
  stays revisitable later without disturbing the STT/TTS vendor choice made in
  §4.3.

---

## 5. State (LangGraph) — unchanged

No new fields needed. Swapping STT/TTS vendors changes what each node calls
internally, not the graph's shape — v1 PRD §7.2's existing state schema still
covers it as-is.

---

## 6. Updated stack

| Layer | v1 | v2 |
|---|---|---|
| Orchestration | LangGraph `StateGraph` | unchanged |
| UI | Streamlit + `st.audio_input` | Streamlit + `st.audio_input`, CSS-restyled (§4.2a) |
| STT | OpenAI `whisper-1` | Deepgram Nova-3, prerecorded/single-shot |
| Planner + verbalizer | `gpt-4o-mini` | unchanged — confirmed §0 |
| TTS | OpenAI `tts-1` | Deepgram Aura-2, single-shot |
| Observability | none | LangSmith (tracing + eval-run history) |
| Data | pandas + CSV + YAML | unchanged |
| Deploy | Streamlit Community Cloud | unchanged |

**Resolved:** Path A (`streamlit-webrtc`) had been confirmed earlier specifically
to support continuous duplex audio. With push-to-talk kept, that justification no
longer applied, and it's now settled (§10): no `streamlit-webrtc`, no custom
component — a CSS restyle of `st.audio_input` covers the round colored mic
button. One fewer dependency than the earlier draft carried.

---

## 7. Success metrics for v2

**Regression gate first:** every hard gate from v1 PRD §8 must still pass, re-run
in full against the swapped pipeline — the STT/TTS vendor swap touches
`listen`/`speak` directly and could silently move the numbers (merchant-name
recognition, latency) even though `plan`/`query`/`verbalize` and the interaction
model are untouched. Treat a full 55-question `eval.py` re-run as a ship-blocking
gate, not a nice-to-have. Per §11, this re-run — like all live API calls — happens
only after human review of the build, not during it.

**New v2-specific metrics:**

| Metric | Target | Why |
|---|---|---|
| Merchant-name recognition, Nova-3 vs. `whisper-1` baseline | at least parity with v1's ≥90% target | Regression check per §4.3, not just "Deepgram says it's better" |
| p50 / p95 round-trip latency, new vendor pair vs. v1 baseline | at least parity with v1 PRD §8 targets (≤4s / ≤7s) | A vendor swap alone shouldn't regress latency even without streaming |
| LangSmith trace coverage | 100% of graph runs traced | New observability-completeness check |

---

## 8. Risks — new, on top of v1's carried-forward list

v1 PRD §10's risks (ASR merchant-name mangling, relative-date misresolution, stray
verbalizer arithmetic, cold start, model reciting a term from memory, fee-schedule
ambiguity, reward-cap logic, scope creep) all still apply unchanged. New for v2:

| Risk | Likelihood | Mitigation |
|---|---|---|
| STT/TTS vendor swap regresses accuracy or latency versus the tuned `whisper-1`/`tts-1` baseline | Medium | §7's regression gate — full 55-question re-run and a direct latency comparison before shipping, not just a spot check |
| Two vendor relationships now split cost/reliability (OpenAI for planner/verbalizer, Deepgram for STT/TTS) | Low–Medium | Nothing to fix now, just worth naming — an outage on either vendor now affects a different half of the pipeline |
| LangSmith as a third external dependency | Low | Must degrade to "tracing off," never to "pipeline broken" — see §4.1 |

---

## 9. Non-goals for v2 (explicit)

Unchanged from v1 §4, with no reversals in this version: no cross-card
comparison, no multi-card, no auth, no real PII, no mobile native app, no
financial advice — and, per §1/§4.4, streaming/interruption stays out of scope
for this pass too.

---

## 10. Open questions — confirm before build starts

**Confirmed:**
- **STT/TTS naming** (§0): the swap is `whisper-1` + `tts-1` → Deepgram, and
  `gpt-4o-mini` (the planner/verbalizer) stays as-is.
- **Push-to-talk vs. continuous** (§1/§4.4): keeping push-to-talk. Continuous
  voice chat is not in scope for this pass.
- **Mic button implementation** (§4.2a/§6): CSS restyle of `st.audio_input`, not
  `streamlit-webrtc`. Superseded Path A now that continuous audio isn't being
  built.
- **TTS model** (§4.3): Aura-2, not Flux TTS.

**Still open:** none — all four decisions above are confirmed. Nothing further
needed before build starts.

---

## 11. Build-stage testing policy

**No live API calls while the product is being built.** Nothing in the build
phase — code for the STT/TTS swap, the LangSmith wiring, the frontend rework —
calls OpenAI, Deepgram, or LangSmith with real credentials. That includes
`eval.py` runs: the 55-question regression gate in §7 is a live-API activity and
is explicitly deferred by this policy, not run as part of building.

**Testing starts only after a human reviews the build.** Once Aryan has reviewed
the assembled v2 build, live testing begins — first real Deepgram/OpenAI calls,
first LangSmith traces, the full `eval.py` regression run. That review is the
gate between "built" and "tested," not a formality folded into a build-day task.

This changes what "done" means for each build-stage day in §12: a day's gate is
about the code being complete and internally consistent, not about a live run
passing — live runs don't happen until after the review checkpoint.

---

## 12. Rough timeline

| Stage | Deliverable | Gate |
|---|---|---|
| Day 1 | Deepgram Nova-3 (STT) + Aura-2 (TTS) wired into `voice.py`, replacing `whisper-1`/`tts-1`, push-to-talk UX unchanged | Code complete, call shape matches v1's `whisper-1`/`tts-1` pattern — no live calls made, per §11 |
| Day 2 | Frontend: round mic button via CSS restyle, sidebar rework (§4.2); LangSmith wiring added (§4.1) | UI renders correctly locally; LangSmith env vars and `@traceable` wraps in place but not yet exercised — no live calls made, per §11 |
| Day 3 | Full v2 build assembled end-to-end | Build ready for human review — nothing yet tested against live credentials |
| **— human review checkpoint —** | Aryan reviews the assembled build | Sign-off to proceed to testing |
| Day 4 (post-review) | First live testing pass: full 55-question `eval.py` re-run, latency comparison vs. v1 baseline, `EVAL_REPORT.md` updated, redeploy to Streamlit Community Cloud | All hard gates green on v2, same bar as v1 |

Noticeably shorter than the earlier continuous-chat draft — dropping that
workstream removes most of the integration risk (barge-in, session state,
duplex streaming) that drove the original four-day estimate. Still a rough pass,
not a committed schedule.