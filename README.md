# Voice Q&A over Credit Card Data

Hold a button, ask a question about your credit card in plain speech, hear a
spoken answer with the correct number in it.

This repo is mid-build (currently at the S00 skeleton stage). The full
README — architecture diagram, 5-command setup, and the 30-minute data-swap
guide — lands as part of the S09 handover spec. Until then, the source of
truth is:

- `PRD.md` — product requirements, scope, success metrics
- `all-specs.md` — the ten build specs (S00–S09), in build order
- `CLAUDE.md` — project index, kept up to date as specs complete

## Quickstart (skeleton only — most of the app is not built yet)

```bash
python -m venv venv
venv\Scripts\activate        # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env       # then add your OPENAI_API_KEY
streamlit run app.py
```

This should open a page that says "hello" and confirms the API key loaded
from the environment. That's the entire S00 gate — everything else (data,
tools, the graph, voice, the real UI) is built out spec by spec per
`all-specs.md`.
