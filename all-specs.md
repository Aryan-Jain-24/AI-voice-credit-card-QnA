# Spec Sheets — Voice Q&A over Credit Card Data

Ten specs. Each is independently buildable and independently testable. Build in
order; every spec has a **Done when** condition that must pass before starting the
next one.

**Ordering principle:** correctness first, language second, voice last. The
microphone does not exist until S07. If the numbers are wrong, a nicer voice makes
the product worse, not better.

```
S00 Skeleton
 ├─ S01 Synthetic txns ──► S02 Loader + mapping ──► S03 Transaction tools ─┐
 └─ S03B Card terms + terms/rewards tools ─────────────────────────────────┤
                                                                           ▼
                                                                    S04 Gold eval
                                                                           │
                                              S05 Planner + graph ◄─────────┘
                                                        │
                                              S06 Verbalizer
                                                        │
                                    S07 Voice I/O ──► S08 UI ──► S09 Handover
```

S03B is the new domain: card terms, rewards, fees, offers. It depends on S01 only for
the category list, so it can be built in parallel if you get blocked on transactions.

---

## S00 — Repo skeleton and config

**Goal:** every later spec has a place to live and a key to use.

**Deliverables**
```
voice-card-bot/
├── app.py              # Streamlit UI            (S08)
├── graph.py            # LangGraph definition    (S05)
├── tools_txn.py        # 6 transaction tools     (S03)
├── tools_card.py       # 4 terms/rewards tools   (S03B)
├── voice.py            # STT + TTS               (S07)
├── data_loader.py      # canonical loader        (S02)
├── mapping.yaml        # field mapping           (S02)
├── card_terms.yaml     # card product terms      (S03B)
├── generate_data.py    # synthetic generator     (S01)
├── eval.py             # eval harness            (S04)
├── data/
├── evals/gold_questions.json
├── requirements.txt
├── .env.example
└── README.md
```

**Config:** `OPENAI_API_KEY` from `.env` locally, from Streamlit secrets in
deployment. Never hardcoded, never committed. `.env` in `.gitignore` from commit one.

**Done when:** repo runs `streamlit run app.py` and shows "hello", key loads from env.

**Time:** 20 min

---

## S01 — Synthetic transaction generator

**Goal:** a dataset realistic enough that hard questions have real answers.

**Why this comes first:** the edge cases you generate here determine which questions
are answerable on Thursday. A flat random dataset makes every answer boring and hides
every bug.

**Output:** `data/transactions.csv`, ~2,000 rows, 18 months, 1 user, **1 card**.

`card_id` stays in the schema as a constant — so multi-card v2 is a filter, not a
migration — but every v1 question is single-card.

**Schema (canonical)**

| Column | Type | Notes |
|---|---|---|
| `txn_id` | str | `TXN000001` |
| `timestamp` | datetime | ISO 8601 |
| `amount` | float | positive = spend, negative = refund |
| `merchant` | str | from a fixed dictionary |
| `category` | str | 12 categories |
| `card_id` | str | masked, e.g. `XXXX4412` |
| `txn_type` | str | `purchase / refund / fee / interest / emi` |
| `city` | str | |
| `currency` | str | `INR`, some `USD` |

**Categories (12):** food_dining, groceries, fuel, travel, shopping, entertainment,
utilities, health, education, cash_advance, fees_interest, other

**Realism requirements — these are the spec, not decoration**

- Weekday/weekend rhythm; monthly salary-week spike
- Festive season lift (Oct–Nov)
- 6 recurring subscriptions, same merchant, ~same amount, ~same day each month
- 15 refunds, matched to earlier purchases
- 1 EMI conversion with a monthly instalment series
- 3 foreign-currency transactions with FX markup
- 2 late fees, each followed by an interest charge
- 1 duplicate charge (same merchant, same amount, same day) — for anomaly questions
- 1 genuine spend spike in one month — so "why was March high?" has a real answer
- **At least 2 months where dining spend breaches the reward cap**, and at least one
  where it doesn't — so `rewards_earned` cap logic is exercised by real data rather
  than only by unit tests
