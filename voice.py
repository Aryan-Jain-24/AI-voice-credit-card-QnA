"""STT + TTS wrappers, ASR merchant fuzzy-correction, and the voice-wrapped
graph -- S07 (voice-ui-engineer).

    [mic bytes] -> listen -> plan -> query/clarify -> verbalize -> speak -> [mp3 bytes]

The two thin OpenAI wrappers all-specs.md S07 asks for:

    transcribe(audio_bytes: bytes) -> str      whisper-1
    synthesize(text: str) -> bytes             tts-1, voice="nova", mp3

Everything else in this file exists to make transcription trustworthy for
Indian merchant names, which whisper-1 reliably mangles ("Swiggie",
"Zomatoo", "Big Basket", ...). Two independent layers, per the spec ("do
both, not one or the other"):

  1. `transcribe()` passes the full S01 merchant dictionary (`ALL_MERCHANTS`,
     ~50 names) as Whisper's `prompt` parameter -- this *biases* recognition
     toward those spellings before a single token is fuzzy-matched.
  2. `correct_merchants()` is the deterministic fallback for whatever (1)
     still gets wrong. This is NOT optional -- see
     .claude/agents/voice-ui-engineer.md and all-specs.md S07.

--------------------------------------------------------------------------
Fuzzy-matching design notes (read before changing FUZZY_THRESHOLD/scorer)
--------------------------------------------------------------------------
The spec's own worked example -- "Swiggie" -> "Swiggy" -- was used to
empirically validate this, not just assumed:

* Plain `rapidfuzz.fuzz.ratio`/`WRatio` on the RAW strings scores
  "Swiggie" vs "Swiggy" at 76.9, not >=80. Below the spec's stated
  threshold. Space/punctuation normalisation (lowercase, strip non-
  alphanumerics -- "Big Basket" -> "bigbasket") fixes multi-word mangling
  ("Big Basket" -> 100, "Book my show" -> 100) but does not move the
  single-word case: "Swiggie" vs "Swiggy" is still 76.9, and "Netflicks"
  vs "Netflix" is 75.0, after normalisation, under `fuzz.ratio`.
* Switching to a scorer forgiving of short strings (`WRatio`'s partial-
  match component, `partial_ratio`, or `JaroWinkler`) does push those two
  above 80 -- but it also creates real false positives on ordinary
  question words that happen to share letters with a short merchant name:
  measured directly against this repo's own merchant list, "how" ->
  "BookMyShow" scores 90 under `WRatio`, and "number" -> "Uber" (88.9),
  "payment" -> "Paytm" (85.3), "dining" -> "IndiGo" (82.2), "amount" ->
  "Amazon" (82.2), "rate" -> "Airtel" (80.6) all score >=80 under
  `JaroWinkler`. Any of those firing on a real question ("what's my
  dining spend", "compare rate...") would silently corrupt the transcript
  -- a worse failure than not correcting at all.
* The combination actually used below -- normalise, plain `fuzz.ratio`,
  a denylist of in-domain vocabulary (category names, common
  question/finance words) skipped for single-word candidates, and a
  minimum normalised-candidate length of 4 -- keeps the worst false
  positive found across a battery of realistic gold-style questions at
  66.7 ("to last" -> "Ola" in "...this month to last month"), a
  comfortable ~9-10 point margin below the true positives (75.0-100.0).
* `FUZZY_THRESHOLD = 75` (not exactly the spec's "~80") is the direct
  consequence: it is the smallest threshold that still catches the spec's
  own canonical example ("Swiggie" -> "Swiggy" at 76.9) while staying
  comfortably above every false positive actually measured. The spec
  itself flags the number as approximate ("threshold ~80"); this is that
  approximation, tuned against the spec's own test case rather than left
  at a value that would silently fail it.

See all-specs.md S07 and .claude/agents/voice-ui-engineer.md.
"""

from __future__ import annotations

import logging
import re

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph
from openai import OpenAI
from rapidfuzz import fuzz, process

from generate_data import ALL_MERCHANTS
from graph import (
    State,
    clarify_node,
    plan_node,
    query_node,
    route,
    verbalize_node,
)

load_dotenv()

logger = logging.getLogger("voice")
if not logger.handlers:
    # Library-safe default: only attaches a handler if nothing upstream
    # (app.py, pytest, etc.) already configured logging, so raw transcripts
    # always land somewhere -- S07's done-when needs them for S09's WER
    # number -- without double-logging when embedded in a larger app.
    logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# OpenAI client -- lazy singleton, mirrors graph.py's `_get_planner_llm()` /
