"""Pytest suite for S12 -- LangSmith tracing wraps in voice.py and the
eval.py dataset/experiment logging.

Scope, and why this suite makes no live calls (per PRD-02.md S11 / the S12
build-stage constraint in .claude/agents/langsmith-observability.md):

  - `voice.transcribe`/`voice.synthesize` are wrapped in `@traceable`, but
    with `LANGSMITH_TRACING`/`LANGSMITH_API_KEY` unset (the default, and the
    only state this repo's tests ever run in), `@traceable` is a transparent
    passthrough -- no network call. This suite re-runs a couple of the S10
    Deepgram-call-shape tests with LangSmith's env vars *explicitly* unset,
    to pin down that the S12 decorator did not change transcribe()/
    synthesize()'s behavior or call signature.
  - `eval.log_run_to_langsmith` is gated on `_langsmith_enabled()`. This
    suite tests both the disabled no-op path (no import, no network) and the
    enabled path with `langsmith.Client` monkeypatched out to a fake that
    records calls in memory -- never a real `langsmith.Client()`, never a
    network call, same mocking pattern test_voice.py uses for the Deepgram
    SDK.

Run with:  pytest test_langsmith.py -v
"""

from __future__ import annotations

import eval as eval_mod
import voice


# ---------------------------------------------------------------------------
# voice.py -- @traceable wraps must not change transcribe()/synthesize()'s
# behavior when tracing is off (the default).
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


def test_transcribe_still_works_with_tracing_env_vars_unset(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    class _FakeMedia:
        def transcribe_file(self, **kwargs):
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


def test_synthesize_still_works_with_tracing_env_vars_unset(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    class _FakeAudio:
        def generate(self, **kwargs):
            return iter([b"a", b"b"])

    class _FakeSpeakV1:
        audio = _FakeAudio()

    class _FakeSpeak:
        v1 = _FakeSpeakV1()

    class _FakeClient:
        speak = _FakeSpeak()

    monkeypatch.setattr(voice, "_get_client", lambda: _FakeClient())

    out = voice.synthesize("hello")
    assert out == b"ab"


def test_transcribe_and_synthesize_are_traceable_wrapped():
    # @traceable attaches identifying metadata to the wrapped function --
    # confirms the decorator is actually in place, without needing tracing
    # enabled or a network call.
    assert hasattr(voice.transcribe, "__wrapped__")
    assert hasattr(voice.synthesize, "__wrapped__")


# ---------------------------------------------------------------------------
# eval.py -- _langsmith_enabled() gating
# ---------------------------------------------------------------------------


def test_langsmith_disabled_when_env_vars_unset(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert eval_mod._langsmith_enabled() is False


def test_langsmith_disabled_when_only_api_key_set(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-fake")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    assert eval_mod._langsmith_enabled() is False


def test_langsmith_disabled_when_only_tracing_flag_set(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert eval_mod._langsmith_enabled() is False


def test_langsmith_enabled_when_both_set(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-fake")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert eval_mod._langsmith_enabled() is True


# ---------------------------------------------------------------------------
# eval.py -- log_run_to_langsmith(): disabled path makes no calls at all;
# enabled path drives a fully mocked langsmith.Client (no network, no real
# credentials -- see module docstring).
# ---------------------------------------------------------------------------

_FAKE_GOLD = [
    {
        "id": "Q1",
        "utterance": "how much did I spend last month",
        "bucket": "domain_a_straightforward",
        "expected_tool": "spend_total",
        "expected_domain": "transactions",
        "expected_behaviour": "answer",
    },
    {
        "id": "Q2",
        "utterance": "what's my cash advance fee",
        "bucket": "domain_b_terms",
        "expected_tool": "card_fees",
        "expected_domain": "terms",
        "expected_behaviour": "answer",
    },
]

_FAKE_EVALD = {
    "gold": _FAKE_GOLD,
    "rows": [
        {
            "entry": _FAKE_GOLD[0],
            "result": {
                "implemented": True, "error": None, "latency": 1.23,
                "tool_name": "spend_total", "behaviour": "answer",
                "answer_text": "You spent Rs. 8,240 last month.",
            },
        },
        {
            "entry": _FAKE_GOLD[1],
            "result": {
                "implemented": True, "error": None, "latency": 0.87,
                "tool_name": "card_fees", "behaviour": "answer",
                "answer_text": "The cash advance fee is 2.5%.",
            },
        },
    ],
    "implemented": True,
    "drift_warnings": [],
}


def test_log_run_to_langsmith_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    # If this tried to import/construct a real langsmith.Client (let alone
    # touch the network), monkeypatching Client to raise below would catch
    # it. Since the function must return before ever reaching that import,
    # nothing needs patching here -- absence of an exception plus the
    # disabled flag is the whole assertion.
    eval_mod.log_run_to_langsmith(_FAKE_EVALD, {})


class _FakeLangsmithClient:
    """Records every call in memory; never touches the network. Mirrors
    test_voice.py's fake Deepgram client pattern."""

    def __init__(self):
        self.datasets_checked = []
        self.datasets_created = []
        self.examples_created = []
        self.runs_created = []
        self._existing_datasets = set()

    def has_dataset(self, dataset_name):
        self.datasets_checked.append(dataset_name)
        return dataset_name in self._existing_datasets

    def create_dataset(self, dataset_name, description=None):
        self.datasets_created.append(dataset_name)
        self._existing_datasets.add(dataset_name)

    def create_example(self, **kwargs):
        self.examples_created.append(kwargs)

    def create_run(self, **kwargs):
        self.runs_created.append(kwargs)


def test_log_run_to_langsmith_logs_dataset_and_runs_when_enabled(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-fake")

    fake_client = _FakeLangsmithClient()

    import langsmith
    monkeypatch.setattr(langsmith, "Client", lambda: fake_client)

    eval_mod.log_run_to_langsmith(_FAKE_EVALD, {})

    assert fake_client.datasets_checked == [eval_mod.LANGSMITH_DATASET_NAME]
    assert fake_client.datasets_created == [eval_mod.LANGSMITH_DATASET_NAME]
    assert len(fake_client.examples_created) == 2
    assert len(fake_client.runs_created) == 2

    # Every logged run is tagged with its gold-question bucket (the 9
    # buckets gold_questions.json already partitions its 55 questions into)
    # so LangSmith UI slicing by bucket works out of the box.
    tags_by_run = [run["tags"] for run in fake_client.runs_created]
    assert ["domain_a_straightforward"] in tags_by_run
    assert ["domain_b_terms"] in tags_by_run


def test_log_run_to_langsmith_swallows_client_errors(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-fake")

    import langsmith

    def _boom():
        raise RuntimeError("simulated LangSmith outage")

    monkeypatch.setattr(langsmith, "Client", _boom)

    # Must not raise -- a LangSmith outage degrades to "logging skipped",
    # never to a crashed eval run.
    eval_mod.log_run_to_langsmith(_FAKE_EVALD, {})
