"""
Evaluate the CRAG pipeline end-to-end against a small ground-truth set.

Checks two things per question:
  - routing accuracy : did the graph pick the right tier (docs / docs+incident / web)?
  - answer vs. ground truth : printed side-by-side for manual review

No RAGAS dependency — keeps this project free of the ragas/langchain_community
version conflicts present elsewhere in this environment.
"""

import sys

import pandas as pd
from dotenv import load_dotenv

# Windows terminals often default to cp1252, which can't encode the box-drawing
# and checkmark characters used in the summary output below.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from graph import build_crag_graph
from knowledge_base import EVAL_PAIRS


def run_pipeline_on_dataset(graph) -> list[dict]:
    """Invoke the compiled CRAG StateGraph for every eval question."""
    results = []
    for i, qa in enumerate(EVAL_PAIRS, 1):
        print(f"  [{i}/{len(EVAL_PAIRS)}] {qa['question'][:70]}...")
        state = graph.invoke({"question": qa["question"]})
        results.append({
            "question":        qa["question"],
            "answer":          state.get("answer", ""),
            "context":         state.get("context", ""),
            "ground_truth":    qa["ground_truth"],
            "expected_route":  qa["expected_route"],
            "actual_route":    state.get("source"),
            "overall_verdict": state.get("overall_verdict"),
            "incident_hit":    bool(state.get("incident")),
        })
    return results


def score_routing_accuracy(results: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "question": r["question"],
            "expected_route": r["expected_route"],
            "actual_route": r["actual_route"],
            "correct": r["actual_route"] == r["expected_route"],
        }
        for r in results
    ]
    return pd.DataFrame(rows)


def print_summary(results: list[dict], routing_df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("  CRAG Evaluation Summary — Incident-Aware Customer Support")
    print("=" * 70)

    accuracy = routing_df["correct"].mean()
    print(f"\nRouting accuracy: {accuracy:.0%} "
          f"({routing_df['correct'].sum()}/{len(routing_df)} questions routed to the correct tier)")
    for _, row in routing_df.iterrows():
        mark = "✓" if row["correct"] else "✗"
        print(f"  {mark} {row['question'][:55]:<55} expected={row['expected_route']:<15} actual={row['actual_route']}")

    print("\nPer-question answer vs. ground truth:")
    for i, r in enumerate(results, 1):
        print(f"\n  [{i}] {r['question']}")
        print(f"      route: {r['actual_route']} (expected: {r['expected_route']}) | incident_hit: {r['incident_hit']}")
        print(f"      answer:       {r['answer'][:200]}")
        print(f"      ground_truth: {r['ground_truth'][:200]}")
    print("\n" + "=" * 70)


def main():
    print("── Step 1: Building CRAG graph (vector store + grader + graph) ──────")
    graph = build_crag_graph()

    print("\n── Step 2: Running CRAG pipeline over evaluation questions ──────────")
    results = run_pipeline_on_dataset(graph)

    print("\n── Step 3: Scoring routing accuracy ──────────────────────────────────")
    routing_df = score_routing_accuracy(results)

    print_summary(results, routing_df)

    pd.DataFrame(results).to_csv("eval_results.csv", index=False)
    routing_df.to_csv("routing_scores.csv", index=False)
    print("\n  Results saved to eval_results.csv and routing_scores.csv\n")


if __name__ == "__main__":
    main()