- Enough `cash_advance` and `fees_interest` rows to test reward *exclusions*

**Merchant dictionary:** ~40 recognisable Indian merchants (Swiggy, Zomato, BigBasket,
IRCTC, Indian Oil, Amazon, Myntra, Netflix, Jio, Apollo Pharmacy…). Reused later for
fuzzy ASR matching in S07 — so keep it in one importable list.

**Done when:** CSV loads, has ≥1,800 rows, and each realism item above is findable
with a one-line pandas filter. Write those filters as assertions in `generate_data.py`.

**Time:** 2 hrs

---

## S02 — Data loader and mapping layer

**Goal:** the swappability promise, implemented.

**Interface**
```python
def load_transactions(mapping_path: str = "mapping.yaml") -> pd.DataFrame:
    """Returns a canonical DataFrame regardless of source column names."""
```

**Behaviour**
1. Read `mapping.yaml` → source path + field mapping
2. Load CSV, rename columns to canonical names
3. Coerce types (`timestamp` → datetime, `amount` → float)
4. Validate: all six required columns present → else raise a clear error naming the
   missing field and the mapping key that would fix it
5. Cache with `@st.cache_data` so it loads once per session

**Done when:** you rename every column in the CSV to nonsense, edit only
`mapping.yaml`, and every tool still passes its tests. Do this test — it is the
proof, and it takes four minutes.

**Time:** 45 min

---

## S03 — Query tools

**Goal:** six deterministic functions. This is the product's correctness layer.

**Shared rules**

- Decorated with LangChain `@tool`, typed args, docstring written *for the LLM* —
  the docstring is the prompt for tool selection, so it names example utterances
- Return a small flat dict of scalars, never a DataFrame, never prose
- Every dict includes `period_label` (human-readable) so the verbalizer can echo the
  period back and the user can catch a misread date
- Read-only. No mutation of the source frame.
- Relative dates resolved by a Python helper, **never** by the LLM

**Date helper**
```python
def resolve_period(phrase: str, today: date) -> tuple[date, date, str]
# "last month" -> (2026-07-01, 2026-07-31, "July 2026")
```
Supports: last month, this month, last week, this week, last N months, a named month,
last year, YTD, a specific date.

**The six tools**

| Tool | Args | Returns |
|---|---|---|
| `spend_total` | period, category?, card_id? | `{total, count, period_label, avg_txn}` |
| `spend_by_category` | period, top_n=5 | `{categories:[{name,total,pct}], total, period_label}` |
| `top_merchants` | period, top_n=5 | `{merchants:[{name,total,count}], period_label}` |
| `compare_periods` | period_a, period_b, category? | `{total_a, total_b, delta, pct_change, direction, labels}` |
| `find_transactions` | merchant?, date?, min_amount?, period? | `{matches:[{date,merchant,amount}], count}` — cap at 5 |
| `recurring_charges` | — | `{subscriptions:[{merchant,amount,frequency,last_charged}], monthly_total}` |

**Recurring detection:** same merchant, ≥3 occurrences, amount within ±10%, interval
28–31 days. Deterministic rule, not an LLM judgement.

**Done when:** each tool has ≥3 pytest cases with hand-computed expected values.
Hand-computed — if you generate the expectation with the same code you are testing,
you have tested nothing.

**Time:** 3 hrs

---

## S03B — Card terms, rewards and offers

**Goal:** answer "what does my card do?" from a file, never from the model's memory.

**Why it's a separate spec:** this is a different failure mode from Domain A. There is
no arithmetic to get wrong — the risk is the model *recalling* a plausible reward rate
from training and stating it with confidence. Everything below exists to make that
impossible.

### Part 1 — `card_terms.yaml`

Hand-authored, ~40 facts, one card. Structure per the PRD §7.3. Two rules:

- Every leaf that could be spoken carries a `clause` string — the exact sentence a
  terms document would use. The bot speaks the clause, not a paraphrase.
- Category keys must match the 12 canonical categories from S01 exactly. A mismatch
  here silently zeroes out reward calculations, and it is a genuinely annoying bug to
  find on Wednesday night.

