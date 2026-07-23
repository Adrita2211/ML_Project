"""CLI entry point for the CRAG incident-aware support demo."""

import sys

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from graph import build_crag_graph  # noqa: E402  (must load env vars first)


def main():
    print("Building CRAG graph (loading embeddings + vector store)...")
    graph = build_crag_graph()
    print("Ready. Type a support question (or 'quit' to exit).\n")

    while True:
        question = input("You: ").strip()
        if not question:
            continue
        if question.lower() in {"quit", "exit"}:
            break

        result = graph.invoke({"question": question})

        print(f"\n[route: {result.get('source')} | doc grade: {result.get('overall_verdict')} "
              f"| web grade: {result.get('web_verdict')} | incident: {bool(result.get('incident'))}]")
        print(f"Assistant: {result['answer']}\n")


if __name__ == "__main__":
    main()
