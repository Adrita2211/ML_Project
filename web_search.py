"""Tier 3 fallback — real web search via Tavily, used when internal docs
are graded incorrect/ambiguous."""

import os

from tavily import TavilyClient


def web_search(query: str, max_results: int = 3) -> list[str]:
    """Run a Tavily search and return a list of content snippets."""
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.search(query=query, max_results=max_results)
    return [r["content"] for r in response.get("results", [])]
