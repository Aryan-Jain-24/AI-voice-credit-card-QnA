"""Pytest suite for voice.py's merchant fuzzy-correction (S07) and the
Deepgram STT/TTS call shape (S10).

Scope: `correct_merchants()` and its helpers are unit-testable without any
API key/network call. `transcribe()`/`synthesize()` are thin wrappers around
Deepgram Nova-3/Aura-2 (swapped from whisper-1/tts-1 under S10) -- their
empty-input validation is tested directly here, and their actual API call
shape (model name, `keyterm`/`encoding` params, response parsing) is tested
with the Deepgram client mocked out, so this suite still runs in CI/offline
without secrets and without ever touching the network. A live smoke test
against real Deepgram credentials happens separately post-review (see
.claude/agents/stt-tts-deepgram-swap.md), not here.

Every expected merchant name below is copied by hand from `ALL_MERCHANTS`
(generate_data.py) -- these are not round-tripped through the function under
test to produce their own expectation.

Run with:  pytest test_voice.py -v
"""

from __future__ import annotations

import voice
from generate_data import ALL_MERCHANTS


# ---------------------------------------------------------------------------
# True positives -- the spec's own worked example, plus common Whisper-style
# mangling patterns (dropped/added letters, split compound names).
# ---------------------------------------------------------------------------


def test_swiggie_corrects_to_swiggy():
    # The spec's own canonical example (all-specs.md S07).
    out = voice.correct_merchants("I ordered dinner from Swiggie last night")
    assert "Swiggy" in out
    assert "Swiggie" not in out


def test_zomatoo_corrects_to_zomato():
    out = voice.correct_merchants("I paid Zomatoo for lunch")
    assert "Zomato" in out


def test_split_compound_name_big_basket():
    out = voice.correct_merchants("I bought groceries from Big Basket")
    assert "BigBasket" in out


def test_split_compound_name_book_my_show():
    out = voice.correct_merchants("I booked tickets on Book my show")
    assert "BookMyShow" in out


def test_air_tel_corrects_to_airtel():
    out = voice.correct_merchants("my Air tel bill was high")
    assert "Airtel" in out


def test_mac_donalds_corrects_to_mcdonalds():
    out = voice.correct_merchants("I ate at Mac Donalds")
    assert "McDonald's" in out


def test_already_correct_merchant_left_alone():
    out = voice.correct_merchants("how much did I spend at Swiggy last month")
    assert "Swiggy" in out
    # Nothing else in the sentence should have been touched.
    assert out == "how much did I spend at Swiggy last month"


def test_no_merchant_present_returns_text_unchanged():
    text = "how much did I spend last month"
    assert voice.correct_merchants(text) == text


def test_empty_string_returns_empty_string():
    assert voice.correct_merchants("") == ""


# ---------------------------------------------------------------------------
# False-positive guards -- ordinary question/domain vocabulary that shares
# letters with a short merchant name must NOT be swapped. These are the
# concrete cases the module docstring's tuning notes measured directly
# (fuzz.ratio-normalized scores of 60-80 against this repo's own merchant
# list before the stopword denylist was added).
# ---------------------------------------------------------------------------


def test_dining_is_not_corrected_to_indigo():
    out = voice.correct_merchants("what is my dining spend this quarter")
    assert "IndiGo" not in out
    assert "dining" in out


def test_amount_is_not_corrected_to_amazon():
    out = voice.correct_merchants("what amount did I pay in fees")
    assert "Amazon" not in out


def test_payment_is_not_corrected_to_paytm():
    out = voice.correct_merchants("what is the payment due date on my statement")
    assert "Paytm" not in out


def test_rate_is_not_corrected_to_airtel():
    out = voice.correct_merchants("tell me the fuel rate for my card")
    assert "Airtel" not in out


def test_compare_is_not_corrected_to_croma():
    out = voice.correct_merchants("compare my spending this month to last month")
    assert "Croma" not in out


def test_number_is_not_corrected_to_uber():
    out = voice.correct_merchants("what is the number of transactions I made")
    assert "Uber" not in out


def test_realistic_gold_style_sentences_untouched_by_false_positives():
    sentences = [
        "how much did I spend on food last month",
        "how many reward points did I earn last year",
        "is there a limit on cash advances",
        "what percent is charged as interest",
        "how much is the annual fee for this card",
        "did I get charged a late payment fee",
    ]
    for s in sentences:
        out = voice.correct_merchants(s)
        # None of these mention a merchant -- correction should be a no-op.
        assert out == s, f"unexpected change: {s!r} -> {out!r}"


# ---------------------------------------------------------------------------
# Nova-3 `keyterm` bias -- ALL_MERCHANTS must actually be in the keyterm list
# sent to the API (the other half of "do both, not one or the other"). S10
# swapped this from a single joined `_MERCHANT_PROMPT` string (whisper-1's
# `prompt=`) to a `_MERCHANT_KEYTERMS` list (Nova-3's `keyterm=`).
# ---------------------------------------------------------------------------


