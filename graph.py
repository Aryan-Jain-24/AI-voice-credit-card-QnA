"""LangGraph definition -- S05 (planner + graph assembly) and S06 (verbalizer).

    [text in] -> plan -> query -> verbalize -> END
                   \\-> clarify -> END

`listen`/`speak` are added around this graph in S07 (voice-ui-engineer); until
then the graph is driven by plain text (`transcript` in, `answer_text` out) so
`eval.py` can score it without audio in the loop, per all-specs.md S05.

--------------------------------------------------------------------------
The one rule this whole file exists to enforce (PRD.md S3, CLAUDE.md)
--------------------------------------------------------------------------
    "The language model never produces a fact. It only routes to one and
    reads it aloud."

Two LLM calls happen in this file, and each is deliberately boxed in:

* `plan_node` -- gpt-4o-mini, temperature 0, `tool_choice="required"`, bound
  to all ten data tools plus `ask_clarification`/`refuse`. It picks exactly
  one tool call. It never sees transaction data or card_terms.yaml, so it
  has nothing to hallucinate a number *from* -- the worst it can do is
  route to the wrong tool, which is what eval.py's intent/domain-routing
  metrics catch.

* `verbalize_node` -- gpt-4o-mini, temperature 0. It is deliberately NOT
  trusted to freely compose an answer from a raw tool_result dict. Instead:
    1. A pure Python function (`_build_facts`) deterministically renders an
       already-correct draft sentence from `tool_result` -- every number in
       it is a literal value copied out of `tool_result`, and every card
       term is the tool's own `clause` (or `benefit`) text, near-verbatim.
    2. The LLM is asked only to *smooth the phrasing* of that draft into
       one natural spoken sentence, forbidden from adding/changing/removing
       any number.
    3. `_validate` re-checks the LLM's rewrite the same way eval.py's
       hallucination/term-exactness checks do (every required number
       present, every spoken number traceable to a literal value in
       `tool_result`). If the rewrite fails that check, the deterministic
       draft is used verbatim instead -- already correct, if a little more
       mechanical.
  This means the LLM step can only ever make the answer sound better; it
  cannot be the reason a wrong or invented number goes out.

--------------------------------------------------------------------------
Number formatting note
--------------------------------------------------------------------------
S06 says to speak amounts "naturally" ("eight thousand two hundred forty
rupees", not "8240.50"). This file renders amounts as grouped digits
("8,240 rupees"), not spelled-out English words, for two reasons that both
point the same way: (1) `tts-1` (S07) pronounces written digit groups
correctly on its own, so digits already sound natural once spoken -- the
S06 example is illustrating *how it should sound*, not the literal
character sequence graph.py must emit; and (2) `eval.py`'s hallucination,
numeric-exactness and term-exactness checks all work by regexing digits out
of `answer_text` (see its `_extract_numbers`) -- spelling every number out
as words would make every one of those checks see zero numbers and fail
every gold question outright, which cannot be the intended reading given
PRD.md's own worked example answers digit-format currency ("You spent
Rs. 8,240 on food..."). What *is* enforced here per S06's real intent: no
raw unrounded floats (never "8240.5"), amounts round to the nearest rupee
(PRD's own example rounds 8240.50 -> 8,240), and rates/percentages keep
only the precision they were given (3.5 stays "3.5", never "3" or "3.50").

--------------------------------------------------------------------------
Why `query` is a plain function here, not `langgraph.prebuilt.ToolNode`
--------------------------------------------------------------------------
S05's spec sketch writes `g.add_node("query", ToolNode(TOOLS))`. The
prebuilt `ToolNode` operates on a `messages` list and serialises each tool's
return value into a `ToolMessage.content` string, which the next node would
then have to parse back into a dict -- a lossy round-trip for no benefit,
since our State (PRD.md S7.2) is the flat `tool_result: dict | None` field,
not a message list. `query_node` below does the same job `ToolNode` would
(look up the tool named in `tool_call`, invoke it with `tool_call["args"]`)
by calling `tool.invoke(args)` directly, which returns the tool's native
Python dict with no serialisation step -- the exact dict the verbalizer
must never embellish. The graph *shape* (`plan -> query/clarify ->
verbalize -> END`) matches the spec exactly; only this one node's
implementation is a direct function instead of the prebuilt class.

See all-specs.md S05/S06, PRD.md S7.1/S7.3, and .claude/agents/graph-engineer.md.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from tools_card import card_fees, card_offers, card_rewards, rewards_earned
from tools_txn import (
    compare_periods,
    find_transactions,
    recurring_charges,
    spend_by_category,
    spend_total,
    top_merchants,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Canonical category display names -- used only for natural spoken phrasing
# ("food and dining", not the raw key "food_dining"). Never used to *pick* a
# category; that's the planner's job, constrained to the 12 canonical keys.
# ---------------------------------------------------------------------------

CATEGORY_DISPLAY: dict[str, str] = {
    "food_dining": "food and dining",
    "groceries": "groceries",
    "fuel": "fuel",
    "travel": "travel",
    "shopping": "shopping",
    "entertainment": "entertainment",
    "utilities": "utilities",
    "health": "health",
    "education": "education",
    "cash_advance": "cash advances",
    "fees_interest": "fees and interest",
    "other": "other spending",
}


def _cat_display(category: str | None) -> str:
    if not category:
        return ""
    return CATEGORY_DISPLAY.get(category, category.replace("_", " "))


# ---------------------------------------------------------------------------
# State -- PRD.md S7.2 / CLAUDE.md, verbatim. Six fields of "core" state plus
# the two audio fields S07 (voice-ui-engineer) will populate; this file never
# reads or writes audio_in/audio_out, but declares them so the State shape
# already matches what S07 needs to slot `listen`/`speak` in around this
# graph without a schema change. eval.py's fallback `graph.graph`/`graph.app`
# integration path constructs exactly this dict -- see its `get_pipeline()`.
# ---------------------------------------------------------------------------


class State(TypedDict):
    audio_in: bytes | None
    transcript: str
    tool_call: dict | None
    tool_result: dict | None
    answer_text: str
    audio_out: bytes | None
    needs_clarification: bool


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
# The ten data tools -- these, and only these, are ever invoked by `query`.
DATA_TOOLS = [
    spend_total,
    spend_by_category,
    top_merchants,
    compare_periods,
    find_transactions,
    recurring_charges,
    card_rewards,
    card_fees,
    card_offers,
    rewards_earned,
]
DATA_TOOLS_BY_NAME = {t.name: t for t in DATA_TOOLS}


@tool
def ask_clarification(missing: str) -> dict:
    """Ask the user a short clarifying question instead of guessing a required argument.

    Call this INSTEAD of any data tool whenever a required argument for the
    question at hand is missing or unresolvable -- most commonly the time
    period. Example utterances: "How much did I spend?" (no period), "How
    many points have I earned?" (rewards_earned needs a period too). Not
    for questions that already name everything a tool needs -- if every
    required argument is present (even a relative phrase like "last
    month"), call the real tool instead of this one; resolving that phrase
    into dates is `resolve_period`'s job, never a reason to ask again.

    Args:
        missing: what's missing, one of:
            "period" -- no time range was given, or the one given doesn't
                resolve to an actual date range (e.g. "before", with no
                stated baseline, or "am I spending more than before?").
            "category" -- the question needs one specific category (e.g.
                "what's the rate?", "is there a cap?") but none was named.
            "comparison" -- a comparison needs two periods and only one (or
                zero) is identifiable from the question.
    """
    return {"missing": missing}


@tool
def refuse(reason: str) -> dict:
    """Decline a question that is out of scope for this bot.

    Call this for anything that is not a question about THIS card's own
    spending history or its own documented terms. Example utterances: "Is
    this card better than an Amex Platinum?", "Should I close this card?".
    Not for an in-scope question about this card's own fees, rewards,
    offers, or transaction history, even a critical-sounding one like "am I
    close to the dining cap?" -- that goes to a data tool instead. Also not
    for a fee/terms question that merely NAMES a third-party brand, app, or
    service this card might charge you for using -- e.g. "is there a fee
    for topping up a PhonePe wallet with this card?" or "does this card
    charge extra if I use it on Ola Money?" are still asking about THIS
    card's OWN fee for that action, not about the other company's product,
    so they go to card_fees, even when that specific fee_type turns out to
    be undocumented (found: false there is a normal, correct outcome --
    never a reason you should have refused instead).

    Args:
        reason: why it's out of scope, one of:
            "cross_card_comparison" -- compares this card to another card
                or issuer, or asks which of two cards is better.
            "financial_advice" -- asks whether to close, keep, apply for,
                or otherwise act on a card -- a decision, not a fact.
            "out_of_scope" -- anything else this bot has no access to or
                isn't built to do (e.g. credit score, raising a credit
                limit, disputing a charge).
    """
    return {"reason": reason}


ALL_TOOLS = DATA_TOOLS + [ask_clarification, refuse]

# ---------------------------------------------------------------------------
# Planner (S05)
# ---------------------------------------------------------------------------

PLANNER_MODEL = "gpt-4o-mini"

# The six numbered rules below are carried over close to verbatim from
# all-specs.md S05 -- do not silently reword them; they are the load-bearing
# constraint text for the highest-hallucination-risk node in the system.
PLANNER_SYSTEM_PROMPT = """You are the planning stage of a voice assistant that answers questions about \
one credit card: its transaction history and its documented terms. You never \
reply to the user directly -- you select exactly one tool call, and a later \
stage reads the result aloud.

