# Voice Q&A over Credit Card Data

Hold a button, ask a question about your credit card in plain speech, hear a
spoken answer with the correct number in it.

```
"How much did I spend on food last month?"
  -> "You spent 8,240 rupees on food and dining in July, across 22 transactions."

"What's the reward rate on dining?"
  -> "You earn 5 points per hundred rupees on dining, capped at 2,000 points a month."

"How many points did I earn last month?"
  -> "You earned 2,912 points last month."
```

v1 is one card, one cardholder, two domains — transaction history (computed)
and card terms (retrieved) — plus the cross-domain case of applying the
reward schedule to actual spend. The one rule everything follows from:

> **The language model never produces a fact. It only routes to one and reads
> it aloud.** Transactions are never summed by the LLM — a typed tool call
> triggers a deterministic Python computation. Card terms are never recalled
> from the model's training — every rate, fee, and cap is read from
> `card_terms.yaml` at call time and spoken from its `clause` field.

Full detail: `PRD.md` (why, scope, success metrics), `all-specs.md` (the ten
build specs), `EVAL_REPORT.md` (current numbers against every target, plus
known failure modes found by directly testing this build, not guessed at),
`LOOM_SCRIPT.md` (a 3-minute recording outline covering the same ground live).

---

## Architecture

```
                    ┌───────────────────────────┐
                    │                           ▼
  [mic] ──► listen ──► plan ──► query ──► verbalize ──► speak ──► [audio out]
                        │                                ▲
                        └────────► clarify ──────────────┘
```

| Node | Does | Model / lib |
|---|---|---|
| `listen` | audio bytes → transcript, then merchant fuzzy-correction | OpenAI `whisper-1` + `rapidfuzz` |
| `plan` | transcript → exactly one typed tool call, or `ask_clarification` / `refuse` | `gpt-4o-mini`, `.bind_tools()`, `tool_choice="required"`, temp 0 |
| `query` | executes the chosen tool over a pandas DataFrame or `card_terms.yaml` | plain Python, `LangGraph` node |
| `verbalize` | result dict → one spoken sentence, numbers copied verbatim | `gpt-4o-mini`, temp 0, with a deterministic draft-and-validate fallback |
| `speak` | text → mp3 | OpenAI `tts-1`, voice `nova` |

**Two compiled graphs share the same five node functions**, deliberately:

- `graph.py` builds a **text-only** graph (`plan → query/clarify → verbalize`)
  and exposes `run_pipeline(utterance: str) -> dict`. This is what `eval.py`
  scores — fast, no audio cost, no `listen`/`speak` in the loop.
- `voice.py` builds a **second**, separate compiled graph
  (`listen → plan → query/clarify → verbalize/clarify → speak`) out of the
  exact same `plan_node`/`query_node`/`clarify_node`/`verbalize_node`
  functions `graph.py` defines, imported unmodified, plus its own
  `listen_node`/`speak_node`. `app.py` (the Streamlit UI) drives this one via
  `run_voice_pipeline(audio_bytes) -> dict`.

Neither graph is a copy of the other's logic — they're two different wirings
of one shared node set, so a planner/verbalizer fix in `graph.py` is
automatically live in the voice path with no duplication.

**Ten typed tools, not open-ended querying** — six over transactions
(`spend_total`, `spend_by_category`, `top_merchants`, `compare_periods`,
`find_transactions`, `recurring_charges`), four over card terms
(`card_rewards`, `card_fees`, `card_offers`, `rewards_earned` — the
cross-domain one, which applies the reward schedule to real transactions),
plus `ask_clarification` and `refuse` bound as tools too, so routing to "I
need more information" or "that's out of scope" is the same uniform
mechanism as routing to a real answer, not a separate string-matching path.

**Data layer:**

```
Transactions:  pandas DataFrame over data/transactions.csv (~2,000 rows)
Card terms:    card_terms.yaml, hand-authored, ~40 facts, read fresh every call
```

