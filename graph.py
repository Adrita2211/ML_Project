"""CRAG StateGraph — retrieval -> grading -> incident check -> routing ->
refine/web-fallback -> generation, with a low-confidence escalation guard
and a feedback log for later grader tuning."""

import json
import os
from datetime import datetime
from typing import Optional, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langgraph.graph import END, StateGraph

from grader import GradeResult, build_grader, grade_document
from incident_feed import check_incident
from vector_store import build_vector_store
from web_search import web_search

GROQ_MODEL = "llama-3.1-8b-instant"
LOG_PATH = os.path.join(os.path.dirname(__file__), "feedback_log.jsonl")

REWRITE_QUESTION_PROMPT = ChatPromptTemplate.from_template(
    """Given the conversation history and a follow-up question, rewrite the follow-up
question into a standalone question that contains all context needed to understand it
without the history (resolve pronouns and implicit references like "it", "that",
"the same issue"). If the follow-up is already standalone, return it unchanged. Do not
answer the question — only rewrite it. Return just the rewritten question, no commentary.

Conversation history:
{history}

Follow-up question: {question}

Standalone question:"""
)

REFINE_PROMPT = ChatPromptTemplate.from_template(
    """Given the question and the source text below, extract ONLY the sentences
that are directly relevant to answering the question. Discard everything else.
Return just the extracted sentences, no commentary.

Question: {question}

Source text:
{text}
"""
)

GENERATE_PROMPT = ChatPromptTemplate.from_template(
    """You are a customer support assistant. Answer the question using ONLY the
context below. Do not use outside knowledge and do not invent any information,
incidents, ticket numbers, ETAs, product names, connectors, or step-by-step
instructions that are not explicitly present in the context. If the context does
not contain enough detail to answer the question, say plainly that you don't have
verified information on that and recommend escalating to a human agent — do not
fill the gap with a plausible-sounding guess.

PRECEDENCE RULE: the context will contain a section starting with the literal
marker "[ACTIVE INCIDENT]" if and only if there is a real, currently active
incident relevant to this question. If that exact marker is present, that
information overrides general documentation — mention the incident and its
workaround/ETA FIRST, clearly labeled, before any general instructions. If that
marker is NOT present anywhere in the context, there is no active incident —
do not mention, imply, or speculate about any incident, outage, or known issue
under any circumstances. Simply answer from the general context.

Context:
{context}

Question: {question}

Answer:"""
)


class CRAGState(TypedDict):
    question: str
    chat_history: list[dict]
    standalone_question: str
    docs: list[str]
    grades: list[dict]
    overall_verdict: str
    incident: Optional[dict]
    context: str
    source: str
    web_verdict: Optional[str]
    answer: str


