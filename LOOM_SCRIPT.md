# Loom recording outline — 3 minutes

Companion to `EVAL_REPORT.md` and `README.md` for the S09 handover package
(`PRD.md` §12). Order and emphasis follow `all-specs.md` S09 exactly: a spend
question → the "how it got this" panel → a rewards question with its clause →
**the cross-domain moment (most time here)** → a missing-term gap admission →
one real, already-known failure mode, explained plainly.

Every utterance below was tested live against the current pipeline (`d61bbed`)
while writing this script — none are hypothetical. Exact spoken answers will
vary slightly run to run (the verbalizer is an LLM call, temp 0 but not
literally deterministic in wording), but the tool routed to, the numbers
returned, and the failure demonstrated are all reproducible.

## Before you hit record

- **Warm the app first.** Cold-start (first request after `streamlit run
  app.py` or after Streamlit Cloud wakes a sleeping app) measured at ~6.3s
  end-to-end in `EVAL_REPORT.md` §5.7 — noticeably slower than every other
  turn. Ask it one throwaway question off-camera, then start recording once
  it's warm, so the timings on camera reflect normal operation (p50 ~2s),
  not the cold-start outlier. This is the PRD's own stated mitigation
  (§9/§10) — worth saying out loud on camera if there's time, since it shows
  the tradeoff was a decision, not an oversight.
- Have the sidebar visible throughout — its three groups ("Your spending" /
  "Your card" / "Your rewards") are doing real work teaching the scope of the
  product without narration.
- Decide mic vs. sidebar-button per segment ahead of time (noted per segment
  below) — both exercise the identical real pipeline (`app.py`'s own design:
  the button path skips only the `listen` stage, nothing else), so this is a
  reliability choice for recording, not an honesty tradeoff either way.

---

## 0:00–0:15 — Cold open

**Say:** "This is a voice Q&A app over one credit card's data — you ask a
question out loud, it answers out loud, with a number it either computed from
real transactions or looked up from the card's actual terms. It never lets
the model guess or recall a number — I'll show you exactly why that matters
in a minute."

**Show:** the app's title/one-line description, the mic button, the sidebar.

## 0:15–0:45 — A spend question (Domain A)

**Ask (mic, live):** "How much did I spend last month?"

**Say while it answers:** nothing yet — let the audio play.

**Expect (verified live while writing this script):** *"Last month, you
spent 122,049 rupees across 101 transactions."* (spoken rounded to the
nearest rupee; the underlying `tool_result` is the exact ₹122,048.88) —
matches `PRD.md`'s own worked example almost exactly.

## 0:45–1:05 — Open "How it got this answer"

**Do:** click the expander under the answer.

**Say:** "This is the part that matters most. That number didn't come from
the model doing arithmetic — it called one function, `spend_total`, with the
period `last month`, and a Python function summed the real rows. Here's the
raw result dict it read the number back from — no arithmetic happened inside
the language model at any point."

**Show:** tool name (`spend_total`), args (`{"period": "last month"}`), raw
result dict (`total`, `count`, `period_label`, `avg_txn`).

## 1:05–1:30 — A rewards question, showing the clause (Domain B)

**Ask (sidebar button or mic):** "What's the reward rate on dining?"

