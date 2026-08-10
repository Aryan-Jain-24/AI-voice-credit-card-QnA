# PRD — Voice Q&A over Credit Card Data

**Owner:** Aryan Jain
**Requested by:** Chandresh Pancholi
**Version:** v1 (trial scope)
**Ship date:** Thursday
**Status:** Approved to build

---

## 1. What this is

A web app where a person holds a button, asks a question about their credit card in
plain speech, and hears a spoken answer with the correct number in it.

> "How much did I spend on food last month?"
> → *"You spent ₹8,240 on food and dining in July, across 31 transactions. That's up 12% from June."*

> "What's the reward rate on dining?"
> → *"You earn 5 points per hundred rupees on dining, capped at 2,000 points a month."*

> "How many points did I earn last month?"
> → *"You earned 4,120 points in July. About 1,900 of those came from dining."*

Scope of v1 is **one card, one cardholder**, covering two domains:

- **Transaction history** — spend, categories, merchants, trends, subscriptions, anomalies
- **Card terms** — rewards, fees, charges, offers, eligibility, limits

Explicitly **not** comparison across cards, and **not** recommendations about which
card to hold.

---

## 2. Why it is useful

A cardholder's questions split cleanly into two shapes, and both are badly served today.

**"What did I do?"** — aggregation questions. A sum, a comparison, a ranking, a
filter. Today: open the app, find the statement, pick a date range, read a chart.
Four navigation steps to retrieve one number you already knew you wanted.

**"What does my card do?"** — retrieval questions. Reward rate on fuel, annual fee,
late payment charge, forex markup, current offers. Today: a 40-page terms PDF, or a
marketing page that omits the caps, or a call centre. Most cardholders do not know
their own card's reward structure. That is a product failure, not a user failure.

Voice collapses both. The question *is* the query.

Four reasons this shape of problem is worth building:

1. **The intent is short, the retrieval is long.** You can say in three seconds what
   takes four taps to specify.
2. **Answers are verifiable.** Every question here has exactly one correct answer —
   a computed figure or a documented term. Measurable means improvable.
3. **The two domains multiply.** The interesting questions cross them: *"How many
   points did I earn last month?"* needs the reward schedule applied to actual
   transactions. *"Am I close to the dining cap?"* needs both. Neither a statement app
   nor a terms PDF answers those today, which is where the real value sits.
4. **It generalises.** The same graph answers questions over invoices, orders, payouts,
   or any dataset paired with a rules document. Only the tool layer changes.

**What this is not for:** browsing, exploration, or anything a chart does better.
If the answer needs a visual, voice is the wrong interface and v1 says so.

---

## 3. The one principle everything follows from

> **The language model never produces a fact. It only routes to one and reads it aloud.**

Two corollaries, one per domain:

**On transactions — the LLM never does arithmetic.** It converts speech into a
structured query; a deterministic Python function computes the number; the LLM reads
that number aloud without recalculating it. A model asked to sum 2,000 rows will
produce a plausible, confident, wrong figure. On financial data that is not a bug, it
is a disqualification.

**On card terms — the LLM never recalls, it looks up.** Reward rates and fee
structures are exactly the kind of thing a model half-remembers from training and
states with total confidence. Every term comes from a structured card-terms file, and
the answer carries the clause it came from. If a term is not in the file, the bot says
it does not have it rather than filling the gap.

A wrong number said out loud in a confident voice is worse than no product. That is
true of a spend total and doubly true of a fee the user might act on.

**Corollary — no free-form text-to-SQL, and no vector store either.** Generated SQL
hallucinates columns and cannot be unit-tested. And for a single card's terms, RAG is
theatre: one document, maybe 40 facts, all of which fit in a structured YAML file that
is faster, exactly correct, and citable. Retrieval that can return the wrong chunk is
a downgrade from a dictionary lookup. v1 uses typed tools over both domains.

---

## 4. Non-goals for v1

Written down so scope does not drift mid-week.

| Not doing | Why |
|---|---|
| Comparison **across** cards ("is HDFC better than Amex?") | Needs a multi-issuer product catalogue and turns the bot into a recommendation engine. v1 answers about *this* card only. |
| Multiple cards for one user | v1 is single-card. Multi-card is a `card_id` filter and a second terms file — deliberately deferred so the terms layer gets proven on one first. |
| Streaming audio / interruption | ~2s faster, meaningfully more complex. Swappable later (see §9). |
| Multi-user accounts, auth | Demo is single-user. Auth adds nothing to the question being tested. |
| Real bank/PII data | Synthetic set by default, real schema swappable in one file. |
| Financial advice ("should I get card X", "should I close this") | Out of scope by design. Stating a fee is in scope; advising on a decision is not. The bot refuses and says why. |
| Mobile native app | Web works on a phone browser. One URL to share. |