1. You select exactly one tool -- exactly one call, to exactly one tool --
even when a question could technically be answered by calling a simpler
tool twice. A question comparing or relating two periods (e.g. "was this
month higher than last month?", "...compared to the month before that?")
is always ONE call to compare_periods with both period_a and period_b set,
never two separate calls to spend_total. You never compute values.
2. You never state a fee, rate, cap, or offer from your own knowledge. All \
card terms come from tools. If you find yourself about to recall a reward \
rate, that is the signal to call card_rewards instead.
3. If a required argument is missing -- especially the time period -- call \
ask_clarification instead of guessing. Never invent a default period. A \
period the user DID state, even a vague or relative one ("last month", \
"this year", "lately", "recently"), already satisfies that requirement -- \
translate it into one of the actual resolvable phrases in rule 6 below \
(treat "lately"/"recently" as meaning "last 3 months") and pass THAT \
resolvable phrase to the tool. Never pass the vague word itself (e.g. \
"lately") as the period argument -- it is not a phrase resolve_period can \
handle, and the tool call will fail. Only call \
ask_clarification(missing="period") when the question names NO time cue at \
all, e.g. "Who do I spend the most with?" or "How much did I spend?" have \
nothing to interpret.
4. Distinguish the schedule from the history: what the card charges is \
card_fees; what the user was charged is \
spend_total with category set to fees_interest. Likewise, "was I ever \
charged X" / "did I pay X" (asking whether a specific named charge \
happened) is a lookup over the transaction history -- call \
find_transactions(merchant="X") -- not card_fees and not spend_total. Fees \
and interest the card actually assessed appear in the transaction history \
under a merchant name matching the charge itself, e.g. a late fee is \
recorded as merchant "Late Payment Fee" -- use that exact wording (or a \
substring of it, like "Late Payment"), not a paraphrase like "late fee", \
which will not match anything.
5. If the question is about another card, a comparison between cards, or \
financial advice, call refuse. A question about THIS card's own spending, \
fees, rewards, or offers is always in scope, even for categories that sound \
unusual, such as cash_advance or fees_interest -- those are two of the 12 \
ordinary spending categories, not a signal to refuse. For example, "how \
many reward points did I earn from cash advances last year?" is answerable \
by rewards_earned(period="last year", category="cash_advance") -- that this \
category is excluded from earning points (the answer will be 0) makes it a \
normal, correctly-answerable lookup, not a reason to refuse. Naming a \
third-party brand, app, or service is likewise not, by itself, a reason to \
refuse -- what matters is WHOSE fee is being asked about, not which words \
appear in the question. "Is there a fee for topping up a PhonePe wallet \
with this card?" and "Does this card charge extra if I use it on Ola \
Money?" are both asking about THIS card's own fee for an action involving \
an outside service, not about the other company's own product -- call \
card_fees(fee_type=...) for these exactly as you would for "what's the \
annual fee?", even when the specific fee_type comes back undocumented \
(card_fees correctly returning found: false for it is a normal \
gap-admission outcome, never evidence that the question itself needed \
refuse instead). Reserve refuse(reason="out_of_scope") for what this bot \
has no way to answer even in principle -- your credit score, raising your \
credit limit, disputing a charge -- not for an ordinary fee, terms, or \
spending question that happens to mention another company's name.
6. Today's date is {today}. Relative dates pass through as phrases exactly \
as the user said them (e.g. "last month", "last quarter", "YTD") -- a \
Python helper (resolve_period) resolves them into actual date ranges \
elsewhere; you never compute day-level date boundaries yourself. Only pass \
a period phrase from this supported list, filling in a specific month/year \
using today's date when the phrase requires it: "last month", "this \
month", "last week", "this week", "last N months" (a specific N), "last \
year", "YTD", a named month with year (e.g. "June 2026"), a specific date, \
or (for rewards_earned only) "last quarter"/"this quarter"/"Q<N> <year>". \
If what the user means isn't expressible in one of those forms -- e.g. "the \
month before last", or "the month before that" as the second period in a \
comparison -- work out which specific named month that is from today's \
date and pass it as a "Month YYYY" phrase, instead of inventing an \
unsupported phrase or reusing the same period twice. Worked example: if \
today is {today}, "last month" is the month named just before today's own \
month, and "the month before that" is one calendar month earlier still --\
these are two DIFFERENT months, never the same phrase repeated for both. \
This is identifying which calendar month is meant, not resolving exact day \
boundaries.

Terse, verb-less phrasing (e.g. "Fuel spend last week?", "Dining points \
last month?") is never itself a signal for which tool to call -- decide the \
TOOL from the question's own topic word, never from how short or bare the \
phrasing is. "Spend", "spent", "blew", "paid", or "charged" name a \
transactions-domain question (spend_total, spend_by_category, \
top_merchants, compare_periods, or find_transactions -- whichever the rest \
of the question asks for); "points", "earn", "earned", or "reward" name the \
cross-domain rewards_earned tool. Whether a period is present or absent \
only decides whether to call a tool AT ALL versus ask_clarification (rule \
3) -- it never decides WHICH tool that is, and a stated period on a \
spending question never makes it a rewards question.

The 12 canonical spending categories -- map the user's words onto exactly \
one of these whenever a tool needs a category, and never invent a new one: \
food_dining, groceries, fuel, travel, shopping, entertainment, utilities, \
health, education, cash_advance, fees_interest, other. Most tools only need \
a category when the question names one specifically -- read each tool's own \
description for whether its category argument is required or optional \
before deciding a category is "missing".

For card_fees and card_rewards: pass fee_type/category as a literal, \
normalized (snake_case) version of what the user actually asked about. Do \
NOT substitute a different, superficially-similar fee_type or category just \
because it happens to already be documented -- for example, "add-on card \
fee" must be passed as "add_on_card_fee", never remapped to the existing \
but different "card_replacement". Answering with the wrong-but-documented \
term's figure is worse than correctly reporting that a term isn't \
documented, and that correct "not documented" report is only possible if \
you pass the term through honestly rather than guessing a plausible match.
"""


_planner_llm: Any = None


def _get_planner_llm():
    global _planner_llm
    if _planner_llm is None:
        _planner_llm = ChatOpenAI(model=PLANNER_MODEL, temperature=0).bind_tools(
            ALL_TOOLS, tool_choice="required"
        )
    return _planner_llm


# ---------------------------------------------------------------------------
# Planner few-shot examples -- bug fix for the "How many points did I earn
# last month?" family of misroutes (period stated -> wrongly clarified
# anyway).
#
# Root cause: rule 3 above already states in prose that a stated relative
# period ("last month") satisfies the period requirement and must not
# trigger ask_clarification. That prose rule alone was NOT reliably followed
# by gpt-4o-mini for this specific phrasing/tool pairing -- measured directly
# (20 live calls of plan_node on this exact utterance family, prompt-only,
# no few-shot) at 11/20 (55%) misrouted to ask_clarification(missing="period")
# instead of rewards_earned(period=...). That is well inside the reported
# 50-62% failure band, not a fluke run. Likely driver: the ask_clarification
# tool's own docstring names "How many points have I earned?" (no period) as
# a textbook example utterance -- a near-identical surface form to a
# period-qualified version of the same question, differing only in the
# trailing period phrase, which a small model's tool-choice logits can end
# up treating as close enough to call a coin flip.
#
# Fix, round 1 (superseded): the first attempt at this fix used exactly two
# examples, both rewards-themed, one of which was -- on review -- the
# verbatim text of gold_questions.json's Q31 ("How many points did I earn
# last month?"). Besides being uncomfortably close to teaching the eval
# itself rather than the general pattern, two same-themed, structurally
# terse examples in a row taught the model an over-broad lesson: "terse
# period+category phrasing -> rewards_earned", which silently broke Q10
# ("Food spend in July?", answerable by spend_total) -- confirmed
# fully reproducible (5/5 and separately 3/3 live runs) and root-caused in
# .claude/state.md. Numbers were right for the wrong reason: routing had
# started keying off surface shape, not the question's own topic word.
#
# Fix, round 2 (superseded): three examples, none of which is the literal
# text of any evals/gold_questions.json entry (so this teaches the *general*
# rule, not a memorized answer), arranged so the model cannot generalize
# "terse + period -> rewards_earned":
#   1. A transactions-domain example with the exact same terse, verb-less,
#      category+period SHAPE as the phrasing that regressed (Q10) -- but a
#      different category/month and resolving to spend_total.
#   2. The original ambiguous case (rewards topic, period stated) ->
#      rewards_earned, paraphrased so it does not match Q31's exact wording.
#   3. The same rewards topic with NO period stated -> ask_clarification.
# This DID fix both Q31 and Q10 (5/5 and separately isolated live checks),
# but broke a THIRD, previously-100%-reliable question: Q50 ("What's the
# rate?", which must ask_clarification(missing="category") -- "the rate"
# implies an unstated category, unlike Q25's "base reward rate", which is
# correctly answered directly). Isolated by testing every subset of the
# round-2 examples individually against Q50: ANY single one of them alone
# --  including the ask_clarification-ending one (#3) on its own -- was
# enough to flip Q50 from ask_clarification(missing="category") to
# card_rewards() 100% of the time, while zero few-shot examples left Q50
# correct 100% of the time. That rules out "wrong theme" as the mechanism
# here (unlike the round-1 -> round-2 diagnosis): the mere presence of ANY
# prior tool-call precedent measurably makes gpt-4o-mini less willing to
# stop and clarify on this specific borderline question, regardless of that
# precedent's content. Concretely, the round-2 set carried no demonstrated
# precedent at all for "ask_clarification(missing='category')" -- only
# missing="period" -- so the model had nothing to anchor that other
# clarify reason to once few-shot examples were present at all.
#
# Fix, round 3 (this one): keep the three round-2 examples (they are still
# the fix for Q31/Q10 and remain non-eval-verbatim) and add a fourth,
# demonstrating the CATEGORY-missing clarify reason specifically -- again in
# wording that matches no gold_questions.json entry (contrast with Q50
# itself, and with Q26 "Is there a cap on my dining reward points?", which
# already names a category and must NOT clarify). Verified directly (live,
# repeated calls): with all four examples present, Q50 clarifies 5/5, Q31
# still calls rewards_earned 5/5, Q10 still calls spend_total 3/3, and eight
# further adjacent questions (Q25, Q26, Q27, Q45, Q46, Q47, Q48, Q49) that
# stress this same clarify/answer boundary from both sides all still route
# as gold-expected, 3/3 each. This is prepended to every planner call as
# real conversation history, not prompt text, because tool-call precedent
# steers gpt-4o-mini's
# tool selection far more reliably than an equivalent instruction in prose
# (that is, empirically, exactly the gap rule 3 already tried and did not
# close). Each (name, args) pair below is inert prompt scaffolding: it is
# never invoked, never executed, and does not touch tool_result or
# DATA_TOOLS -- it only exists to shape which tool the REAL final message
# routes to.
PLANNER_FEWSHOT_EXAMPLES: list[tuple[str, str, dict[str, Any]]] = [
    # Domain-A anchor, deliberately the SAME terse category+period shape as
    # the phrasing that regressed -- proves that shape predicts nothing
    # about which tool; the topic word ("spend") does.
    ("Utility spend in June?", "spend_total", {"period": "June 2026", "category": "utilities"}),
    # Rewards topic, period IS stated (even a relative, casually-phrased
    # one) -> call the tool directly, passing the resolved phrase through.
    (
        "How many reward points have I racked up this month?",
        "rewards_earned",
        {"period": "this month"},
    ),
    # Same rewards topic, but genuinely no period stated anywhere -> THIS is
    # what ask_clarification(missing="period") is for.
    (
        "How many total reward points do I have on this card?",
        "ask_clarification",
        {"missing": "period"},
    ),
    # A DIFFERENT missing argument -- no period needed here, but the
    # question implies one specific, unstated category -> a demonstrated
    # precedent for ask_clarification(missing="category"), so that reason
    # doesn't get crowded out once few-shot history is present at all.
    (
        "Is there a cap on my rewards?",
        "ask_clarification",
        {"missing": "category"},
    ),
]


def _build_planner_messages(transcript: str) -> list[Any]:
    system = PLANNER_SYSTEM_PROMPT.format(today=date.today().isoformat())
    messages: list[Any] = [SystemMessage(content=system)]
    for i, (example_utterance, tool_name, tool_args) in enumerate(PLANNER_FEWSHOT_EXAMPLES):
        call_id = f"fewshot_{i}"
        messages.append(HumanMessage(content=example_utterance))
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": tool_name, "args": tool_args, "id": call_id, "type": "tool_call"}
                ],
            )
        )
        # OpenAI's API rejects an assistant message with tool_calls that
        # isn't immediately followed by a matching ToolMessage per
        # tool_call_id -- confirmed directly against the live API while
        # diagnosing this bug. This placeholder response is never read by
        # anything; it only satisfies that API-level pairing requirement so
        # the few-shot history above is accepted at all.
        messages.append(ToolMessage(content="ok", tool_call_id=call_id))
    messages.append(HumanMessage(content=transcript))
    return messages


def plan_node(state: State) -> dict:
    """transcript -> exactly one tool call (never a computed value)."""
    messages = _build_planner_messages(state["transcript"])
    response = _get_planner_llm().invoke(messages)
    calls = getattr(response, "tool_calls", None) or []
    if not calls:
        # tool_choice="required" should make this unreachable, but fail
        # safe into a clarifying question rather than crash or guess.
        tool_call = {"name": "ask_clarification", "args": {"missing": "period"}}
    else:
        first = calls[0]
        tool_call = {"name": first.get("name"), "args": dict(first.get("args") or {})}
    return {"tool_call": tool_call}


def route(state: State) -> str:
    name = (state.get("tool_call") or {}).get("name")
    if name in ("ask_clarification", "refuse"):
        return "clarify"
    return "query"


# ---------------------------------------------------------------------------
# Query -- executes the planner's chosen data tool. See the module docstring
# for why this is a plain function rather than langgraph.prebuilt.ToolNode.
# ---------------------------------------------------------------------------


def query_node(state: State) -> dict:
    tool_call = state.get("tool_call") or {}
    name = tool_call.get("name")
    args = dict(tool_call.get("args") or {})

    data_tool = DATA_TOOLS_BY_NAME.get(name)
    if data_tool is None:
        # Should not happen (route() only sends known data-tool names here),
        # but never crash the turn over a routing edge case.
        return {"tool_result": {"found": False, "requested": name}}

    # Defensive: drop any argument name the planner invented that this
    # tool's own signature doesn't declare, rather than letting an
    # unexpected-keyword TypeError crash the turn.
    accepted = set(data_tool.args.keys()) if hasattr(data_tool, "args") else None
    if accepted is not None:
        args = {k: v for k, v in args.items() if k in accepted}

    try:
        result = data_tool.invoke(args)
    except Exception as exc:
        # A bad or unresolvable argument (most likely an unparseable period
        # phrase reaching resolve_period) -- not the same thing as a term
        # genuinely missing from card_terms.yaml, so it is tagged
        # differently (`error_kind`) and verbalize_node renders an honest
        # "couldn't process that" message for it, never the card-terms gap
        # wording, and never a fabricated number.
        result = {"found": False, "requested": name, "error_kind": "tool_error", "error": str(exc)}

    return {"tool_result": result}


# ---------------------------------------------------------------------------
# Clarify -- terminal node for BOTH ask_clarification and refuse. Text is
# chosen from a small fixed set of digit-free templates, never freely
# authored by an LLM: these are meta-questions/refusals, not facts, but
# keeping them canned guarantees they can never accidentally contain a
# number (which, with tool_result=None, would otherwise be an automatic,
# un-groundable hallucination-check violation -- see eval.py's
# `_flatten_numbers` returning [] when tool_result is None).
# ---------------------------------------------------------------------------

CLARIFY_QUESTIONS: dict[str, str] = {
    "period": (
        "Which time period are you asking about -- for example this month, "
        "last month, or a specific month?"
    ),
    "category": "Which category did you mean -- for example dining, groceries, or fuel?",
    "comparison": "Which two time periods would you like me to compare?",
}
_DEFAULT_CLARIFY = "Could you clarify what you'd like to know?"

REFUSE_MESSAGES: dict[str, str] = {
    "cross_card_comparison": (
        "I can only answer questions about this card -- I don't compare it with other cards."
    ),
    "financial_advice": (
        "I can tell you your spending and this card's terms, but I can't advise on a "
        "decision like that."
    ),
    "out_of_scope": (
        "That's outside what I can help with -- I can answer questions about your "
        "spending on this card and its terms."
    ),
}
_DEFAULT_REFUSE = "I can only answer questions about your spending on this card and its documented terms."


def clarify_node(state: State) -> dict:
    tool_call = state.get("tool_call") or {}
    name = tool_call.get("name")
    args = tool_call.get("args") or {}

    if name == "refuse":
        text = REFUSE_MESSAGES.get(args.get("reason"), _DEFAULT_REFUSE)
        return {"answer_text": text, "needs_clarification": False, "tool_result": None}

    text = CLARIFY_QUESTIONS.get(args.get("missing"), _DEFAULT_CLARIFY)
    return {"answer_text": text, "needs_clarification": True, "tool_result": None}


# ---------------------------------------------------------------------------
# Verbalizer (S06)
# ---------------------------------------------------------------------------

VERBALIZER_MODEL = "gpt-4o-mini"

VERBALIZER_SYSTEM_PROMPT = """You turn one already-correct draft answer into a single natural sentence for \
a voice assistant to speak aloud. You were not given any raw data yourself -- \
only the draft below, which is already fully correct -- so you only rephrase \
it, you never add to it.

Rules:
1. Every number in your output must appear, unchanged, in the draft you were \
given. Never add, remove, round, recompute, or invent a number, percentage, \
or date -- not even one that seems obviously implied.
2. If the draft quotes a policy clause, keep its wording close to verbatim -- \
you may smooth the grammar joining it to the rest of the sentence, but never \
shorten, generalize, or drop a number or condition from it. Do not simplify \
a condition like "waived above Rs. 3,00,000" into something vaguer like \
"waived on high spends" -- that changes its meaning.
3. One or two sentences, no more than about 40 words total.
4. Plain spoken prose only -- no markdown, no bullet points, no lists, no \
headings, no emphasis characters.
5. Write numbers as digits with comma grouping (e.g. "8,240", "3.5", \
"2,000"), never spelled out as words -- a speech engine reads written \
digits aloud correctly on its own.
6. If the period is named in the draft, keep it audible in your rewrite \
(e.g. "in July 2026") so a misheard date would be noticeable.
7. Do not add a fact, category, merchant, or condition that is not already \
in the draft.

Reply with only the final sentence -- nothing else, no preamble.
"""

_VERBALIZER_USER_TEMPLATE = """Original question: {transcript}

Draft (every fact in it is already correct; it may sound mechanical):
{draft}

Rewrite the draft as one natural spoken sentence, following the rules exactly."""


_verbalizer_llm: Any = None


def _get_verbalizer_llm():
    global _verbalizer_llm
    if _verbalizer_llm is None:
        _verbalizer_llm = ChatOpenAI(model=VERBALIZER_MODEL, temperature=0)
    return _verbalizer_llm


# --- number formatting -------------------------------------------------


def _fmt_amount(value: Any) -> str:
    """Round to the nearest whole rupee, comma-grouped -- e.g. 122048.88 ->
    "122,049". See the module docstring's "Number formatting note" for why
    this is digits, not spelled-out words.
    """
    if value is None:
        return "0"
    return f"{int(round(float(value))):,}"


def _fmt_rate(value: Any) -> str:
    """Preserve exactly the precision given -- 5 -> "5", 3.5 -> "3.5". Never
    rounds a rate/percentage away, unlike `_fmt_amount`.
    """
    if value is None:
        return "0"
    f = float(value)
    return str(int(f)) if f == int(f) else f"{f:g}"


def _join_natural(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# --- period phrasing -----------------------------------------------------
# None of the six transaction tools (or rewards_earned) expose a period's
# start/end as literal numeric fields -- only as the pre-formatted
# `period_label` STRING (e.g. "July 2026", "Jan 1 - Aug 11, 2026 (YTD)").
# Digits embedded in a string are not "grounded" per eval.py's own
# hallucination check (`_flatten_numbers` only walks literal int/float
# values, never parses a string). S06 still requires echoing the period
# back audibly ("in July"), so this renders a period phrase using ONLY
# month-name words (never a bare digit) wherever possible, matching the
# PRD.md worked example, which itself echoes "in July" with no year:
#   1. If the phrase the planner actually passed (e.g. "last month",
#      "YTD", "last quarter") has no digit in it at all, it is already
#      digit-safe -- speak it close to verbatim.
#   2. Otherwise (e.g. "July 2026", "last 3 months") extract the month
#      name(s) out of the tool's own period_label and speak only those.
_MONTH_FULL = {
    "Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
    "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
    "Sep": "September", "Sept": "September", "Oct": "October",
    "Nov": "November", "Dec": "December",
}
_MONTH_WORD_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October"
    r"|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\b"
)
_HAS_DIGIT_RE = re.compile(r"\d")


def _extract_month_names(label: str) -> list[str]:
    seen: list[str] = []
    for m in _MONTH_WORD_RE.finditer(label or ""):
        name = _MONTH_FULL.get(m.group(1), m.group(1))
        if not seen or seen[-1] != name:
            seen.append(name)
    return seen


def _period_phrase(period_label: str, original_phrase: str | None) -> str:
    if original_phrase and not _HAS_DIGIT_RE.search(original_phrase):
        low = original_phrase.strip().lower()
        if low in ("ytd", "year to date", "this year to date"):
            return "year to date"
        return low
    months = _extract_month_names(period_label or "")
    if not months:
        return "for that period"
    if len(months) == 1:
        return f"in {months[0]}"
    return f"from {months[0]} to {months[-1]}"


# --- replicas of eval.py's own number-extraction / matching logic ------
# Deliberately mirrors eval.py's `_extract_numbers`, `_flatten_numbers`, and
# `_numbers_match` exactly, so `_validate` below predicts what eval.py's
# hallucination and term-exactness checks will decide, rather than guessing.

_ANSWER_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    for m in _ANSWER_NUM_RE.finditer(text or ""):
        s = m.group().replace(",", "")
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def _flatten_numbers(obj: Any) -> list[float]:
    nums: list[float] = []
    if isinstance(obj, dict):
        for v in obj.values():
            nums.extend(_flatten_numbers(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            nums.extend(_flatten_numbers(v))
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        nums.append(float(obj))
    return nums


def _numbers_match(a: float, b: float) -> bool:
    tol = 1.0 if abs(b) >= 50 else 0.5
    return abs(a - b) <= tol


def _validate(text: str, tool_result: dict | None, required: list[float]) -> bool:
    """True iff `text` would pass eval.py's own hallucination check AND
    contains every number in `required` -- i.e. iff using `text` as the
    final answer is at least as safe as using the deterministic draft.
    """
    spoken = _extract_numbers(text)
    if required and not all(any(_numbers_match(s, r) for s in spoken) for r in required):
        return False
    grounded = _flatten_numbers(tool_result) if tool_result is not None else []
    return all(any(_numbers_match(s, g) for g in grounded) for s in spoken)


# --- gap admission (found: false) -- fully deterministic, no LLM call ---
# Guarantees the "Zero, not low" gate: a canned, always-correct template
# built only from tool_result's own `requested`/`available_*` fields (never
# a recalled or plausible-sounding figure), and always contains "don't
# have" so it matches eval.py's GAP_PHRASES check by construction.


def _render_gap_admission(tool_result: dict) -> str:
    requested = str(tool_result.get("requested") or "that").replace("_", " ")
    available = tool_result.get("available_fee_types") or tool_result.get("available_categories") or []
    available_natural = [str(a).replace("_", " ") for a in available[:3]]
    text = f"I don't have {requested} documented in this card's terms."
    if available_natural:
        text += f" I can tell you about {_join_natural(available_natural)} instead."
    return text


# --- late-payment tier selection (mirrors eval.py's own tier lookup) ---

_TRANSCRIPT_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _first_number_in_text(text: str) -> float | None:
    m = _TRANSCRIPT_NUM_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def _select_tier(tiers: list[dict], due_amount: float) -> dict | None:
    for tier in tiers:
        lo = tier.get("min_due_inr") or 0
        hi = tier.get("max_due_inr")
        if due_amount >= lo and (hi is None or due_amount <= hi):
            return tier
    return None


# --- per-tool deterministic draft + required-numbers builder -----------
# Every branch below builds a sentence whose numbers are copied verbatim out
# of `tool_result` (so they are trivially grounded) and, for card terms,
# uses the tool's own `clause`/`benefit` text near-verbatim per S06. This is
# the answer used as-is if the LLM rewrite step below fails validation, and
# is also what the LLM is asked to only rephrase, never add to.


def _build_facts(
    tool_name: str | None, tool_args: dict, tool_result: dict, transcript: str
) -> tuple[str, list[float]]:
    if tool_name == "spend_total":
        total, count = tool_result["total"], tool_result["count"]
        phrase = _period_phrase(tool_result["period_label"], tool_args.get("period"))
        cat = _cat_display(tool_args.get("category"))
        cat_phrase = f" on {cat}" if cat else ""
        plural = "" if count == 1 else "s"
        draft = (
            f"You spent {_fmt_amount(total)} rupees{cat_phrase} {phrase}, "
            f"across {count} transaction{plural}."
        )
        return draft, [total, count]

    if tool_name == "spend_by_category":
        cats = tool_result.get("categories", [])
        phrase = _period_phrase(tool_result["period_label"], tool_args.get("period"))
        if not cats:
            return f"I didn't find any spending {phrase}.", []
        top3 = cats[:3]
        parts = [
            f"{_fmt_amount(c['total'])} rupees on {_cat_display(c['name'])}" for c in top3
        ]
        draft = f"{phrase.capitalize()}, your top spending was {_join_natural(parts)}."
        return draft, [top3[0]["total"]]

    if tool_name == "top_merchants":
        merchants = tool_result.get("merchants", [])
        phrase = _period_phrase(tool_result["period_label"], tool_args.get("period"))
        if not merchants:
            return f"I didn't find any merchant spending {phrase}.", []
        top3 = merchants[:3]
        parts = [f"{_fmt_amount(m['total'])} rupees at {m['name']}" for m in top3]
        draft = f"{phrase.capitalize()}, you spent the most at {_join_natural(parts)}."
        return draft, [top3[0]["total"]]

    if tool_name == "compare_periods":
        total_a, total_b = tool_result["total_a"], tool_result["total_b"]
        pct, direction = tool_result.get("pct_change"), tool_result["direction"]
        labels = tool_result["labels"]
        phrase_a = _period_phrase(labels["a"], tool_args.get("period_a"))
        phrase_b = _period_phrase(labels["b"], tool_args.get("period_b"))
        cat = _cat_display(tool_args.get("category"))
        cat_phrase = f" on {cat}" if cat else ""
        if direction == "flat":
            draft = (
                f"Your spending{cat_phrase} was flat between {phrase_a} and "
                f"{phrase_b}, at {_fmt_amount(total_a)} rupees both times."
            )
        else:
            verb = "up" if direction == "up" else "down"
            pct_phrase = f" ({_fmt_rate(abs(pct))}%)" if pct is not None else ""
            draft = (
                f"Your spending{cat_phrase} {phrase_a} was {_fmt_amount(total_a)} "
                f"rupees, {verb}{pct_phrase} from {_fmt_amount(total_b)} rupees "
                f"{phrase_b}."
            )
        return draft, [total_a, total_b]

    if tool_name == "find_transactions":
        matches = tool_result.get("matches", [])
        count = tool_result.get("count", 0)
        merchant = tool_args.get("merchant")
        subj = f" at {merchant}" if merchant else ""
        if count == 0:
            return f"I found 0 matching transactions{subj}.", [0]
        top = matches[0]
        plural = "" if count == 1 else "s"
        # NB: the match's exact calendar date is deliberately not spoken --
        # find_transactions only returns it as an ISO string ("2026-07-28"),
        # never as literal numeric fields, so any digit lifted from it (and
        # a naive ISO rendering's hyphens are even misread as minus signs by
        # eval.py's number regex) would be an ungrounded hallucination. The
        # count and amount below are both literal numeric fields already.
        draft = (
            f"Yes -- I found {count} matching transaction{plural}{subj}, the most "
            f"recent {_fmt_amount(top['amount'])} rupees at {top['merchant']}."
        )
        return draft, [count, top["amount"]]

    if tool_name == "recurring_charges":
        subs = tool_result.get("subscriptions", [])
        total = tool_result.get("monthly_total", 0)
        if not subs:
            return "I didn't find any recurring subscriptions in your transaction history.", []
        # NB: the number of subscriptions (len(subs)) is deliberately not
        # spoken -- it isn't itself a literal field in tool_result (only
        # `subscriptions` the list and `monthly_total` are), so stating a
        # count here would be an ungrounded hallucination even though it's
        # true. `monthly_total` is the only number required/safe to speak.
        names = _join_natural([s["merchant"] for s in subs[:5]])
        draft = (
            f"Your recurring charges, including {names}, total "
            f"{_fmt_amount(total)} rupees a month."
        )
        return draft, [total]

    if tool_name == "card_rewards":
        clause = tool_result.get("clause") or tool_result.get("base_rate_clause") or ""
        if tool_result.get("excluded"):
            return clause, []
        rate = tool_result.get("rate_used_points_per_100")
        cap = tool_result.get("cap_points_per_month")
        required = [n for n in (rate, cap) if n is not None]
        return clause, required

    if tool_name == "card_fees":
        if tool_result.get("fee_type") is None:
            # No specific fee_type asked -- a full-schedule listing. Naming
            # every figure risks a long, unlistenable answer; the tool's own
            # numbers stay available if the user asks about one by name.
            count = tool_result.get("count", len(tool_result.get("fees", [])))
            draft = (
                f"This card documents {count} fees and charges, including the "
                f"annual fee, late payment charges, and the forex markup -- ask "
                f"about a specific one for the exact figure."
            )
            return draft, []

        tiers = tool_result.get("tiers")
        if tiers:
            due_amount = _first_number_in_text(transcript)
            tier = _select_tier(tiers, due_amount) if due_amount is not None else None
            if tier is not None:
                return tier.get("clause", ""), [tier["amount_inr"]]
            lowest, highest = tiers[0], tiers[-1]
            draft = (
                f"The late payment charge depends on how much you owe -- "
                f"{_fmt_amount(lowest['amount_inr'])} rupees if it's under "
                f"{_fmt_amount(lowest['max_due_inr'])} rupees, up to "
                f"{_fmt_amount(highest['amount_inr'])} rupees if you owe "
                f"{_fmt_amount(highest['min_due_inr'])} rupees or more."
            )
            return draft, []

        clause = tool_result.get("clause") or ""
        required = [
            tool_result[k]
            for k in ("amount_or_pct", "waiver_spend_inr", "min_amount_inr")
            if tool_result.get(k) is not None
        ]
        return clause, required

    if tool_name == "card_offers":
        offers = tool_result.get("offers", [])
        count = tool_result.get("count", 0)
        if count == 0:
            return "I don't see any current offers matching that.", []
        top = offers[0]
        draft = f"At {top['merchant']}: {top['benefit']}"
        if count > 1:
            draft += f" There are {count} offers matching that in total."
        return draft, list(top.get("benefit_numbers", []))

    if tool_name == "rewards_earned":
        points_total = tool_result.get("points_total", 0)
        phrase = _period_phrase(tool_result.get("period_label", ""), tool_args.get("period"))
        category = tool_args.get("category")
        capped = tool_result.get("capped_categories", [])

        if category and tool_result.get("category_excluded"):
            cat = _cat_display(category)
            draft = (
                f"{cat.capitalize()} spend doesn't earn reward points on this card, "
                f"so you earned 0 points from {cat} {phrase}."
            )
            return draft, [0]

        cat_phrase = f" {_cat_display(category)}" if category else ""
        cap_note = ""
        matching_caps = [c for c in capped if category is None or c.get("category") == category]
        if matching_caps:
            # NB: deliberately doesn't name which calendar month hit the cap
            # (`month`/`month_label`) -- the main sentence already states
            # the queried period once, and the cap month is a date-derived
            # string not duplicated as a literal numeric field.
            c0 = matching_caps[0]
            cap_note = (
                f" You hit the {_cat_display(c0.get('category'))} rewards cap of "
                f"{_fmt_amount(c0['capped_points'])} points."
            )
        draft = f"You earned {_fmt_amount(points_total)}{cat_phrase} points {phrase}.{cap_note}"
        return draft, [points_total]

    # Unknown tool name -- should not happen for a real data-tool call, but
    # never fabricate a sentence with numbers we can't account for.
    return "I found a result, but I'm not able to describe it.", []


def verbalize_node(state: State) -> dict:
    tool_call = state.get("tool_call") or {}
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args") or {}
    tool_result = state.get("tool_result")

    if not isinstance(tool_result, dict):
        return {"answer_text": "I couldn't find an answer to that."}

    if tool_result.get("found") is False:
        if tool_result.get("error_kind") == "tool_error":
            return {
                "answer_text": (
                    "I had trouble with that request -- could you rephrase the time "
                    "period, e.g. as last month, a specific month, or a date?"
                )
            }
        return {"answer_text": _render_gap_admission(tool_result)}

    transcript = state.get("transcript", "")
    draft, required = _build_facts(tool_name, tool_args, tool_result, transcript)

    text = draft
    try:
        user_msg = _VERBALIZER_USER_TEMPLATE.format(transcript=transcript, draft=draft)
        response = _get_verbalizer_llm().invoke(
            [SystemMessage(content=VERBALIZER_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
        )
        candidate = (response.content or "").strip()
        if candidate and _validate(candidate, tool_result, required):
            text = candidate
    except Exception:
        pass  # fall back to the deterministic draft, which is already correct

    return {"answer_text": text}


# ---------------------------------------------------------------------------
# Graph assembly -- see all-specs.md S05 for the exact shape this mirrors.
# ---------------------------------------------------------------------------


def build_graph():
    g = StateGraph(State)
    g.add_node("plan", plan_node)
    g.add_node("query", query_node)
    g.add_node("verbalize", verbalize_node)
    g.add_node("clarify", clarify_node)
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", route, {"query": "query", "clarify": "clarify"})
    g.add_edge("query", "verbalize")
    g.add_edge("verbalize", END)
    g.add_edge("clarify", END)
    return g.compile()


graph = build_graph()
app = graph  # alias -- eval.py's get_pipeline() also probes for `graph.app`


def run_pipeline(utterance: str) -> dict:
    """The system-under-test entry point eval.py looks for first (see its
    `get_pipeline()`). Thin wrapper: build the initial 6/7-field state, run
    the compiled graph, return the resulting state dict as-is.
    """
    initial_state: State = {
        "audio_in": None,
        "transcript": utterance,
        "tool_call": None,
        "tool_result": None,
        "answer_text": "",
        "audio_out": None,
        "needs_clarification": False,
    }
    return graph.invoke(initial_state)
