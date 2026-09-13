"""Opt-in live verifier controls using synthetic evidence, not real video claims.

Run: .venv/bin/python tests/evaluate_verifier_controls.py
Consumes OpenAI credits. Does not search, import, or modify the video library.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge.answers import verify_answer
from knowledge.providers import OpenAIJSON
from knowledge.server import load_settings


def main():
    load_settings()
    cases = [
        ("qualified_paraphrase", "Can this help my team?", "This approach may help some teams; it does not guarantee success.",
         "The method can help some teams, but success is not guaranteed.", None, True),
        ("invented_guarantee", "Can this help my team?", "This approach may help some teams; it does not guarantee success.",
         "This method guarantees success for every team.", None, False),
        ("invented_history", "Online sales stopped growing. Should I approach stores?", "We opened a shop. Sales increased. Rent was expensive.",
         "The brand increased sales by opening a shop after its online sales stopped growing.", None, False),
        ("personal_cause", "My colleague repeats mistakes. Why?", "Some people repeat familiar patterns linked to past experiences.",
         "Your colleague repeats mistakes because of childhood trauma.", None, False),
        ("unsupported_summary", "Can this help my team?", "This approach may help some teams; it does not guarantee success.",
         "This method may help some teams.", "Success is guaranteed for every team.", False),
    ]
    llm, rows = OpenAIJSON(), []
    for name, question, quote, text, summary, expected in cases:
        citation = {"url": "https://example.invalid/synthetic-evidence", "title": "Synthetic test evidence", "quote": quote}
        if summary:
            citation["summary"] = summary
        audit = {}
        actual = verify_answer({"points": [{"text": text, "citations": [citation]}]}, question, llm, audit)
        rows.append({"id": name, "expected": expected, "actual": actual, "passed": actual == expected,
                     "audit": audit, "usage": llm.last_usage})
        print(name, "PASS" if actual == expected else "FAIL", flush=True)
    path = Path("data/accuracy-review/verifier-controls.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": llm.model_name, "cases": rows}, indent=2) + "\n")
    if not all(row["passed"] for row in rows):
        raise SystemExit("Some verifier controls failed; review before claiming an improvement.")


if __name__ == "__main__":
    main()