---

## 5. Users and job stories

**Primary user (demo):** a cardholder checking their own spending.

- When I get my statement and it looks high, I want to ask what drove it, so I can
  decide whether to worry.
- When I am budgeting, I want to know what I spend on a category monthly, so I can
  set a realistic limit.
- When I scan my statement, I want to find a charge I don't recognise, so I can
  dispute it.
- When I am cutting costs, I want to know what recurring charges I have, so I can
  cancel the dead ones.

**Evaluating user (real):** Chandresh, judging whether the build is trustworthy,
explainable, and swappable onto his own data in under an hour.

---

## 6. Scope — the question taxonomy

v1 answers ten families across two domains. This list is the contract; anything
outside it gets a graceful refusal rather than a guess.

**Domain A — transactions (computed)**

| # | Family | Example utterance | Tool |
|---|---|---|---|
| 1 | Total spend | "What did I spend last month?" | `spend_total` |
| 2 | Category breakdown | "Where did my money go in March?" | `spend_by_category` |
| 3 | Merchant ranking | "Who do I spend the most at?" | `top_merchants` |
| 4 | Period comparison | "Am I spending more than last month?" | `compare_periods` |
| 5 | Transaction lookup | "Did I pay Swiggy on the 14th?" | `find_transactions` |
| 6 | Recurring charges | "What subscriptions am I paying for?" | `recurring_charges` |

**Domain B — card terms (retrieved)**

| # | Family | Example utterance | Tool |
|---|---|---|---|
| 7 | Rewards structure | "What do I earn on fuel?" / "Is there a cap?" | `card_rewards` |
| 8 | Fees and charges | "What's my annual fee?" / "What's the forex markup?" | `card_fees` |
| 9 | Offers | "Any offers on dining right now?" | `card_offers` |

**Cross-domain (the interesting one)**

| # | Family | Example utterance | Tool |
|---|---|---|---|
| 10 | Rewards earned | "How many points did I earn last month?" / "Am I near the dining cap?" | `rewards_earned` |

Family 10 applies the reward schedule from Domain B to actual transactions from
Domain A. It is a deterministic calculation in Python — category rates, caps,
exclusions, refund handling — not an LLM inference. It is also the single most
demo-worthy capability in the build, because neither a statement app nor a terms PDF
answers it today.

**One routing ambiguity to handle explicitly:** *"what fees do I pay?"* (the schedule,
Domain B) versus *"what fees was I charged?"* (actual `txn_type=fee` rows, Domain A).
The planner must distinguish these, and both are in the eval set.

Plus two behaviours that are features, not fallbacks:

- **Clarify, don't assume.** "How much did I spend?" has no time period. The bot asks
  for one. It never silently picks a default and reports a number as fact.
- **Refuse, don't improvise.** "Should I get an Amex?" → the bot says it answers
  questions about this card only, and names what it can do instead.
- **Admit a gap, don't fill it.** If a term isn't in the card-terms file — a charge
  type not documented, an offer that expired — the bot says it doesn't have that,
  rather than reciting something plausible from training. This is the single highest
  risk in Domain B and it gets its own eval bucket.

---

## 7. Architecture

### 7.1 The graph

Built on LangGraph. Five nodes, one conditional edge.

```
                    ┌──────────────────────────┐
                    │                          ▼
  [mic] ──► listen ──► plan ──► query ──► verbalize ──► speak ──► [audio out]
                        │                                ▲
                        └────────► clarify ──────────────┘
```

| Node | Does | Model / lib |
|---|---|---|
| `listen` | audio bytes → transcript | OpenAI `whisper-1` |
| `plan` | transcript → one typed tool call, **or** a clarifying question | `gpt-4o-mini` with `.bind_tools()` |
| `query` | executes the tool over a pandas DataFrame | LangGraph `ToolNode` |
| `verbalize` | computed dict → one spoken sentence, numbers injected verbatim | `gpt-4o-mini`, temperature 0 |
| `speak` | text → mp3 | OpenAI `tts-1` |

The conditional edge after `plan` routes to `clarify` when required arguments are
missing (usually the time period). This single branch is what makes the system
*designed* rather than a linear script — and it is the thing that prevents the most
common failure mode in data chatbots: confidently answering a question that was
never fully asked.

### 7.2 State

