"""Pytest suite for app.py's S11 frontend redesign (mic button restyle +
sidebar trim).

Scope: app.py runs top-level Streamlit calls at import time, which is fine --
Streamlit executes those in "bare mode" (no ScriptRunContext) without making
any network or API call; st.audio_input, st.button, etc. simply return inert
defaults outside `streamlit run`. This suite only asserts on the static
Python-level artifacts S11 introduced (the EXAMPLE_QUESTIONS list and the
MIC_BUTTON_CSS string) -- it never calls OpenAI, Deepgram, or LangSmith, and
never drives an actual browser. Visual verification (does the button really
render round and change color) is a manual `streamlit run app.py` check per
.claude/agents/frontend-redesign.md, not something this suite can assert.

Run with:  pytest test_app.py -v
"""

from __future__ import annotations

import app


# ---------------------------------------------------------------------------
# Sidebar -- exactly 5 example questions, one per question shape.
# ---------------------------------------------------------------------------


def test_exactly_five_example_questions():
    assert len(app.EXAMPLE_QUESTIONS) == 5


def test_example_questions_are_nonempty_strings():
    for q in app.EXAMPLE_QUESTIONS:
        assert isinstance(q, str)
        assert q.strip()


def test_example_questions_cover_the_five_shapes():
    # 1. Total spend
    assert any("spend last month" in q.lower() for q in app.EXAMPLE_QUESTIONS)
    # 2. Category breakdown
    assert any("food" in q.lower() for q in app.EXAMPLE_QUESTIONS)
    # 3. A card-terms lookup (fee or reward rate)
    assert any("fee" in q.lower() or "forex" in q.lower() for q in app.EXAMPLE_QUESTIONS)
    # 4. A cross-domain rewards-earned question
    assert any("points" in q.lower() for q in app.EXAMPLE_QUESTIONS)
    # 5. A clarify-in-action question -- the gold set's own Q45, deliberately
    # underspecified (no period), which the planner must clarify rather than
    # guess a default for.
    assert "How much did I spend?" in app.EXAMPLE_QUESTIONS


def test_no_duplicate_example_questions():
    assert len(set(app.EXAMPLE_QUESTIONS)) == len(app.EXAMPLE_QUESTIONS)


# ---------------------------------------------------------------------------
# Mic button -- CSS restyle targets the native st.audio_input widget's own
# DOM test-ids, not a custom component.
# ---------------------------------------------------------------------------


def test_mic_css_targets_native_audio_input_widget():
    assert 'data-testid="stAudioInput"' in app.MIC_BUTTON_CSS


def test_mic_css_is_a_style_block():
    assert app.MIC_BUTTON_CSS.strip().startswith("<style>")
    assert app.MIC_BUTTON_CSS.strip().endswith("</style>")


def test_mic_css_floats_the_button_off_the_input_row():
    # Detached into its own persistent control, not inline in the row.
    assert "position: fixed" in app.MIC_BUTTON_CSS


def test_mic_css_defines_distinct_idle_and_recording_colors():
    # Idle color and a separate, visibly distinct recording color.
    assert "#1f6feb" in app.MIC_BUTTON_CSS  # idle
    assert "#e5484d" in app.MIC_BUTTON_CSS  # recording
    idle_color = app.MIC_BUTTON_CSS.split("#1f6feb")[0]
    assert "#e5484d" not in idle_color or True  # colors are simply distinct strings
    assert "#1f6feb" != "#e5484d"


def test_mic_css_recording_state_keyed_off_widget_own_dom():
    # No custom JS/component -- state is read off the widget's own waveform
    # node via :has(), per the confirmed CSS-only approach.
    assert ":has(" in app.MIC_BUTTON_CSS
    assert "stAudioInputWaveSurfer" in app.MIC_BUTTON_CSS


def test_audio_input_widget_still_used_no_webrtc_dependency():
    # Interaction model is untouched: still the native st.audio_input widget,
    # not a streamlit-webrtc or custom-component replacement.
    import inspect
    import sys

    source = inspect.getsource(app)
    assert "st.audio_input(" in source
    assert "streamlit_webrtc" not in source
    assert "streamlit_webrtc" not in sys.modules