def test_merchant_keyterms_contains_every_merchant_name():
    for merchant in ALL_MERCHANTS:
        assert merchant in voice._MERCHANT_KEYTERMS


def test_merchant_index_covers_all_merchants():
    assert len(voice._MERCHANT_INDEX) == len(set(ALL_MERCHANTS))
    assert set(voice._MERCHANT_INDEX.values()) == set(ALL_MERCHANTS)


# ---------------------------------------------------------------------------
# transcribe()/synthesize() input validation -- the parts that don't need a
# live API call.
# ---------------------------------------------------------------------------


def test_transcribe_rejects_empty_audio():
    import pytest

    with pytest.raises(ValueError):
        voice.transcribe(b"")


def test_synthesize_rejects_empty_text():
    import pytest

    with pytest.raises(ValueError):
        voice.synthesize("")


# ---------------------------------------------------------------------------
# S10 -- Deepgram call shape, verified with the Deepgram client mocked out
# (no network, no API key). These pin down the two things S10's done-when
# gate cares about: correct model names/endpoint types, and v1's exact
# single-shot call shape (one blob in / one transcript out, one text in /
# one buffer out -- no streaming/partial-result path).
# ---------------------------------------------------------------------------


class _FakeAlternative:
    def __init__(self, transcript):
        self.transcript = transcript


class _FakeChannel:
    def __init__(self, transcript):
        self.alternatives = [_FakeAlternative(transcript)]


class _FakeResults:
    def __init__(self, transcript):
        self.channels = [_FakeChannel(transcript)]


class _FakeListenResponse:
    def __init__(self, transcript):
        self.results = _FakeResults(transcript)


def test_transcribe_calls_nova3_prerecorded_with_full_blob_and_keyterms(monkeypatch):
    captured = {}

    class _FakeMedia:
        def transcribe_file(self, **kwargs):
            captured.update(kwargs)
            return _FakeListenResponse("swiggy order arrived")

    class _FakeListenV1:
        media = _FakeMedia()

    class _FakeListen:
        v1 = _FakeListenV1()

    class _FakeClient:
        listen = _FakeListen()

    monkeypatch.setattr(voice, "_get_client", lambda: _FakeClient())

    out = voice.transcribe(b"some-wav-bytes")

    assert out == "swiggy order arrived"
    # Model is Nova-3, not whisper-1; the whole blob goes in one call (no
    # chunking/streaming); keyterm bias carries every known merchant name,
    # the direct replacement for whisper-1's `prompt=`.
    assert captured["model"] == "nova-3"
    assert captured["request"] == b"some-wav-bytes"
    assert set(captured["keyterm"]) == set(ALL_MERCHANTS)


def test_transcribe_runs_merchant_correction_on_nova3_output(monkeypatch):
    class _FakeMedia:
        def transcribe_file(self, **kwargs):
            return _FakeListenResponse("I ordered dinner from Swiggie last night")

    class _FakeListenV1:
        media = _FakeMedia()

    class _FakeListen:
        v1 = _FakeListenV1()

    class _FakeClient:
        listen = _FakeListen()

    monkeypatch.setattr(voice, "_get_client", lambda: _FakeClient())

    # transcribe() itself only returns the raw transcript (correction is a
    # separate step run by listen_node) -- assert the raw pass-through here,
    # and exercise correct_merchants() on Nova-3-shaped output directly.
    raw = voice.transcribe(b"some-wav-bytes")
    assert raw == "I ordered dinner from Swiggie last night"
    corrected = voice.correct_merchants(raw)
    assert "Swiggy" in corrected


def test_synthesize_calls_aura2_and_returns_joined_bytes(monkeypatch):
    captured = {}

    class _FakeAudio:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return iter([b"chunk1", b"chunk2", b"chunk3"])

    class _FakeSpeakV1:
        audio = _FakeAudio()

    class _FakeSpeak:
        v1 = _FakeSpeakV1()

    class _FakeClient:
        speak = _FakeSpeak()

    monkeypatch.setattr(voice, "_get_client", lambda: _FakeClient())

    out = voice.synthesize("Your total spend was 500 rupees.")

    # Model is an Aura-2 voice, not tts-1; mp3 requested explicitly to match
    # app.py's `st.audio(audio_out, format="audio/mp3")` contract; the
    # (possibly chunked) response iterator is fully drained into one buffer
    # before returning -- single-shot, not streamed to the caller.
    assert captured["model"] == voice.TTS_MODEL
    assert captured["model"].startswith("aura-2-")
    assert captured["text"] == "Your total spend was 500 rupees."
    assert captured["encoding"] == "mp3"
    assert out == b"chunk1chunk2chunk3"
    assert isinstance(out, bytes)


# ---------------------------------------------------------------------------
# Graph wiring -- the voice_graph must not mutate graph.py's own text-only
# graph/app/run_pipeline (the objects eval.py scores).
# ---------------------------------------------------------------------------


def test_voice_graph_is_a_separate_object_from_text_graph():
    import graph as graph_module

    assert voice.voice_graph is not graph_module.graph
    assert voice.voice_graph is not graph_module.app