Include deliberate gaps — two or three plausible charge types left undocumented. These
are the test cases for "admit a gap, don't fill it."

### Part 2 — four tools

| Tool | Args | Returns |
|---|---|---|
| `card_rewards` | category? | `{base_rate, category_rate, cap, exclusions, redemption_value, clause}` |
| `card_fees` | fee_type? | `{fee_type, amount_or_pct, waiver_condition, clause}` |
| `card_offers` | merchant? / category? | `{offers:[{merchant, benefit, valid_until}], count}` |
| `rewards_earned` | period, category? | `{points_total, by_category, capped_categories, excluded_spend, redemption_value_inr, period_label}` |

**`rewards_earned` is the cross-domain tool and the demo centrepiece.** It applies the
schedule to actual transactions. Deterministic Python. Must handle, in this order:

1. Exclude excluded categories (`cash_advance`, `fees_interest`)
2. Exclude refunds, or net them off — pick one, document which
3. Apply category rate where defined, base rate otherwise
4. Apply monthly caps **per category, per calendar month** — not across the period
5. Return `capped_categories` so the answer can say "you hit the dining cap in July"

Step 4 is the one that gets written wrong. If someone asks about a quarter, the cap
applies three times, not once.

**Missing-term behaviour:** if a requested `fee_type` isn't in the file, return
`{"found": false, "requested": "..."}`. Do not return an empty dict — the planner
needs to distinguish "no data" from "zero".

**Done when:**
- Every tool has pytest cases with hand-computed expectations
- `rewards_earned` has explicit tests for: cap hit, cap not hit, multi-month cap,
  excluded category, refund handling
- A missing fee type returns `found: false`, verified

**Time:** 2.5 hrs

---

## S04 — Gold eval set and harness

**Goal:** the thing that makes every later claim measurable.

**Build this before the LLM exists.** Written afterwards, the questions unconsciously
bend toward what the model already handles.

**`evals/gold_questions.json`** — 55 entries:

| Bucket | Count | Purpose |
|---|---|---|
| Domain A straightforward, one per family | 8 | Transaction baseline |
| Domain A phrasing variants | 8 | "what'd I blow on food", "food spend July?" |
| Domain A multi-constraint | 4 | "groceries over 2,000 last quarter" |
| **Domain B — rewards, fees, offers** | 10 | "fuel rate?", "annual fee?", "forex markup?" |
| **Cross-domain — `rewards_earned`** | 5 | "points earned in July", "am I near the dining cap?" |
| **Domain-routing traps** | 4 | "what fees do I pay" vs "what fees was I charged" |
| **Missing terms → must admit gap** | 5 | Charge types deliberately absent from the YAML |
| **Underspecified → must clarify** | 6 | "how much did I spend?", "what's the rate?" |
| **Out of scope → must refuse** | 5 | "is Amex better?", "should I close this card" |

For Domain B entries, `expected_value` is read from `card_terms.yaml` by the eval
script — so if the terms file changes, the eval updates itself and nothing silently
drifts.

Entry shape:
```json
{
  "id": "Q07",
  "utterance": "how much did I spend on food last month",
  "expected_tool": "spend_total",
  "expected_args": {"period": "last month", "category": "food_dining"},
  "expected_value": 8240.50,
  "expected_behaviour": "answer"
}
```

`expected_value` computed by a direct pandas one-liner in the eval script — not by
calling the tool. Independent ground truth.

**`eval.py` reports**
- Intent accuracy (correct tool)
- **Domain routing accuracy** (transactions vs. terms) — reported separately, because
  a domain error and an intra-domain error have different causes
- Argument accuracy (correct args)
- **Numeric exactness** (spoken figure == ground truth)
- **Term exactness** — every rate/fee/cap spoken matches `card_terms.yaml`
- **Hallucination check** — regex every number out of the answer text, assert each
  appears in `tool_result`. This is the hard gate, and it now covers both domains.
