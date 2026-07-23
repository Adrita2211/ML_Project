"""Tier 3 fallback — real web search via Tavily, used when internal docs
are graded incorrect/ambiguous."""

import os

from tavily import TavilyClient


def web_search(query: str, max_results: int = 3) -> list[str]:
    """Run a Tavily search and return a list of content snippets.

    search_depth="advanced" matters here: "basic" depth was observed to
    return generic/irrelevant results (e.g. dictionary definitions of a
    stray word in the query) for ordinary support questions, which the
    grader then correctly rejects as incorrect — starving Tier 3 of any
    usable content it should have found.
    """
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.search(query=query, max_results=max_results, search_depth="advanced")
    return [r["content"] for r in response.get("results", [])]