def _build_graph():
    vector_store = build_vector_store()
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    grader_chain = build_grader()
    llm = ChatGroq(model=GROQ_MODEL, temperature=0)
    rewrite_question_chain = REWRITE_QUESTION_PROMPT | llm
    refine_chain = REFINE_PROMPT | llm
    generate_chain = GENERATE_PROMPT | llm

    def rewrite_question(state: CRAGState) -> dict:
        history = state.get("chat_history") or []
        if not history:
            return {"standalone_question": state["question"]}
        # Only the last few turns — enough to resolve references without
        # letting unrelated older turns bias retrieval for the current one.
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
        standalone = rewrite_question_chain.invoke(
            {"history": history_text, "question": state["question"]}
        ).content.strip()
        return {"standalone_question": standalone}

    def retrieve(state: CRAGState) -> dict:
        docs = retriever.invoke(state["standalone_question"])
        return {"docs": [d.page_content for d in docs]}

    def grade(state: CRAGState) -> dict:
        grades = []
        for doc in state["docs"]:
            result: GradeResult = grade_document(grader_chain, state["standalone_question"], doc)
            grades.append(result.model_dump())

        verdicts = [g["verdict"] for g in grades]
        if "correct" in verdicts:
            overall = "correct"
        elif "ambiguous" in verdicts:
            overall = "ambiguous"
        else:
            overall = "incorrect"
        return {"grades": grades, "overall_verdict": overall}

    def check_incidents(state: CRAGState) -> dict:
        return {"incident": check_incident(state["standalone_question"])}

    def route_after_grade(state: CRAGState) -> str:
        return "refine" if state["overall_verdict"] == "correct" else "web_fallback"

    def _incident_block(state: CRAGState) -> str:
        incident = state.get("incident")
        if not incident:
            return ""
        return (
            f"[ACTIVE INCIDENT] Component: {incident['component']} | "
            f"Status: {incident['status']}\n{incident['message']} {incident['eta']}\n\n"
        )

    def refine(state: CRAGState) -> dict:
        kept_docs = [
            doc
            for doc, g in zip(state["docs"], state["grades"])
            if g["verdict"] == "correct"
        ]
        combined = "\n\n".join(kept_docs)
        refined = refine_chain.invoke(
            {"question": state["standalone_question"], "text": combined}
        ).content
        context = _incident_block(state) + refined
        source = "docs+incident" if state.get("incident") else "docs"
        return {"context": context.strip(), "source": source}

    def web_fallback(state: CRAGState) -> dict:
        results = web_search(state["standalone_question"])
        combined = "\n\n".join(results)

        # A real search API almost never returns zero results, even for
        # gibberish or made-up product-specific questions — it just returns
        # loosely/fuzzy-matched pages. Without grading those results too, the
        # generator will confidently answer from irrelevant web content
        # instead of ever reaching the escalation guard. So: grade the
        # combined web content against the question the same way docs are
        # graded, and treat "incorrect" web content as no usable context.
        # "ambiguous" is still included — generic-but-real web content (e.g.
        # a genuine explanation of how SSO works) legitimately grades
        # "ambiguous" rather than a strict "correct", and discarding it
        # entirely caused answerable questions to escalate needlessly.
        # Fabrication risk on weak/irrelevant context is instead handled by
        # GENERATE_PROMPT's explicit "don't invent specifics" instruction.
        web_verdict = "incorrect"
        if combined.strip():
            web_grade: GradeResult = grade_document(grader_chain, state["standalone_question"], combined)
            web_verdict = web_grade.verdict

        context = _incident_block(state)
        if web_verdict != "incorrect":
            context += combined
        source = "web+incident" if state.get("incident") else "web"
        return {"context": context.strip(), "source": source, "web_verdict": web_verdict}

    def route_after_context(state: CRAGState) -> str:
        return "escalate" if not state["context"] else "generate"

    def generate(state: CRAGState) -> dict:
        answer = generate_chain.invoke(
            {"context": state["context"], "question": state["standalone_question"]}
        ).content
        return {"answer": answer}

    def escalate(state: CRAGState) -> dict:
        return {
            "answer": (
                "I'm not confident I have accurate information to answer that. "
                "I'm escalating this to a live support agent who can help further."
            ),
            "source": "escalation",
        }

    def log(state: CRAGState) -> dict:
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "question": state["question"],
            "standalone_question": state.get("standalone_question"),
            "overall_verdict": state.get("overall_verdict"),
            "grades": state.get("grades"),
            "web_verdict": state.get("web_verdict"),
            "incident_hit": bool(state.get("incident")),
            "source": state.get("source"),
            "answer": state.get("answer"),
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return {}

    workflow = StateGraph(CRAGState)
    workflow.add_node("rewrite_question", rewrite_question)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("grade", grade)
    workflow.add_node("check_incidents", check_incidents)
    workflow.add_node("refine", refine)
    workflow.add_node("web_fallback", web_fallback)
    workflow.add_node("generate", generate)
    workflow.add_node("escalate", escalate)
    workflow.add_node("log", log)

    workflow.set_entry_point("rewrite_question")
    workflow.add_edge("rewrite_question", "retrieve")
    workflow.add_edge("retrieve", "grade")
    workflow.add_edge("grade", "check_incidents")
    workflow.add_conditional_edges(
        "check_incidents", route_after_grade, {"refine": "refine", "web_fallback": "web_fallback"}
    )
    workflow.add_conditional_edges(
        "refine", route_after_context, {"generate": "generate", "escalate": "escalate"}
    )
    workflow.add_conditional_edges(
        "web_fallback", route_after_context, {"generate": "generate", "escalate": "escalate"}
    )
    workflow.add_edge("generate", "log")
    workflow.add_edge("escalate", "log")
    workflow.add_edge("log", END)

    return workflow.compile()


def build_crag_graph():
    return _build_graph()