- **Gap-admission precision** — all 5 missing-term questions get "I don't have that"
- Clarify precision (all 6 clarify, none of the others do)
- Refusal precision
- Latency p50 / p95

**Done when:** `python eval.py` prints a table. It will show 0% until S05 — correct.
Text input only, no audio.

**Time:** 2 hrs

---

## S05 — Planner node and LangGraph assembly

**Goal:** speech text → one correct typed tool call, or a clarifying question.

**Graph**
```python
g = StateGraph(State)
g.add_node("plan", plan_node)
g.add_node("query", ToolNode(TOOLS))
g.add_node("verbalize", verbalize_node)
g.add_node("clarify", clarify_node)
g.set_entry_point("plan")
g.add_conditional_edges("plan", route, {"query": "query", "clarify": "clarify"})
g.add_edge("query", "verbalize")
g.add_edge("verbalize", END)
g.add_edge("clarify", END)
```

(`listen` and `speak` are added in S07 — keep the core graph runnable from text so
evals stay fast.)

**Planner system prompt must state**
1. You select exactly one tool. You never compute values.
2. **You never state a fee, rate, cap or offer from your own knowledge.** All card
   terms come from tools. If you find yourself about to recall a reward rate, that is
   the signal to call `card_rewards` instead.
3. If a required argument is missing — especially the time period — call
   `ask_clarification` instead of guessing. Never invent a default period.
4. Distinguish the schedule from the history: what the card *charges* is
   `card_fees`; what the user *was charged* is `spend_total(category=fees_interest)`.
5. If the question is about another card, comparison, or advice, call `refuse`.
6. Today's date is `{today}`. Relative dates pass through as phrases; a Python helper
   resolves them.

**Ten tools bound is near the reliability limit for `gpt-4o-mini`.** If domain routing
comes in below 95%, the fix is sharper docstrings — each one naming two example
utterances and one *counter*-example ("not for questions about fees already charged")
— not a bigger model. Try that before escalating to `gpt-4o`.

`ask_clarification` and `refuse` are bound as tools too — that way routing is one
uniform mechanism rather than prompt-string parsing.

**Settings:** `gpt-4o-mini`, temperature 0, `tool_choice="required"`.

**Done when:** `eval.py` scores ≥90% intent accuracy, ≥95% domain routing, 100% clarify
precision, 100% refusal precision, 100% gap-admission — via text input. Do not proceed
to voice until this passes.

**Time:** 3 hrs

---

## S06 — Verbalizer node

**Goal:** turn a result dict into one sentence that sounds right spoken aloud.

**Constraints in the prompt**
- One or two sentences, max ~40 words. Long answers are unlistenable.
- Every number appears exactly as given. **No arithmetic, no rounding, no percentages
  you weren't handed.**
- Always echo the period label back ("in July") so a misread date is audible.
- Speak amounts naturally: "eight thousand two hundred forty rupees", not "8240.50".
- No markdown, no bullet points, no lists — this is going to a speech engine.
- For `spend_by_category`, name the top three only.
- **For card terms: speak the `clause` verbatim or near-verbatim.** Do not simplify a
  fee condition — a "waived above ₹3,00,000" that gets shortened to "waived on high
  spends" is a materially different statement.
- **Always speak the cap alongside the rate.** "5 points per hundred on dining" without
  "capped at 2,000 a month" is technically true and practically misleading.
- If `tool_result` has `found: false`, say plainly that this isn't in the card terms
  and offer what is available. Never substitute a typical market value.

**Temperature 0.**

**Done when:** the hallucination check in `eval.py` returns zero violations across all
55 questions, and all 10 Domain B answers match the YAML exactly. Zero, not "low".

**Time:** 1.5 hrs

---

## S07 — Voice I/O

**Goal:** audio in, audio out. Two functions, thin wrappers.

```python
def transcribe(audio_bytes: bytes) -> str     # whisper-1
def synthesize(text: str) -> bytes            # tts-1, voice="nova", mp3
```

