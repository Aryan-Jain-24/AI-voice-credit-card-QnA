"""Streamlit UI -- S08 (voice-ui-engineer), restyled under S11 (frontend-redesign).

    [mic] -> listen -> plan -> {query -> verbalize | clarify} -> speak -> [audio out]

Single column, deliberately plain, per all-specs.md S08 /
.claude/agents/voice-ui-engineer.md, with the S11 visual pass layered on top
(all-specs.md S11 / .claude/agents/frontend-redesign.md):

    1. Title + one-line scope explanation.
    2. st.audio_input -- native mic widget, CSS-restyled (see MIC_BUTTON_CSS
       below) into a standalone, floating, round button detached from the
       main input row, colored idle vs. recording. Still the native widget --
       no streamlit-webrtc, no custom component, no interaction-model change.
    3. A progress indicator that names the current stage (Listening /
       Thinking / Answering) as it actually happens, not a cosmetic fake --
       cleared once the turn finishes, leaving no residual box behind.
    4. st.audio(response, autoplay=True) for the spoken answer.
    5. Transcript + answer shown as text, always -- "trust requires seeing
       what it heard."
    6. A sidebar: 5 example questions (one per question shape -- total spend,
       category breakdown, a card-terms lookup, a cross-domain rewards
       question, and one clarify-in-action question), a short "how to use
       this" block, and the dataset summary.

This file does not reimplement any planning/tool/verbalizing/ASR/TTS logic --
everything it calls is already built and gated by graph.py (S05/S06) and
voice.py (S07/S10). The one piece of real orchestration here is `run_turn()`
below, which sequences voice.py's own node functions (listen_node, plan_node,
route, query_node, clarify_node, verbalize_node, speak_node -- the exact
functions voice.build_voice_graph() wires into a single compiled graph) one
at a time so the UI can show real, not simulated, per-stage progress. This
mirrors build_voice_graph()'s shape exactly; it does not change what any node
does, only when the UI is told about it. The sidebar's example-question
buttons reuse the same `run_turn()` with a typed transcript instead of audio
(skipping the "Listening" stage, since there is no audio to transcribe) --
they exercise the same planner/tool/verbalizer path a spoken question would,
so they are honest demos, not decorative labels.

See all-specs.md S08/S11 and .claude/agents/voice-ui-engineer.md /
.claude/agents/frontend-redesign.md.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import streamlit as st
import yaml
from dotenv import load_dotenv

import voice
from data_loader import load_transactions

# ---------------------------------------------------------------------------
# API key -- .env locally (loaded below), Streamlit secrets in deployment.
# Streamlit Cloud's secrets.toml populates st.secrets, NOT the process
# environment, so it has to be copied across explicitly for the OpenAI SDK
# (which reads OPENAI_API_KEY from os.environ) to see it. Never hardcoded,
# never committed -- .streamlit/secrets.toml is git-ignored (see .gitignore)
# and st.secrets simply has nothing in it when no secrets file exists
# locally, which is why this is wrapped defensively.
# ---------------------------------------------------------------------------

load_dotenv()

try:
    if "OPENAI_API_KEY" in st.secrets and st.secrets["OPENAI_API_KEY"]:
        os.environ.setdefault("OPENAI_API_KEY", st.secrets["OPENAI_API_KEY"])
except Exception:
    pass  # no secrets.toml locally -- .env (already loaded) is the source of truth

HAS_API_KEY = bool(os.getenv("OPENAI_API_KEY"))

st.set_page_config(page_title="Voice Q&A over Credit Card Data", page_icon="\U0001F4B3")


# ---------------------------------------------------------------------------
# S11 -- mic control restyle. CSS-only restyle of the native st.audio_input
# widget (per .claude/agents/frontend-redesign.md: confirmed approach is CSS
# via st.markdown(unsafe_allow_html=True) targeting the widget's DOM wrapper
# -- no streamlit-webrtc, no custom component). Detaches the widget from the
# main input row into a persistent, floating bar, centered on the screen,
# and colors it by state:
#   - idle: neutral blue bar, just the record control.
#   - recording: the widget swaps its "Record" button for a "Stop recording"
#     button (aria-label changes) only while actively capturing audio -- that
#     aria-label, not the waveform/timecode (which stay in the DOM after the
#     recording is captured too), is the precise state hook, via :has(), for
#     the active-red color and the "Listening..." label rendered via ::after
#     below the bar. Both disappear the moment recording stops, since the
#     button reverts to "Record" -- no JS needed.
# The output st.audio player (data-testid="stAudio", a plain <audio> element)
# gets the same bar treatment -- same width/radius/background/shadow -- fixed
# directly below the mic bar so the two form one vertically stacked, matching
# pair instead of overlapping.
# The underlying record-on-click-hold-release behavior is untouched; this is
# a restyle, not a reimplementation.
# ---------------------------------------------------------------------------

MIC_BUTTON_CSS = """
<style>
div[data-testid="stAudioInput"],
audio[data-testid="stAudio"] {
    position: fixed;
    left: 50%;
    transform: translateX(-50%);
    z-index: 9999;
    width: min(420px, 80vw);
    border-radius: 14px;
    background-color: #1f6feb;   /* idle: neutral blue */
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.28);
    transition: background-color 0.2s ease, box-shadow 0.2s ease;
}
div[data-testid="stAudioInput"] {
    top: calc(50% - 80px);
    padding: 10px 16px;
}
audio[data-testid="stAudio"] {
    top: calc(50% + 10px);
    padding: 6px 16px;
}
div[data-testid="stAudioInput"] label {
    display: none;
}
div[data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"] {
    background: transparent;
    border: none;
}
div[data-testid="stAudioInput"] svg {
    fill: #ffffff;
}
div[data-testid="stAudioInput"] [data-testid="stAudioInputWaveformTimeCode"] {
    color: #ffffff;
    font-size: 0.7rem;
}
/* recording state -- the "Stop recording" button only exists while a
   recording is actively in progress, so its presence flips the color and
   reveals the "Listening..." label below the bar; both revert the instant
   recording stops (button reverts to "Record") */
