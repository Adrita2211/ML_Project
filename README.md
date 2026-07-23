# CRAG — Incident-Aware Customer Support

Corrective RAG (CRAG) demo for a customer support bot that must not give
stale/wrong answers when there's an active product incident affecting the
topic being asked about.

## Architecture

```
retrieve (FAISS, Tier 1 docs)
    |
grade (Groq LLM-as-judge: correct / ambiguous / incorrect + outdated flag)
    |
check_incidents (Tier 2, mock live status feed — always runs)
    |
route -----------------------------------
    | overall grade == correct           | grade == ambiguous/incorrect
    v                                     v
refine (strip irrelevant content,   web_fallback (Tavily search, Tier 3,
        prepend incident if found)         prepend incident if found)
    |                                     |
    -----------------> route -------------
                          |
              context empty?  --- yes ---> escalate (hand off to live agent)
                          | no
                          v
                      generate (incident info takes precedence over docs)
                          |
                          v
                 log (append to feedback_log.jsonl)
```

Tier 2 (the mock incident feed) is checked unconditionally, independent of
the doc grade — a doc can be topically perfect but still wrong right now if
there's an active incident on that component. `generate` is instructed to
always surface incident info first when present.

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # then fill in GROQ_API_KEY and TAVILY_API_KEY
python main.py
```

## Try these queries to exercise each branch

- `"How do I reset my password?"` — clean doc match, no incident → answers from Tier 1 docs only.
- `"How does SSO login work?"` — matches the SSO doc (which claims fast, reliable login) **and** the mock active incident (`incident_feed.py`) flags the auth gateway as degraded → answer should lead with the incident callout, not the stale "completes in under 2 seconds" claim.
- `"My exported CSV file shows garbled/broken special characters when I open it in Excel — why does that happen?"` — a plausible follow-on to the Data Export doc, but the specific issue (encoding) isn't covered by the mock docs → triggers Tavily web search fallback.

> Note on the Tier 3 demo query: it's a generic, widely-documented issue
> (CSV/Excel character encoding) rather than something about "this"
> fictional product's internal policies (e.g. its refund terms). Tavily
> searches the actual live internet, and since this mock company doesn't
> exist there, a company-specific fallback query would return irrelevant
> real-world noise (some other company's policy) instead of a meaningful
> grounded answer. A generic-but-realistic support issue, by contrast, is
> genuinely documented across the web, so Tavily's results are actually
> relevant. In a real deployment, Tier 3 should still primarily point at
> your own public help center/FAQ or curated ticket history for anything
> company-specific — open web search is best reserved for exactly this
> kind of generic, product-agnostic troubleshooting question.

## Files

- `knowledge_base.py` — mock product docs (Tier 1 corpus)
- `incident_feed.py` — mock live incident/status-page API (Tier 2)
- `vector_store.py` — FAISS + local HuggingFace embeddings
- `grader.py` — structured-output relevance grader (Groq)
- `web_search.py` — Tavily wrapper (Tier 3)
- `graph.py` — the LangGraph `StateGraph` wiring everything together
- `main.py` — CLI loop
- `feedback_log.jsonl` — created at runtime; one JSON record per query for later grader tuning
