"""Streamlit UI -- S08 (voice-ui-engineer).

    [mic] -> listen -> plan -> {query -> verbalize | clarify} -> speak -> [audio out]

Single column, deliberately plain, per all-specs.md S08 /
.claude/agents/voice-ui-engineer.md:

    1. Title + one-line scope explanation.
    2. st.audio_input -- native mic widget.
    3. A spinner/status that names the current stage (Listening / Thinking /
       Answering) as it actually happens, not a cosmetic fake.
    4. st.audio(response, autoplay=True) for the spoken answer.
    5. Transcript + answer shown as text, always -- "trust requires seeing
       what it heard."
    6. An expander ("How it got this answer") showing the tool name, its
       args, and the raw result dict -- the thing that makes "the LLM never
       does arithmetic" visible instead of merely claimed.
    7. A sidebar: example questions as buttons, grouped "Your spending" /
       "Your card" / "Your rewards", plus a dataset summary.

This file does not reimplement any planning/tool/verbalizing/ASR/TTS logic --
everything it calls is already built and gated by graph.py (S05/S06) and
voice.py (S07). The one piece of real orchestration here is `run_turn()`
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

See all-specs.md S08 and .claude/agents/voice-ui-engineer.md.
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
# Example questions -- grouped so the grouping itself teaches the scope
# (transactions vs. terms vs. the cross-domain reward calc), per S08.
# ---------------------------------------------------------------------------

EXAMPLE_QUESTIONS: dict[str, list[str]] = {
    "Your spending": [
        "How much did I spend last month?",
        "What'd I blow on food last month?",
        "Who are my top merchants last month?",
    ],
    "Your card": [
        "What's my annual fee?",
        "What's the forex markup on this card?",
        "What's the late payment fee if I owe 10,000 rupees?",
    ],
    "Your rewards": [
        "How many points did I earn last month?",
        "How many dining points did I earn last month?",
        "Did I hit my dining rewards cap in October 2025?",
    ],
}


# ---------------------------------------------------------------------------
# One turn -- reuses voice.py's own node functions verbatim (see the module
# docstring). `status` is an st.status(...) context manager whose label is
# updated as each real stage starts, so "Listening... Thinking... Answering"
# reflects actual progress, not a timer.
# ---------------------------------------------------------------------------


def run_turn(status, *, audio_bytes: bytes | None = None, transcript: str | None = None) -> dict:
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
        status.update(label="Listening...")
        state.update(voice.listen_node(state))

    status.update(label="Thinking...")
    state.update(voice.plan_node(state))
    branch = voice.route(state)
    if branch == "query":
        state.update(voice.query_node(state))
        state.update(voice.verbalize_node(state))
    else:
        state.update(voice.clarify_node(state))

    status.update(label="Answering...")
    state.update(voice.speak_node(state))

    return state


def render_result(result: dict, *, heard_via_mic: bool) -> None:
    """The text/audio/expander panel -- shared by the mic path and the
    sidebar example-question path so both are equally auditable."""
    transcript = result.get("transcript") or ""
    answer_text = result.get("answer_text") or ""
    audio_out = result.get("audio_out")
    tool_call = result.get("tool_call") or {}
    tool_result = result.get("tool_result")

    label = "What I heard" if heard_via_mic else "Question"
    st.markdown(f"**{label}:** {transcript}")
    st.markdown(f"**Answer:** {answer_text}")

    if audio_out:
        st.audio(audio_out, format="audio/mp3", autoplay=True)

    with st.expander("How it got this answer"):
        st.markdown(f"**Tool called:** `{tool_call.get('name') or '(none)'}`")
        st.markdown("**Arguments:**")
        st.json(tool_call.get("args") or {})
        st.markdown("**Raw result:**")
        st.json(tool_result if tool_result is not None else {})


# ---------------------------------------------------------------------------
# Sidebar -- example questions + dataset summary.
# ---------------------------------------------------------------------------

clicked_question: str | None = None

with st.sidebar:
    st.header("Try asking")
    for group, questions in EXAMPLE_QUESTIONS.items():
        st.subheader(group)
        for q in questions:
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

audio_value = st.audio_input("Ask a question", disabled=not HAS_API_KEY)

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
    with st.status("Listening...", expanded=False) as status:
        try:
            result = run_turn(status, audio_bytes=new_audio_bytes)
            status.update(label="Done", state="complete")
        except Exception as exc:
            status.update(label="Something went wrong", state="error")
            st.error(f"Couldn't process that: {exc}")
            result = None
    if result is not None:
        st.session_state["last_result"] = result
        st.session_state["last_result_heard_via_mic"] = True

elif clicked_question is not None:
    with st.status("Thinking...", expanded=False) as status:
        try:
            result = run_turn(status, transcript=clicked_question)
            status.update(label="Done", state="complete")
        except Exception as exc:
            status.update(label="Something went wrong", state="error")
            st.error(f"Couldn't process that: {exc}")
            result = None
    if result is not None:
        st.session_state["last_result"] = result
        st.session_state["last_result_heard_via_mic"] = False

if st.session_state["last_result"] is not None:
    render_result(
        st.session_state["last_result"],
        heard_via_mic=st.session_state["last_result_heard_via_mic"],
    )
else:
    st.caption("Record a question above, or pick an example from the sidebar.")
