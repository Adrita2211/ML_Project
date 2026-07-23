"""Relevance grader — the core CRAG step that decides whether retrieved docs
are trustworthy enough to answer from, or whether to fall back to web search.

    [Question & Document]
             |
             v
     GRADE_PROMPT (Injected into the text template)
             |
             v
     Groq LLM (Processes prompt + Pydantic schema definitions)
             |
             v
    [Raw JSON output from LLM]
             |
             v
    [Pydantic Validation] (Ensures strings match Literals, types match)
             |
             v
     GradeResult Object (Returned to you as a clean Python object)
"""

from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

GROQ_MODEL = "llama-3.3-70b-versatile"

GRADE_PROMPT = ChatPromptTemplate.from_template(
    """You are a strict relevance grader for a customer support retrieval system.

Question: {question}

Retrieved document:
{document}

Does this document fully, partially, or not answer the question? Also flag if it
appears potentially outdated or contradicted by more recent information (e.g. it
states timing/behavior claims that could plausibly have changed).

Respond with a verdict:
- "correct": the document fully and reliably answers the question
- "ambiguous": the document partially answers it, or answers it but contains a claim that
  could be outdated
- "incorrect": the document does not answer the question at all
"""
)


class GradeResult(BaseModel):
    verdict: Literal["correct", "ambiguous", "incorrect"] = Field(
        description="Overall relevance verdict for the document"
    )
    # Modeled as a string literal rather than bool: Groq's tool-calling
    # occasionally emits booleans as quoted strings (e.g. "false"), which
    # fails strict JSON-schema validation on their side. A string literal
    # sidesteps that failure mode entirely.
    possibly_outdated: Literal["yes", "no"] = Field(
        description="'yes' if the document contains claims that could be outdated or contradicted by more recent info, else 'no'"
    )
    reasoning: str = Field(description="One sentence explaining the verdict")

    @property
    def is_possibly_outdated(self) -> bool:
        return self.possibly_outdated == "yes"


def build_grader():
    llm = ChatGroq(model=GROQ_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(GradeResult)
    chain = GRADE_PROMPT | structured_llm
    return chain


def grade_document(grader_chain, question: str, document: str) -> GradeResult:
    return grader_chain.invoke({"question": question, "document": document})
