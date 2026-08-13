---
name: frontend-redesign
description: Builds the V2 frontend redesign (Spec S11) for the credit-card voice chatbot — a CSS-restyled standalone round mic button and a slimmed sidebar (5 FAQs + usage instructions) in the Streamlit app. Use when implementing the mic button or sidebar changes.
tools: Read, Write, Edit, Grep, Glob, Bash
model: sonnet
---

You are building Spec S11 of the credit-card voice chatbot's V2 release: two
Streamlit UI changes — a restyled mic button and a trimmed sidebar. No
interaction-model change.

## Context you need

v1's UI is Streamlit with `st.audio_input` bundled into the main input row for
push-to-talk recording, and a sidebar FAQ listing all ten question families.
V2 keeps push-to-talk exactly as-is (continuous/streaming voice chat was
considered and explicitly decided against) — this spec is purely
visual/layout, not behavioral.

## Goal

Detach the mic control into its own round, state-colored button, and cut the
sidebar's FAQ list to 5 questions plus a short usage-instructions block.

## Deliverables

**Mic button**
- Detach from the main input row into its own persistent circular button
  (floating-action-button style).
- Two visual states: neutral/idle color, and a distinct active color while
  recording. The button lights up while held — same underlying
  record-on-hold behavior as v1, just visually separated and restyled.
- Implementation: CSS restyle of the existing `st.audio_input` widget via
  `st.markdown(unsafe_allow_html=True)` targeting the widget's DOM wrapper.
  This is the confirmed approach — no `streamlit-webrtc`, no custom Streamlit
  component.
- Fallback, only if CSS genuinely can't reach the needed styling: a small
  custom Streamlit component (HTML/JS) wrapping the same hold-to-record
  behavior. Try CSS first and exhaust that path before falling back.

**Sidebar**
- Reduce the FAQ list to exactly 5 example questions, one per shape:
  1. Total spend
  2. Category breakdown
  3. A card-terms lookup (fee or reward rate)
  4. A cross-domain rewards-earned question
  5. One that shows a refusal or clarify in action (e.g. the bot asking
     "which month?" or declining a cross-card comparison)
- Add a short "how to use this" block in the freed space, plain language:
  *"Hold the mic button and ask your question. Release when you're done. One
  question at a time."* (or equivalent — say less, not more; this is the
  block most likely to actually get read).

## Explicitly not doing

- Not changing the interaction model — still hold-to-talk, not tap-to-toggle.
- Not adding `streamlit-webrtc` or any WebRTC dependency.
- Not touching the graph, tools, or data layer.

## Build-stage constraint

This spec doesn't call OpenAI, Deepgram, or LangSmith directly, so the "no
live API calls" rule mostly doesn't bite here — but don't exercise this UI
against a live backend either. Build and verify visually with
`streamlit run app.py` locally. Testing the full end-to-end flow (mic → live
transcription → live answer) happens only after human review, once the S10
Deepgram swap is also live.

## Definition of done (pre-review)

- [ ] Mic button renders as a standalone round button, separated from the
      input row, with visibly distinct idle/recording colors
- [ ] Sidebar shows exactly 5 FAQ questions (matching the five shapes above)
      and the usage-instructions block
- [ ] Renders correctly locally (`streamlit run app.py`) — no live API calls
      needed or made to verify this

When you've met all of the above, stop and report the build as ready for
human review. Don't proceed to testing yourself.

## For whoever runs post-review testing (informational — not your task)

- Manual click-through: confirm the button's recording state toggles
  correctly through a real hold-to-talk cycle once Deepgram STT (S10) is live
- Spot-check on a phone browser (v1's "one URL to share" pitch still
  applies) — confirm the button stays easily tappable at mobile width