**Merchant fuzzy correction — do not skip this.** Whisper reliably mangles Indian
merchant names. After transcription, fuzzy-match tokens against the merchant
dictionary from S01 (`rapidfuzz`, threshold ~80) and substitute. "Swiggie" → "Swiggy".
This one function is the difference between a demo that works and one that
embarrassingly doesn't.

Pass the merchant list as Whisper's `prompt` parameter too — it biases recognition
before you ever need the fuzzy fallback.

**Graph:** add `listen` at entry, `speak` before END.

**Done when:** 10 spoken questions transcribe correctly, including 3 with merchant
names. Log every raw transcript — you need them for the eval report's WER number.

**Time:** 2 hrs

---

## S08 — Streamlit UI and deploy

**Goal:** one URL he opens on his phone and it just works.

**Layout (single column, deliberately plain)**
1. Title + one-line explanation of scope
2. `st.audio_input("Ask a question")` — native mic widget
3. Spinner with the current stage ("Listening… Thinking… Answering")
4. `st.audio(response, autoplay=True)`
5. Transcript and answer shown as text — trust requires seeing what it heard
6. **Expander: "How it got this answer"** — shows tool name, args, raw result dict
7. Sidebar: example questions as buttons, grouped **"Your spending" / "Your card" /
   "Your rewards"** — the grouping teaches the scope without a paragraph of text;
   plus a dataset summary (rows, date range, card name)

Item 6 matters more than it looks. It makes the "LLM never does arithmetic" principle
visible instead of merely claimed. It is the first thing to open in the Loom.

**Deploy:** Streamlit Community Cloud, `OPENAI_API_KEY` in secrets. Test on a phone
browser — mic permissions behave differently there.

**Done when:** public URL works on your phone from mobile data.

**Time:** 3 hrs

---

## S09 — Eval report and handover

**Goal:** the artefact that separates this from a demo video.

**`EVAL_REPORT.md`**
1. Headline metrics table vs. the PRD targets, pass/fail marked
2. Per-family breakdown — which question types are weakest
3. Latency distribution
4. ASR accuracy, before and after fuzzy correction
5. **Known failure modes**, written by you, each with a cause and a fix path

Candidate failure modes to check for and document honestly:
- Ambiguous relative dates near month boundaries
- Compound questions ("food and travel last month") — v1 handles one intent
- Category names that don't map to the 12 canonical ones
- Uncommon merchant names still mis-transcribed
- Domain-routing edge cases between fee schedule and fees charged
- Reward caps at period boundaries (a quarter query spanning three monthly caps)
- Cold-start latency on first request

**README** — setup in 5 commands, architecture diagram, and the **30-minute swap
guide**: `mapping.yaml` for transactions, `card_terms.yaml` for the card. Run tests,
done.

**Loom, 3 minutes:** a spend question → open the "how it got this" panel → a rewards
question showing the clause it came from → **"how many points did I earn last month"**
(the cross-domain moment, spend the most time here) → a missing-term question where it
admits the gap → one failure mode you already knew about.

**Done when:** a stranger with the repo and no context can run it locally and swap the
data source without asking you a question.

**Time:** 2 hrs

---

## Schedule

| Day | Specs | Hours |
|---|---|---|
| Mon | S00, S01, S02, S03 | ~6 |
| Tue | S03B, S04, S05 | ~8 |
| Wed | S06, S07, S08 | ~6.5 |
| Thu AM | S09 | ~2 |

Total ~22.5 hrs, up from ~19.5. Tuesday is now the heavy day — S03B lands there
because it needs the category list from Monday but nothing else.

**Buffer, in cutting order:**
1. FX and EMI rows in S01 — nice realism, not load-bearing
2. `card_offers` — the least interesting of the four card tools, and the easiest to
   add back on Thursday if there's slack
3. Phrasing-variant questions in S04, down to 5

**Never cut:** the missing-terms bucket or the domain-routing traps in S04. Those two
buckets are what prove the terms layer is grounded rather than improvised, and that is
the whole reason Domain B is defensible.

**Hard rule:** do not build S07 before S05 passes its gate. Debugging a wrong number
through a microphone costs about four times what it costs through a text box.