```python
class State(TypedDict):
    audio_in: bytes | None
    transcript: str
    tool_call: dict | None
    tool_result: dict | None
    answer_text: str
    audio_out: bytes | None
    needs_clarification: bool
```

Six fields. Every node reads some, writes one. No hidden state.

### 7.3 Data layer — two sources, one card

**Transactions:** pandas over a CSV, ~2,000 rows. Not DuckDB, not Postgres. At this
size every aggregation is sub-millisecond either way, and "it's a dataframe" requires
zero explanation to anyone reading the repo.

**Card terms:** a single `card_terms.yaml` — structured, hand-authored, ~40 facts.

```yaml
card:
  name: "Synthetic Rewards Card"
  network: "Visa Signature"
fees:
  annual: {amount: 2500, currency: INR, waiver_spend: 300000,
           clause: "Annual fee waived on spends above ₹3,00,000 in a card year"}
  forex_markup: {pct: 3.5, clause: "3.5% markup on all foreign currency transactions"}
  late_payment: [...]
  cash_advance: [...]
rewards:
  base_rate: {points_per_100: 2}
  category_rates:
    food_dining: {points_per_100: 5, monthly_cap_points: 2000}
    fuel:        {points_per_100: 1, note: "surcharge waiver up to ₹200/month"}
  excluded_categories: [fees_interest, cash_advance]
  redemption: {value_per_point_inr: 0.25}
offers:
  - {merchant: "Swiggy", benefit: "10% off up to ₹150", valid_until: "2026-09-30"}
```

Every leaf carries a `clause` string. The verbalizer speaks the clause, not a
paraphrase — that is what makes Domain B answers auditable, and it costs nothing.

**Why YAML and not a vector store:** 40 facts fit in memory. A dictionary lookup is
exact; a similarity search can return the wrong clause. Adding a retrieval step here
would add latency, add a dependency, and *reduce* accuracy. Worth saying out loud in
the Loom — restraint is a signal.

### 7.4 Schema swappability

Direct answer to the second question in the brief.

```
real_data.csv ──► mapping.yaml ──► canonical DataFrame ──► tools (unchanged)
```

`mapping.yaml` maps six field names. To point the bot at real data:

```yaml
source: data/real_transactions.csv
fields:
  txn_id:    transaction_reference
  timestamp: posted_at
  amount:    amt_inr
  merchant:  merchant_name
  category:  mcc_description
  card_id:   card_last4
```

Nothing else changes. That is the entire migration path, and it is the part of this
build most likely to matter beyond the trial week.

Card terms swap the same way: replace `card_terms.yaml` with the real card's schedule.
The tools read keys, not values, so a different fee structure needs no code change.
Multi-card v2 becomes a dict of terms files keyed by `card_id`.

### 7.5 Stack and cost

| Layer | Choice | Reason |
|---|---|---|
| Orchestration | LangGraph `StateGraph` | Known stack, and the graph *is* the explanation |
| UI | Streamlit + `st.audio_input` | Native mic widget, no JS |
| STT | OpenAI `whisper-1` | One call, strong on Indian merchant names |
| Planner + verbalizer | `gpt-4o-mini` | Fast, cheap, tool-calling is reliable |
| TTS | OpenAI `tts-1` | Same key, natural output |
| Data | pandas + CSV | Explainable in one sentence |
| Deploy | Streamlit Community Cloud | Free, one public URL to share |

**Cost per query ≈ ₹0.25 (~$0.003).** Whisper on 5s audio (~$0.0005) + planner call
(~$0.00025) + verbalizer (~$0.00007) + TTS on ~120 chars (~$0.0018). A thousand demo
queries costs about $3. Worth stating to him — it shows the thing is deployable, not
just demoable.

---

## 8. Success metrics

The gate is correctness, not polish. Measured against a **55-question** gold set whose
expected answers are derived directly from the data and the terms file, independent of
the LLM.

### Must pass before shipping (hard gates)

| Metric | Target | How measured |
|---|---|---|
| **Numeric exactness** (Domain A) | ≥ 95% | Spoken number matches ground truth to the rupee |
| **Term exactness** (Domain B) | **100%** | Every rate, fee, cap matches `card_terms.yaml` exactly |
| **Hallucinated facts** | **0** | Every figure in the answer must trace to `tool_result` — computed or retrieved |
| **No-invention on missing terms** | 100% | 5 questions about undocumented terms must get "I don't have that" |
| **Clarify on underspecified** | 100% | 8 vague questions must trigger `clarify`, never a guess |
| **Out-of-scope refusal** | 100% | 5 off-topic / comparison / advice questions declined, not improvised |

