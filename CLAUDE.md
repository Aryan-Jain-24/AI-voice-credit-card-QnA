# CLAUDE.md — Voice Q&A over Credit Card Data

Orientation file for any Claude Code session working in this repo. Full detail lives
in `PRD.md` (why, scope, success metrics) and `all-specs.md` (ten build specs,
S00–S09). Read those first — this file is a distilled index, not a replacement.

## Current state

Pre-code. Only `PRD.md`, `all-specs.md`, this file, `.claude/agents/`, and an empty
`venv/` exist. **S00 (repo skeleton) has not been executed** — no `app.py`,
`graph.py`, tools, `requirements.txt`, or `.gitignore` exist yet. This session's
scope was planning docs only; scaffolding the real repo is the next step.

## What this is

A web app: hold a button, ask a question about your credit card in plain speech,
hear a spoken answer with the correct number in it. v1 is one card, one cardholder,
two domains — transaction history (computed) and card terms (retrieved) — plus the
cross-domain case of applying the reward schedule to actual spend.

## The one principle everything follows from

> **The language model never produces a fact. It only routes to one and reads it
> aloud.**

- **Transactions:** the LLM never does arithmetic. It emits a typed tool call; a
  deterministic Python function computes the number; the verbalizer reads it back
  without recalculating.
- **Card terms:** the LLM never recalls, it looks up. Every rate/fee/cap comes from
  `card_terms.yaml` via a tool, and the answer carries the `clause` it came from. If
  a term isn't in the file, the bot says so instead of filling the gap.
- No free-form text-to-SQL. No vector store. Ten typed tools, not open-ended
  querying — narrow and correct beats broad and unreliable for a financial figure
  spoken aloud.

## Non-goals (v1)

Cross-card comparison, multi-card, streaming/interruptible audio, auth/multi-user,
real PII data, financial advice, native mobile. See PRD §4 for the why behind each.

## Architecture snapshot

```
[mic] ─► listen ─► plan ─► query ─► verbalize ─► speak ─► [audio out]
                     │                              ▲
                     └────────► clarify ─────────────┘
```

| Node | Does | Model / lib |
|---|---|---|
| `listen` | audio → transcript | OpenAI `whisper-1` |
| `plan` | transcript → one typed tool call, or clarify | `gpt-4o-mini` + `.bind_tools()` |
| `query` | executes tool over pandas DataFrame | LangGraph `ToolNode` |
| `verbalize` | result dict → one spoken sentence | `gpt-4o-mini`, temp 0 |
| `speak` | text → mp3 | OpenAI `tts-1` |

State is 6 fields, no hidden state (PRD §7.2). Transactions live in pandas over a
CSV (~2,000 rows); card terms live in a hand-authored `card_terms.yaml` (~40 facts,
every leaf that could be spoken carries a `clause` string). Schema swap path:
`real_data.csv ─► mapping.yaml ─► canonical DataFrame ─► tools (unchanged)`.

## Config / environment

- `OPENAI_API_KEY` from `.env` locally, from Streamlit secrets in deployment. Never
  hardcoded, never committed. `.env` goes in `.gitignore` from the first commit.
- Stack: LangGraph `StateGraph`, Streamlit (`st.audio_input`), `whisper-1`,
  `gpt-4o-mini` (planner + verbalizer), `tts-1`, pandas + CSV, Streamlit Community
  Cloud for deploy.

## Build order and spec ownership

```
S00 Skeleton
 ├─ S01 Synthetic txns ──► S02 Loader+mapping ──► S03 Transaction tools ─┐
 └─ S03B Card terms + terms/rewards tools ────────────────────────────────┤
                                                                          ▼
                                                                   S04 Gold eval
                                                                          │
                                             S05 Planner+graph ◄──────────┘
                                                       │
                                             S06 Verbalizer
                                                       │
                                   S07 Voice I/O ──► S08 UI ──► S09 Handover
```

| Spec | Deliverable | Owning subagent |
|---|---|---|
| S00 | repo skeleton, config | (orchestrator — no dedicated subagent) |
| S01 | `generate_data.py`, `data/transactions.csv` | `data-generator` |
| S02 | `data_loader.py`, `mapping.yaml` | `data-loader` |
| S03 | `tools_txn.py` (6 tools) | `txn-tools-builder` |
| S03B | `card_terms.yaml`, `tools_card.py` (4 tools) | `card-terms-builder` |
| S04 | `evals/gold_questions.json`, `eval.py` | `eval-harness-builder` |
| S05 | `graph.py` planner node + assembly | `graph-engineer` |
| S06 | verbalizer node | `graph-engineer` |
| S07 | `voice.py`, fuzzy merchant correction | `voice-ui-engineer` |
| S08 | `app.py`, Streamlit deploy | `voice-ui-engineer` |
| S09 | `EVAL_REPORT.md`, `README.md`, Loom outline | `handover-writer` |

**Hard rule from the spec:** do not start S07 (voice) until S05+S06 pass their gate
via text input. Debugging a wrong number through a microphone costs ~4x what it
costs through a text box.

## Hard gates (must pass before shipping — PRD §8)

| Metric | Target |
|---|---|
| Numeric exactness (Domain A) | ≥ 95% |
| Term exactness (Domain B) | **100%** |
| Hallucinated facts | **0** |
| No-invention on missing terms | 100% |
| Clarify on underspecified | 100% |
| Out-of-scope refusal | 100% |

Domain B is held to 100%, not 95% — it's a dictionary lookup, so anything short of
100% is a routing bug, not a hard problem.

## Subagents

Defined in `.claude/agents/`. Each carries the full spec-derived constraints for its
phase (docstring rules, done-when gates, things it must never do) so it doesn't need
to re-derive them from `PRD.md`/`all-specs.md` from scratch each time — though it
should still consult those files for anything not covered here.

- **data-generator** — S01: synthetic transaction CSV + generator, with the
  realism scenarios (subscriptions, refunds, EMI, FX, duplicate charge, cap-breach
  months) required for later specs to have real edge cases to hit.
- **data-loader** — S02: mapping-driven canonical loader; proves the schema-swap
  promise.
- **txn-tools-builder** — S03: the six deterministic transaction tools.
- **card-terms-builder** — S03B: `card_terms.yaml` + the four terms/rewards tools,
  including the cross-domain `rewards_earned` calculation.
- **eval-harness-builder** — S04: the 55-question gold set and `eval.py`, built
  before the planner exists so questions don't bend toward what the model already
  handles.
- **graph-engineer** — S05 + S06: LangGraph assembly, planner node, verbalizer
  node. Owns the two prompts where hallucination risk is highest.
- **voice-ui-engineer** — S07 + S08: STT/TTS wrappers, fuzzy merchant correction,
  Streamlit UI, deploy.
- **handover-writer** — S09: eval report, README with the 30-minute swap guide,
  Loom script.

## Working conventions

- Never let an LLM node compute a number or recall a card term — everything routes
  through a typed tool.
- Correctness first, language second, voice last — don't build ahead of a passing
  gate.
- Test expectations must be hand-computed. An expectation generated by the same code
  under test proves nothing.
- Every transaction/terms tool returns a flat dict of scalars (plus `period_label`
  where relevant) — never a DataFrame, never prose.
- Relative dates are resolved in Python (`resolve_period`), never by the LLM.
