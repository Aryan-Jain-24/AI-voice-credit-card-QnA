"""Eval harness — built out in S04.

Scores the system against evals/gold_questions.json: intent accuracy, domain
routing accuracy, argument accuracy, numeric/term exactness, hallucination
check, gap-admission/clarify/refusal precision, and latency p50/p95.

See all-specs.md S04 and .claude/agents/eval-harness-builder.md.
"""