Domain B is held to 100%, not 95%. A miscomputed spend total is embarrassing; a
misquoted fee is something a user might act on financially. The stricter bar is
cheap here because the answer is a dictionary lookup — anything below 100% means a
routing bug, not a hard problem.

### Quality targets

| Metric | Target |
|---|---|
| Intent routing accuracy (right tool chosen) | ≥ 90% |
| **Domain routing accuracy** (transactions vs. terms) | ≥ 95% |
| Argument extraction accuracy (dates, categories) | ≥ 85% |
| `rewards_earned` correctness incl. caps and exclusions | ≥ 95% |
| Merchant name recognition after fuzzy matching | ≥ 90% |
| p50 round-trip latency (button release → audio start) | ≤ 4s |
| p95 round-trip latency | ≤ 7s |

### Judgement metrics (the ones that actually decide the internship)

- **Time to swap data sources:** a competent engineer, given only the README, points
  the bot at a new CSV in under 30 minutes.
- **Failure modes documented before being discovered.** The handover names what
  breaks and why. This is the differentiator — most trial projects ship a demo video;
  shipping a measured list of your own weaknesses reads as engineering judgement.

---

## 9. Known tradeoffs, stated upfront

**Push-to-talk, not streaming.** ~4s round trip instead of ~1.5s, and no interruption
mid-answer. Chosen deliberately: the streaming version doubles the moving parts and
makes correctness harder to verify in three days. It is a swap of the `listen` and
`speak` nodes, not a rewrite. Say this to him explicitly — an unstated limitation
looks like an oversight, a stated one looks like a decision.

**Ten tools, not open-ended querying.** Questions outside the taxonomy get refused.
Narrow and correct beats broad and unreliable when the output is a financial figure
spoken aloud.

**One card, not many.** Multi-card is a `card_id` filter plus a dict of terms files —
maybe two hours. Deferred on purpose: the terms layer is the new and risky part, and
it should be proven correct on one card before being multiplied across several.

**Synthetic data.** Real patterns (seasonality, refunds, EMI, FX, a duplicate charge)
but generated. Even so: masked card identifiers, no PAN anywhere, read-only queries,
no transaction data in logs. The habit is the point.

---

## 10. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| ASR mangles Indian merchant names ("Swiggy" → "Swiggie") | High | Fuzzy match transcript tokens against the merchant list extracted from the data |
| Relative dates misresolved ("last month" on the 1st) | Medium | Dates resolved in Python from a fixed `today`, never by the LLM |
| LLM restates a number with a stray calculation | Medium | Verbalizer prompt forbids arithmetic; eval asserts every figure appears in `tool_result` |
| Streamlit Cloud cold start slows first demo | Medium | Warm it before sending the link; note it in the README |
| **Model recites a reward rate from training instead of the file** | **High** | Planner prompt forbids answering terms from memory; verbalizer receives only `tool_result`; eval asserts every term matches `card_terms.yaml` |
| Fee-schedule vs. fees-charged confusion | Medium | Both phrasings in the eval set; tool docstrings name the distinction explicitly |
| Reward cap logic wrong (points beyond cap still counted) | Medium | Cap and exclusion handling unit-tested with hand-computed cases in `rewards_earned` |
| Scope creep into cross-card comparison | Medium | §4 non-goals; bot refuses; confirm with him if he pushes |

---

## 11. Timeline

| Day | Deliverable | Gate |
|---|---|---|
| **Mon** | Synthetic data + 6 transaction tools | Tools return correct numbers, verified by hand. No LLM yet. |
| **Tue** | `card_terms.yaml` + 4 terms/rewards tools + 55 gold questions + graph | ≥90% on gold set via typed input |
| **Wed** | Streamlit UI, voice in/out, fuzzy merchant matching, deploy | Public URL works on a phone |
| **Thu AM** | Eval report, README, 3-min Loom, send | All hard gates green |

Monday is the day that decides whether Thursday works. If the deterministic layer is
right, the rest is wiring. If it is wrong, no amount of voice polish saves it.

---

## 12. Handover package

1. Live URL (Streamlit Cloud)
2. GitHub repo, 7 files, README with the 30-minute data-swap guide
3. `EVAL_REPORT.md` — metrics table, per-category breakdown, named failure modes
4. 3-minute Loom: one correct answer, one clarification, one refusal, one failure
   mode explained

Showing the failure is the strongest move in the package. It says the numbers in the
report are trustworthy because they were not curated.