# `_get_verbalizer_llm()` pattern so importing this module never requires a
# live API key (only calling transcribe()/synthesize() does).
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


STT_MODEL = "whisper-1"
TTS_MODEL = "tts-1"
TTS_VOICE = "nova"

# Whisper's `prompt` param biases decoding toward tokens it contains. Passing
# the whole merchant dictionary up front means a correct spelling is more
# likely straight out of the model, before correct_merchants() ever has to
# intervene -- see all-specs.md S07 ("do both, not one or the other").
_MERCHANT_PROMPT = "Merchants that may be mentioned: " + ", ".join(ALL_MERCHANTS)


def transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Audio bytes -> raw transcript text, via OpenAI whisper-1.

    `filename` is only a format hint for the API (Streamlit's
    `st.audio_input` emits WAV; override it if a caller feeds something
    else, e.g. mp3/webm from a different mic widget).

    Every raw transcript is logged at INFO, unmodified by merchant
    correction -- S07's done-when needs these logs for S09's WER number, so
    do not remove or move this log line into a caller.
    """
    if not audio_bytes:
        raise ValueError("transcribe() got empty audio_bytes")

    client = _get_client()
    response = client.audio.transcriptions.create(
        model=STT_MODEL,
        file=(filename, audio_bytes),
        prompt=_MERCHANT_PROMPT,
    )
    raw_transcript = (getattr(response, "text", None) or str(response)).strip()
    logger.info("RAW_TRANSCRIPT: %s", raw_transcript)
    return raw_transcript


def synthesize(text: str) -> bytes:
    """Text -> mp3 bytes, via OpenAI tts-1, voice="nova"."""
    if not text:
        raise ValueError("synthesize() got empty text")

    client = _get_client()
    response = client.audio.speech.create(
        model=TTS_MODEL,
        voice=TTS_VOICE,
        input=text,
        response_format="mp3",
    )
    return response.content


# ---------------------------------------------------------------------------
# Merchant fuzzy correction -- see the module docstring for how
# FUZZY_THRESHOLD and the scorer were chosen. Not optional; do not stub.
# ---------------------------------------------------------------------------

FUZZY_THRESHOLD = 75

# In-domain vocabulary that must never be treated as a merchant candidate,
# no matter how it scores -- these are ordinary words this bot's own
# questions are full of (see the docstring's "dining" -> "IndiGo",
# "amount" -> "Amazon" measurements). Only applied to single-word windows;
# multi-word merchant names ("Big Basket", "Book my show") are never single
# common words, so they're never at risk of this filter hiding a real
# correction.
_CATEGORY_WORDS = {
    "food", "dining", "groceries", "fuel", "travel", "shopping",
    "entertainment", "utilities", "health", "education", "cash", "advance",
    "advances", "fees", "fee", "interest", "other",
}
_DOMAIN_STOPWORDS = {
    "what", "how", "much", "many", "did", "i", "spend", "spent", "last",
    "this", "next", "month", "months", "week", "weeks", "quarter", "year",
    "years", "today", "yesterday", "category", "categories", "rate",
    "rates", "cap", "caps", "reward", "rewards", "point", "points",
    "earned", "card", "transaction", "transactions", "over", "under",
    "compare", "with", "without", "since", "recently", "lately",
    "question", "answer", "please", "thanks", "yes", "no", "okay", "total",
    "average", "highest", "lowest", "merchant", "merchants", "store",
    "stores", "purchase", "purchases", "refund", "refunds", "charge",
    "charged", "charges", "annual", "balance", "minimum", "payment",
    "payments", "due", "date", "dates", "statement", "cycle", "limit",
    "credit", "debit", "rupees", "dollars", "percent", "tell", "me",
    "about", "my", "spending", "pattern", "history", "recent", "biggest",
    "expense", "smallest", "largest", "count", "number", "amount",
    "value", "price", "cost", "budget", "forecast", "trend", "analysis",
    "group", "type", "kind", "label", "name", "description", "detail",
    "summary", "overview", "you", "can", "want", "know", "we", "go",
    "there", "again", "also", "and", "or", "but", "if", "then", "when",
    "where", "why", "who", "whom", "whose", "which", "weekend", "weekday",
    "daily", "weekly", "monthly", "yearly", "annually", "near", "close",
    "breach", "hit", "reached", "applies", "applied", "schedule", "clause",
    "offer", "offers", "valid", "until", "benefit", "redemption", "redeem",
    "worth", "versus", "vs", "day", "days", "that", "those", "these",
    "was", "were", "is", "are", "am", "be", "been", "being", "do", "does",
    "doing", "has", "have", "had", "will", "would", "should", "could",
    "may", "might", "it", "its", "for", "on", "in", "at", "to", "of", "a",
    "an", "the", "not", "get", "got", "as",
}
_SKIP_SINGLE_WORD = _CATEGORY_WORDS | _DOMAIN_STOPWORDS

_PUNCT_RE = re.compile(r"[^a-z0-9]")


def _normalize(s: str) -> str:
    """Lowercase, strip spaces/punctuation -- "Big Basket" and "BigBasket"
    both collapse to "bigbasket" so multi-word mangling of a one-word
    merchant name (and vice versa) still matches."""
    return _PUNCT_RE.sub("", s.lower())


def _build_merchant_index(merchants: list[str]) -> dict[str, str]:
    """normalized-name -> original-name, deduplicating on the normalized
    form (two merchants normalizing to the same string would be a data bug
    upstream in S01, not something to silently pick between here)."""
    index: dict[str, str] = {}
    for m in merchants:
        index[_normalize(m)] = m
    return index


_MERCHANT_INDEX = _build_merchant_index(ALL_MERCHANTS)
_MERCHANT_NORM_KEYS = list(_MERCHANT_INDEX.keys())


def _find_merchant_corrections(
    text: str, merchant_index: dict[str, str], threshold: int
) -> list[tuple[int, int, str, str, float]]:
    """Two-pass, non-overlapping scan over `text`'s whitespace-split tokens
    for spans that match a merchant name.

    Pass 1 (exact, longest window first): a window that is already exactly
    a merchant name (after normalization) is claimed outright, at 100
    score, with no fuzzy scoring involved. This has to run and claim its
    words *before* pass 2, or an already-correct short merchant name
    ("Swiggy") sitting next to an ordinary word ("at Swiggy") can get
    fuzzy-absorbed into a longer window that scores above threshold purely
    because it *contains* the real match -- silently deleting the extra
    word. (Caught by test_voice.py::test_already_correct_merchant_left_alone.)

    Pass 2 (fuzzy, longest window first): only runs over words pass 1 left
    unclaimed, exactly as before -- this is the real ASR-mangling fallback.

    Returns a list of (start_word_idx, end_word_idx, original_span_text,
    replacement_merchant_name, score) tuples, sorted by start index.
    """
    words = text.split()
    n = len(words)
    used = [False] * n
    spans: list[tuple[int, int, str, str, float]] = []
    norm_keys = list(merchant_index.keys())

    # Pass 1 -- exact (post-normalization) matches, longest window first.
    for window in (3, 2, 1):
        for start in range(0, n - window + 1):
            end = start + window
            if any(used[start:end]):
                continue
            candidate = " ".join(words[start:end])
            norm_candidate = _normalize(candidate)
            replacement = merchant_index.get(norm_candidate)
            if replacement is None:
                continue
            for i in range(start, end):
                used[i] = True
            if replacement != candidate:
                # Same merchant, different casing/spacing -- still worth
                # normalizing (e.g. "big basket" -> "BigBasket") but not
                # worth logging as a "correction" the way a real mangling
                # fix is; record it at score 100 either way.
                spans.append((start, end, candidate, replacement, 100.0))
            # else: already verbatim-correct, nothing to substitute -- but
            # still claimed above so pass 2 can't touch it.

    # Pass 2 -- fuzzy matches on whatever pass 1 left unclaimed.
    for window in (3, 2, 1):
        for start in range(0, n - window + 1):
            end = start + window
            if any(used[start:end]):
                continue
            candidate = " ".join(words[start:end])
            candidate_clean = candidate.strip(".,!?;:\"'").lower()
            if window == 1 and candidate_clean in _SKIP_SINGLE_WORD:
                continue
            norm_candidate = _normalize(candidate)
            if len(norm_candidate) < 4:
                continue  # too short to fuzzy-match safely either way

            match = process.extractOne(norm_candidate, norm_keys, scorer=fuzz.ratio)
            if match is None:
                continue
            matched_norm, score, _ = match
            if score < threshold:
                continue
            replacement = merchant_index[matched_norm]

            spans.append((start, end, candidate, replacement, score))
            for i in range(start, end):
                used[i] = True

    spans.sort(key=lambda s: s[0])
    return spans


def correct_merchants(
    text: str,
    merchants: list[str] | None = None,
    threshold: int = FUZZY_THRESHOLD,
) -> str:
    """Fuzzy-correct mangled merchant names in a transcript against the S01
    merchant dictionary, e.g. "Swiggie" -> "Swiggy". This is the required
    fallback layer described in all-specs.md S07 -- run this on every
    transcript, always, in addition to (not instead of) Whisper's `prompt`
    bias in transcribe().

    `merchants` defaults to `ALL_MERCHANTS` (S01's ~50-name dictionary);
    overridable for tests / a future schema swap.
    """
    if not text:
        return text

    merchant_index = (
        _build_merchant_index(merchants) if merchants is not None else _MERCHANT_INDEX
    )
    words = text.split()
    spans = _find_merchant_corrections(text, merchant_index, threshold)
    if not spans:
        return text

    out_words = list(words)
    for start, end, original, replacement, score in sorted(
        spans, key=lambda s: s[0], reverse=True
    ):
        out_words[start:end] = [replacement]
        logger.info(
            "MERCHANT_CORRECTION: %r -> %r (score=%.1f)", original, replacement, score
        )

    return " ".join(out_words)


# ---------------------------------------------------------------------------
# Graph extension -- S07: "Extend the graph: add `listen` at entry, `speak`
# before `END`."
#
# This builds a SECOND compiled graph (`voice_graph`) out of the exact same
# node functions graph.py's own text-only `graph`/`app`/`run_pipeline` use
# (`plan_node`, `route`, `query_node`, `clarify_node`, `verbalize_node`,
# imported unmodified above) -- it does not touch graph.py's `build_graph()`
# or its module-level `graph`/`app` objects. That keeps eval.py scoring the
# exact same fast, audio-free pipeline it already gates green on (S05/S06),
# per CLAUDE.md's hard rule not to build voice on top of an unproven text
# pipeline, and not to make evals slower or dependent on tts-1/whisper-1
# credits.
# ---------------------------------------------------------------------------


def listen_node(state: State) -> dict:
    """Entry node for the voice graph. audio_in -> transcript, via
    transcribe() then correct_merchants(). No-op passthrough when audio_in
    is absent, so the same node function is safe to reuse in a text-only
    test of this graph (state's existing `transcript` is left as-is)."""
    audio_in = state.get("audio_in")
    if not audio_in:
        return {}
    raw_transcript = transcribe(audio_in)
    corrected = correct_merchants(raw_transcript)
    return {"transcript": corrected}


def speak_node(state: State) -> dict:
    """Node placed just before END in the voice graph. answer_text ->
    audio_out, via synthesize(). Both verbalize_node and clarify_node
    always set answer_text, but this stays defensive rather than crashing
    the turn on an empty string."""
    text = (state.get("answer_text") or "").strip()
    if not text:
        return {"audio_out": None}
    return {"audio_out": synthesize(text)}


def build_voice_graph():
    """listen -> plan -> {query, clarify} -> verbalize/clarify -> speak -> END.

    Same shape as graph.py's build_graph(), with `listen` prepended at the
    entry point and `speak` inserted before every path to END (both the
    verbalize path and the clarify/refuse path -- a clarifying question or
    refusal needs to be heard too, not just an answer).
    """
    g = StateGraph(State)
    g.add_node("listen", listen_node)
    g.add_node("plan", plan_node)
    g.add_node("query", query_node)
    g.add_node("verbalize", verbalize_node)
    g.add_node("clarify", clarify_node)
    g.add_node("speak", speak_node)
    g.set_entry_point("listen")
    g.add_edge("listen", "plan")
    g.add_conditional_edges("plan", route, {"query": "query", "clarify": "clarify"})
    g.add_edge("query", "verbalize")
    g.add_edge("verbalize", "speak")
    g.add_edge("clarify", "speak")
    g.add_edge("speak", END)
    return g.compile()


voice_graph = build_voice_graph()


def run_voice_pipeline(audio_bytes: bytes) -> dict:
    """The audio-in/audio-out entry point for S08's app.py: mic bytes in,
    the full resulting state dict out (transcript, tool_call, tool_result,
    answer_text, audio_out -- everything the "how it got this answer"
    expander and the transcript/answer text panel need)."""
    initial_state: State = {
        "audio_in": audio_bytes,
        "transcript": "",
        "tool_call": None,
        "tool_result": None,
        "answer_text": "",
        "audio_out": None,
        "needs_clarification": False,
    }
    return voice_graph.invoke(initial_state)