div[data-testid="stAudioInput"]:has([aria-label="Stop recording"]) {
    background-color: #e5484d;   /* recording: red */
    box-shadow: 0 4px 22px rgba(229, 72, 77, 0.55);
}
div[data-testid="stAudioInput"]:has([aria-label="Stop recording"])::after {
    content: "Listening...";
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    margin-top: 0.6rem;
    color: #e5484d;
    font-size: 0.9rem;
    font-weight: 600;
    white-space: nowrap;
}
/* transcript/answer (or idle instructions) -- fixed below the output audio
   bar, matching its width, so it never lands behind either bar */
div.st-key-result_area {
    position: fixed;
    top: calc(50% + 70px);
    left: 50%;
    transform: translateX(-50%);
    width: min(420px, 80vw);
    max-height: 30vh;
    overflow-y: auto;
    z-index: 9998;
    text-align: center;
}
@media (max-width: 640px) {
    div[data-testid="stAudioInput"],
    audio[data-testid="stAudio"] {
        width: 90vw;
    }
    div.st-key-result_area {
        top: calc(50% + 60px);
        width: 90vw;
    }
}
</style>
"""


# ---------------------------------------------------------------------------
# Dataset summary -- for the sidebar. Reads the same canonical loader and
# card_terms.yaml every tool reads; never a second, hand-maintained copy of
# these facts.
# ---------------------------------------------------------------------------


@st.cache_data
def get_dataset_summary() -> dict[str, Any]:
    df = load_transactions()
    with open("card_terms.yaml", "r", encoding="utf-8") as f:
        terms = yaml.safe_load(f) or {}
    card = terms.get("card", {})
    return {
        "rows": len(df),
        "start": df["timestamp"].min().date().isoformat(),
        "end": df["timestamp"].max().date().isoformat(),
        "card_name": card.get("name", "this card"),
        "network": card.get("network"),
        "issuer": card.get("issuer"),
    }


# ---------------------------------------------------------------------------
# Example questions -- S11 trims this to exactly 5, one per question shape,
# so the sidebar teaches the scope at a glance instead of listing every
# question family (all-specs.md S11 / .claude/agents/frontend-redesign.md):
#   1. Total spend            2. Category breakdown
#   3. A card-terms lookup    4. A cross-domain rewards-earned question
#   5. A clarify-in-action question (underspecified period -> the bot asks
#      "which month?" instead of guessing)
# ---------------------------------------------------------------------------

EXAMPLE_QUESTIONS: list[str] = [
    "How much did I spend last month?",
    "What'd I blow on food last month?",
    "What's my annual fee?",
    "How many points did I earn last month?",
    "How much did I spend?",
]


# ---------------------------------------------------------------------------
# One turn -- reuses voice.py's own node functions verbatim (see the module
# docstring). `progress` is an st.empty() placeholder whose text is updated
# as each real stage starts, so "Listening... Thinking... Answering" reflects
# actual progress, not a timer -- and it's cleared at the end so no box lingers.
# ---------------------------------------------------------------------------


def run_turn(progress, *, audio_bytes: bytes | None = None, transcript: str | None = None) -> dict:
    state: voice.State = {
        "audio_in": audio_bytes,
        "transcript": transcript or "",
        "tool_call": None,
        "tool_result": None,
        "answer_text": "",
        "audio_out": None,
        "needs_clarification": False,
    }

    if audio_bytes:
        progress.write("Listening...")
        state.update(voice.listen_node(state))

    progress.write("Thinking...")
    state.update(voice.plan_node(state))
    branch = voice.route(state)
    if branch == "query":
        state.update(voice.query_node(state))
        state.update(voice.verbalize_node(state))
    else:
        state.update(voice.clarify_node(state))

    progress.write("Answering...")
    state.update(voice.speak_node(state))

    progress.empty()
    return state


def render_result(result: dict, *, heard_via_mic: bool) -> None:
    """The text/audio panel -- shared by the mic path and the sidebar
    example-question path so both render identically."""
    transcript = result.get("transcript") or ""
    answer_text = result.get("answer_text") or ""
    audio_out = result.get("audio_out")

    label = "What I heard" if heard_via_mic else "Question"
    st.markdown(f"**{label}:** {transcript}")
    st.markdown(f"**Answer:** {answer_text}")

    if audio_out:
        st.audio(audio_out, format="audio/mp3", autoplay=True)


# ---------------------------------------------------------------------------
# Sidebar -- example questions + dataset summary.
# ---------------------------------------------------------------------------

clicked_question: str | None = None

with st.sidebar:
    st.header("How to use this")
    st.caption(
        "Hold the mic button and ask your question. Release when you're "
        "done. One question at a time."
    )

    st.divider()

    st.header("Try asking")
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, key=f"example::{q}", disabled=not HAS_API_KEY, width="stretch"):
            clicked_question = q

    st.divider()
    st.header("Dataset")
    try:
        summary = get_dataset_summary()
        st.write(f"**Card:** {summary['card_name']}")
        if summary.get("network") or summary.get("issuer"):
            st.caption(f"{summary.get('network', '')} · {summary.get('issuer', '')}")
        st.write(f"**Transactions:** {summary['rows']:,} rows")
        st.write(f"**Date range:** {summary['start']} to {summary['end']}")
    except Exception as exc:  # pragma: no cover -- defensive UI only
        st.caption(f"Dataset summary unavailable: {exc}")


# ---------------------------------------------------------------------------
# Main column.
# ---------------------------------------------------------------------------

st.title("Voice Q&A over Credit Card Data")
st.write(
    "Ask a question about one credit card, out loud: what you spent, or what "
    "the card's own fees, rewards, and offers actually say. Every number you "
    "hear is looked up or computed in Python, never guessed by the model."
)

if not HAS_API_KEY:
    st.warning(
        "OPENAI_API_KEY not set. Copy .env.example to .env and add your key "
        "locally, or add it to this app's Streamlit secrets when deployed."
    )

# Placeholder for the transcript/answer (or the idle instructions). Both the
# mic bar and the output audio bar are fixed to the viewport, so normal
# document flow -- regardless of where in the script this is declared or
# filled -- can end up rendered underneath them on short pages. `key=` gives
# this container an addressable "st-key-result_area" CSS class (see
# MIC_BUTTON_CSS below), which fixes it to the viewport too, anchored below
# the output audio bar, so it never lands behind either bar. Streamlit lets a
# container be filled later in the script while still rendering at the
# position/style declared here, so this is populated further down.
result_area = st.container(key="result_area")

st.markdown(MIC_BUTTON_CSS, unsafe_allow_html=True)
audio_value = st.audio_input(
    "Ask a question",
    key="mic_input",
    disabled=not HAS_API_KEY,
    label_visibility="collapsed",
)

if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
    st.session_state["last_result_heard_via_mic"] = True
if "last_audio_hash" not in st.session_state:
    st.session_state["last_audio_hash"] = None

new_audio_bytes: bytes | None = None
if audio_value is not None:
    raw = audio_value.getvalue()
    audio_hash = hashlib.sha256(raw).hexdigest()
    # st.audio_input keeps returning the same recording across unrelated
    # reruns (e.g. a sidebar button click) -- only re-run the (paid, live)
    # pipeline when the actual audio content changes.
    if audio_hash != st.session_state["last_audio_hash"]:
        st.session_state["last_audio_hash"] = audio_hash
        new_audio_bytes = raw

if new_audio_bytes is not None:
    progress = st.empty()
    try:
        result = run_turn(progress, audio_bytes=new_audio_bytes)
    except Exception as exc:
        progress.empty()
        result_area.error(f"Couldn't process that: {exc}")
        result = None
    if result is not None:
        st.session_state["last_result"] = result
        st.session_state["last_result_heard_via_mic"] = True

elif clicked_question is not None:
    progress = st.empty()
    try:
        result = run_turn(progress, transcript=clicked_question)
    except Exception as exc:
        progress.empty()
        result_area.error(f"Couldn't process that: {exc}")
        result = None
    if result is not None:
        st.session_state["last_result"] = result
        st.session_state["last_result_heard_via_mic"] = False

if st.session_state["last_result"] is not None:
    with result_area:
        render_result(
            st.session_state["last_result"],
            heard_via_mic=st.session_state["last_result_heard_via_mic"],
        )
else:
    result_area.caption(
        "Hold the mic bar (center of the screen) to ask a question, or "
        "pick an example from the sidebar."
    )