**Expect (verified live while writing this script; exact wording varies
slightly run to run, the number and cap don't):** *"You earn 5 reward points
for every Rs. 100 spent on dining and food delivery, with a cap of 2,000
bonus points per calendar month."*

**Say:** "That's not the model remembering a typical card's reward rate —
it's reading straight from `card_terms.yaml`." **Open the panel** and point
at the `clause` field: "This is the exact sentence in the terms file. The
bot speaks this near-verbatim, on purpose — a paraphrase of a fee condition
is how you accidentally change its meaning."

## 1:30–2:20 — The cross-domain moment: spend the most time here

**Ask (mic, live — this is the centerpiece):** "How many points did I earn
last month?"

**Expect:** *"You earned 2,912 points last month."*

**Say, while the panel is open:** "This is the single most interesting thing
this build does, and neither a statement app nor a terms PDF answers it
today. It's one tool, `rewards_earned`, and it's doing three things in plain
Python: pulling every real transaction from last month, applying this card's
actual category rates and monthly caps from the terms file to each one, and
excluding the categories that don't earn points at all — cash advances, fees.
None of that is the language model inferring anything; it's a deterministic
calculation over two real data sources at once." **Point at `by_category` and
`capped_categories` in the panel** — if a capped category shows up, call it
out: "and if I'd hit a monthly cap that month, it would show up right here,
by month, not averaged across a whole quarter — that's a detail this build
got right on the first real attempt and then verified by hand against a
month that actually breaches it (see the eval report)."

*(Optional, if time allows: "This exact question was also the one that broke
intermittently during testing — caught by the eval harness before it shipped,
fixed, and now verified clean across more than a dozen live runs. It's in the
eval report because a build that hides its own bug history is less credible
than one that shows the harness catching a real one.")*

## 2:20–2:40 — A missing-term question: the gap admission

**Ask (mic or sidebar):** "What's the railway booking surcharge on this
card?"

**Expect (verified live while writing this script, wording varies slightly
run to run):** *"I don't have railway booking surcharge documented in this
card's terms. I can tell you about annual, card replacement, and cash
advance fee instead."*

**Say:** "This charge type is deliberately left out of the terms file, on
purpose, specifically to test this: when a term isn't documented, the bot
says so instead of reciting something plausible it picked up in training.
That's the single highest-risk failure mode for this kind of product, and
it's the one this build refuses to get wrong."

*(Honesty note, not for the recording script itself: this exact question
was retested 19 times while preparing this handover and correctly admitted
the gap 18 times — once it misfired and declined the question as
out-of-scope instead. That's rare enough not to worry about live, but if it
happens on camera, that is also a real, honest moment — just say so and
re-ask once, the same way you'd narrate any other real failure in this
script. See `EVAL_REPORT.md` §5.8 for the full data point.)*

## 2:40–3:00 — One known failure mode, explained plainly

**Ask (mic or sidebar):** "How much did I spend on food and travel last
month?"

**Expect (verified live while writing this script):** *"In July, you spent
18,159 rupees on food and dining across 22 transactions."* — food/dining
only; travel silently dropped, no mention that half the question was
ignored.

**Say:** "And here's a real limitation, not a hidden one — it's in the eval
report. This asked about two categories in one breath, and v1 only ever
makes one tool call per turn, on purpose, to keep the correctness story
simple. So it silently answered the food half and dropped travel, with no
signal that it did that." **Open the panel:** "You can see it right here —
the args only show `food_dining`, even though the question named two
categories. The fix is on the roadmap, not shipped: detect this pattern
before planning and ask which one you meant, rather than silently picking."

**Close:** "Every number in this demo traces back to either a real
transaction or a real line in the terms file — and the failure I just showed
you is a real one I found by testing this build honestly, not a curated
gap. That's the whole point of shipping the eval report alongside the video."

---

## If you have more than 3 minutes

Two more real, already-documented failure modes worth a follow-up cut if
there's appetite (`EVAL_REPORT.md` §5.1 and §5.5):

- **"How much did I spend last quarter?"** dead-ends with an apology, while
  the *identical* phrase works fine for "How many points did I earn last
  quarter?" — a real vocabulary gap between the two domains' date parsers,
  not a general date-handling problem (genuinely ambiguous phrases like
  "recently" correctly trigger a clarifying question instead).
- **"What's the interest rate on this card if I don't pay my full bill?"**
  gets answered confidently with the *cash-advance* interest rate (a real
  number, really in the terms file — not a hallucination) instead of
  admitting there's no documented rate for a revolving purchase balance.
  Arguably the most important finding in the whole eval report, because
  nothing in the current gold set catches it — worth narrating carefully if
  included, since it's subtler than the others to explain in one line.