Not DuckDB, not Postgres, not a vector store — at this size every aggregation
is sub-millisecond regardless, and a dictionary lookup is exact where a
similarity search can return the wrong clause. See `PRD.md` §3 for the full
argument.

**State** (`graph.py`'s `State` TypedDict) — 6 fields, no hidden state:
`transcript`, `tool_call`, `tool_result`, `answer_text`, `audio_out`,
`needs_clarification` (`audio_in` is added by the voice graph). Every node
reads some of these fields and writes one.

---

## Setup — 5 commands

```bash
python -m venv venv
venv\Scripts\activate                    # Windows; `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env                   # Windows; `cp .env.example .env` elsewhere — then edit in your OPENAI_API_KEY
streamlit run app.py
```

That opens the app at `http://localhost:8501`. Type or record a question, or
click one of the sidebar's example questions. Open "How it got this answer"
under any response to see the exact tool call and raw result dict the answer
came from — that panel is the whole "the LLM never computes a number" claim
made visible instead of merely asserted.

**Deployment status:** this repo is deploy-ready (`app.py` is complete and
passes every gate locally, both via text and via the mic) but has **not**
been pushed to Streamlit Community Cloud yet — connecting the GitHub repo at
share.streamlit.io and adding `OPENAI_API_KEY` under Settings → Secrets are
manual steps that still need to happen. There is no live URL to share until
that's done; don't take one on faith from an older doc or message.

---

## The 30-minute data-swap guide

This is the part that matters most: pointing the whole app at a different
card's real transaction export and real terms document, touching **two
files and zero Python**. Everything downstream — all ten tools, the planner,
the verbalizer — reads only the six canonical transaction fields and
`card_terms.yaml`'s key structure; neither file cares what your original
data looked like.

### Part A — transactions, via `mapping.yaml` (~10–15 min)

`mapping.yaml` is the *only* place a source file path or a real column name
is allowed to appear. Nothing else in the repo should ever be edited to
change data sources.

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

1. **Put your CSV export somewhere under the repo** (or reference it by
   absolute path) — e.g. `data/real_transactions.csv`.
2. **Edit `mapping.yaml`:** set `source:` to that path, and set each of the
   six `fields:` entries to your CSV's actual column name for that concept.
   All six are required — `load_transactions()` will refuse to guess.
3. **Check the `amount` sign convention:** canonical `amount` is *signed* —
   positive = a purchase, negative = a refund. If your export uses unsigned
   amounts with a separate transaction-type/flag column, that's a
   preprocessing step on your CSV before pointing `source:` at it (a mapping
   file can rename columns, it can't invert a sign based on another column).
   Currency-formatted amounts ("₹1,234.50") are handled automatically —
   `data_loader.py` strips `₹`/`$`/commas before coercing to float.
4. **Category values, and why they matter beyond just grouping:**
   `spend_total`, `spend_by_category`, `top_merchants`, `compare_periods`,
   `find_transactions`, and `recurring_charges` work with *any* category
   strings your data happens to contain — they just group and filter on
   whatever's present, no canonical list required. **But** `card_rewards`
   and `rewards_earned` only apply a category's specific rate/cap when the
   category string is a byte-exact match to a key under
   `card_terms.yaml`'s `rewards.category_rates` (the 12 canonical names:
   `food_dining, groceries, fuel, travel, shopping, entertainment,
   utilities, health, education, cash_advance, fees_interest, other`).
   Anything else silently earns the flat `base_rate` with no cap — not
   wrong, but probably not what you want for a category that should have
   its own rate. If your source's category taxonomy differs, translate it
   to these 12 (or a subset of them) as part of preparing the CSV, or add
   matching keys to `card_terms.yaml` (Part B) for whatever categories your
   data actually uses.
5. **Sanity-check the load** before running anything else:
   ```bash
   python -c "from data_loader import load_transactions; df = load_transactions(); print(len(df), 'rows'); print(df.head()); print(sorted(df['category'].unique()))"
   ```
   A `MappingError` here names both the canonical field and the exact
   `mapping.yaml` key to fix — that error message *is* the debugging guide,
   there's nothing else to go read.
6. **(Optional) Update the merchant list for voice.** `voice.py` imports
   `ALL_MERCHANTS` from `generate_data.py` for two things: biasing Whisper's
   transcription via its `prompt` parameter, and the fuzzy-correction
   fallback for mangled merchant names. `generate_data.py` itself never
   needs to run against your real data — only its module-level
   `ALL_MERCHANTS` list is imported — but if you want merchant-name voice
   correction to be meaningful for *your* card's merchants, replace that
   list with your own real merchant names. Skippable if voice accuracy on
   merchant names isn't a priority for your swap.

### Part B — card terms, via `card_terms.yaml` (~10–15 min)

Replace the file's contents with your real card's schedule, keeping the same
top-level shape (`tools_card.py` reads these keys, not the values, so a
different fee structure needs no code change):

```yaml
card:
  name: "..."
  network: "..."
  issuer: "..."
fees:
  annual: {amount_inr: ..., waiver_spend_inr: ..., clause: "..."}
  forex_markup: {pct: ..., clause: "..."}
  late_payment: [{min_due_inr: ..., max_due_inr: ..., amount_inr: ..., clause: "..."}, ...]
  # ... any other fee_type keys your card actually documents
rewards:
  base_rate: {points_per_100: ..., clause: "..."}
  category_rates:
    food_dining: {points_per_100: ..., monthly_cap_points: ..., clause: "..."}
    # ... one entry per category your card gives a distinct rate to
  excluded_categories: [cash_advance, fees_interest]
  redemption: {value_per_point_inr: ..., clause: "..."}
offers:
  - {merchant: "...", category: "...", benefit: "...", valid_until: "YYYY-MM-DD"}
```

1. **Keep every leaf that should be spoken carrying a `clause` string** — the
   verbalizer speaks `clause` near-verbatim, not a paraphrase it constructs.
   A number with no `clause` has nothing grounded for the bot to say about
   it.
2. **Category keys under `rewards.category_rates` and
   `rewards.excluded_categories` must exactly match the category strings
   your transaction data actually uses** (see Part A step 4) — a typo here
   doesn't error, it silently zeroes out that category's reward calculation,
   because no transaction row will ever match the mistyped key.
3. **It's fine to leave a fee type out entirely.** `card_fees(fee_type=...)`
   for an undocumented type returns `{"found": false, ...}` and the bot says
   plainly that it doesn't have that term — this is a feature (the "admit a
   gap" behavior), not something to work around by inventing placeholder
   entries.
4. **No code path re-reads `card_terms.yaml` at import time or caches it
   stale** — it's parsed fresh on every tool call, so editing it takes
   effect on the very next question, no restart required (a fresh CSV via
   `mapping.yaml` *does* need a Streamlit restart, or a call to
   `load_transactions.clear()`, since that loader is `@st.cache_data`).

### Prove it — run tests, but know what you're actually proving

This guide's claims below were checked by actually doing the swap once
(a throwaway CSV with renamed columns, `mapping.yaml` repointed at it, tests
re-run, then reverted) rather than assumed from reading the code — that dry
run surfaced one real gotcha in `test_data_loader.py` worth knowing up front,
covered below rather than glossed over.

```bash
pytest test_data_loader.py -q
```

Three of this file's five tests build their own self-contained temp
CSV + mapping file per test and don't care what the real `mapping.yaml`
points at — these stay green no matter what: `test_missing_field_declaration_names_field_and_key`,
`test_field_pointing_at_missing_column_names_both`,
`test_amount_coercion_handles_currency_formatting`.

**The other two do read the literal repo-root `mapping.yaml` directly, and
will go red once you repoint it — expected, not a sign anything broke:**
`test_loads_real_data_with_canonical_schema` asserts `len(df) >= 1800` among
other things specific to this repo's synthetic dataset;
`test_schema_swap_promise_identical_canonical_output` loads
`mapping.yaml`'s current target as its own baseline to diff against. Once
`mapping.yaml` points at your data, both are comparing against (or
asserting facts about) the wrong dataset — that's them doing their job
correctly on stale assumptions, not a bug in your swap.

```bash
pytest -q
```

Running the **full** suite is worth doing for visibility, but expect it to
go substantially red, and don't read that as your swap having broken
something. Most of `test_tools_txn.py` and `test_tools_card.py`'s numeric
assertions are **hand-computed literal values pinned to this repo's
placeholder synthetic data and placeholder `card_terms.yaml`** (e.g. "last
month's total is exactly ₹122,048.88") — by design, per this project's own
testing rule that an expectation generated by the same code under test
proves nothing. The moment you point either file at different content,
those specific literals stop matching, correctly. What that leaves you
with, concretely:

- **Stay green, dataset-agnostic:** the 3 self-contained `test_data_loader.py`
  tests named above; the structural/"smoke" tests —
  `TestToolWrappersEndToEnd` in `test_tools_txn.py`, and every
  `*_tool_invoke_smoke` test in `test_tools_card.py` — which check dict
  shape (keys, types) rather than pinned numbers.
- **Expected to go red, and that's fine:** the 2 `test_data_loader.py` tests
  named above, plus anything in `test_tools_txn.py`/`test_tools_card.py`
  asserting a specific rupee figure, point total, or clause string. These
  need their expected values hand-recomputed against your real data/terms
  if you want durable regression coverage going forward — genuinely useful
  follow-up work, but **not part of the 30-minute swap**, and red here does
  not mean the swap failed.

If you want a single fast go/no-go check instead of reading through
`pytest -q`'s full output, the sanity-check one-liner in Part A step 5
(load the data, print the row count and category list) plus a quick
`streamlit run app.py` and asking one real question is the more direct
proof — the tests above are regression coverage, not the swap's actual
acceptance test.

**Done.** `streamlit run app.py`, ask it a question about the new data.

---

## Testing and eval

```bash
pytest -q            # 128 tests, fully offline and deterministic -- no OPENAI_API_KEY needed at all
python eval.py        # 55-question gold set, live against the real OpenAI API -- needs OPENAI_API_KEY
```

(Verified directly: `pytest -q` passes 128/128 with `OPENAI_API_KEY` unset entirely.
`voice.py`'s `transcribe()`/`synthesize()` validate their input and raise before
ever constructing an OpenAI client, so their two input-validation tests need no
key or network either.)

`eval.py` is the planner's and verbalizer's real regression net — see
`EVAL_REPORT.md` §0 for why there's no separate `test_graph.py`, and for a
worked example of it catching a real bug before ship.

---

## Repo layout

```
app.py               Streamlit UI (S08)
graph.py              LangGraph text-only assembly: planner + verbalizer nodes (S05/S06)
voice.py               STT/TTS wrappers, merchant fuzzy-correction, voice-wrapped graph (S07)
tools_txn.py           6 transaction tools + resolve_period (S03)
tools_card.py           4 card-terms/rewards tools, incl. rewards_earned (S03B)
data_loader.py          mapping.yaml-driven canonical loader (S02)
generate_data.py        synthetic transaction generator + merchant dictionary (S01)
mapping.yaml             <- edit this to swap transaction data sources
card_terms.yaml           <- edit this to swap the card's terms
eval.py                   55-question gold-set harness (S04)
evals/gold_questions.json
data/transactions.csv
tests/, test_*.py         pytest suites (128 tests total)
EVAL_REPORT.md            current metrics vs. every PRD §8 target, known failure modes
PRD.md, all-specs.md      product requirements and the ten build specs
```
