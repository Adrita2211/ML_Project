"""
Pure logic for the deviation-case workflow (no AWS calls, unit tested).

The workflow lets AgentCore agents *propose* and keeps everything that must
be trustworthy in deterministic code, following the pattern AWS describes for
Step Functions + AgentCore: agents propose, a deterministic validator checks
before anything is saved or approved, and no agent state writes to a system.

  build_context  what the agents are shown: the deviation facts, this
                 contract's clauses, and the approved playbook rows. Retrieval
                 is deterministic (metadata filter) and happens here, not by
                 the agent, so an agent can't be steered into fetching or
                 skipping something.
  assemble       turns the agents' raw text into the saved result. It parses
                 defensively, applies the breach/financial-action guardrail,
                 and takes approval flag, channel, evidence and do-not-do from
                 the playbook row - never from model text. Anything rejected
                 falls back to the approved template and is reported.
"""
import json
import re
from decimal import Decimal

STATUS_DATA_QUALITY = "Route to data steward"

FORBIDDEN = re.compile(
    r"(confirmed breach|is in breach|has breached|in breach of|declare[sd]?\s+(a\s+)?breach|"
    r"withhold|offset (the )?rebate|terminate the (agreement|contract)|legal remedy)",
    re.IGNORECASE,
)
MAX_ACTION_CHARS = 1500
# Wording that presents contract TEXT as evidence. Checked in code, not by the verifier model: a small model
# asked to police wording contradicted itself on the first real run.
OVERCLAIM = re.compile(r"\bcontract\s+(explicitly\s+|clearly\s+)?(states|stipulates|specifies|says)\b", re.IGNORECASE)


def to_plain(value):
    """DynamoDB Decimals and sets to JSON-safe values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain(v) for v in value]
    return value


def extract_json(text):
    """The first {...} object in model text, or None. Tolerates code fences and chatter."""
    if not text or not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def describe_deviations(item):
    """Plain-English statements of what the rules found, and what merely looks different but is not a
    deviation. Handed to the agents so their narrative is anchored to the deterministic findings: on the first
    real run the analyst wrote about a harmless wording change (Co-preferred to Preferred) and never mentioned
    the step therapy that had actually been added."""
    item = to_plain(item)
    flags = item.get("flags") or {}
    expected_tier, actual_tier = item.get("expectedTier"), item.get("actualTier")
    expected_status, actual_status = item.get("expectedStatus"), item.get("actualStatus")
    found, not_deviations = [], []

    if flags.get("coverageDeviation") == "Y":
        found.append(f"Coverage: the contract requires the product to be covered; the market data shows it as "
                     f"not covered ({actual_status}).")
    elif flags.get("tierDeviation") == "Y":
        found.append(f"Tier: the contract expects Tier {expected_tier} ({expected_status}); the market data shows "
                     f"Tier {actual_tier} ({actual_status}), which is worse.")
    if flags.get("stDeviation") == "Y":
        found.append("Step therapy: the contract does not permit step therapy; the market data shows it is required.")
    if flags.get("paDeviation") == "Y":
        found.append("Prior authorization: the contract does not permit it; the market data shows it is required.")
    if flags.get("qlDeviation") == "Y":
        found.append("Quantity limit: the contract does not permit one; the market data shows one applies.")
    if flags.get("parityDeviation") == "Y":
        comparator = item.get("comparatorProductId") or "the comparator"
        found.append(f"Parity: the contract requires placement no less favorable than {comparator}; the market "
                     f"data shows {comparator} placed better.")

    tier_ok = flags.get("tierDeviation") != "Y" and flags.get("coverageDeviation") != "Y"
    if tier_ok and expected_status and actual_status and expected_status != actual_status:
        not_deviations.append(f"The status wording differs (contract: {expected_status}; market: {actual_status}) but "
                              f"the tier is not worse than contracted, so this is NOT a deviation.")
    return found, not_deviations


def build_facts(item):
    found, not_deviations = describe_deviations(item)
    item = to_plain(item)
    return {
        "classifications": item.get("classifications") or [],
        "deviatingFields": found,
        "notDeviations": not_deviations,
        "severity": item.get("severity"),
        "flags": item.get("flags") or {},
        "expected": {"tier": item.get("expectedTier"), "status": item.get("expectedStatus")},
        "actual": {"tier": item.get("actualTier"), "status": item.get("actualStatus")},
        "asOfDate": item.get("asOfDate"),
        "payerId": item.get("payerId"),
        "planId": item.get("planId"),
        "productId": item.get("productId"),
        "comparatorProductId": item.get("comparatorProductId"),
        "ambiguities": item.get("ambiguities") or [],
        "withinGracePeriod": bool(item.get("withinGracePeriod")),
        "daysSinceEffective": item.get("daysSinceEffective"),
        "dataQualityReasons": item.get("dataQualityReasons") or [],
        "exhibitDRouting": item.get("routing") or [],
    }


def query_playbook(classifications, query_fn):
    rows, seen = [], set()
    for classification in classifications:
        hits = query_fn(
            classification,
            {"$and": [{"docType": {"$eq": "playbook"}}, {"classification": {"$eq": classification}}]},
            10,
        )
        for hit in hits:
            if hit["key"] not in seen:
                seen.add(hit["key"])
                rows.append(to_plain(hit["metadata"]))
    return rows


# What each deviating field is governed by. The search text used to be built from tier and status alone, so a
# step-therapy case cited the tier and parity clauses and missed the utilization-management clause it is about.
_CLAUSE_TOPICS = (
    ("coverageDeviation", "coverage commitment: product shall remain covered; not covered, excluded or non-formulary"),
    ("tierDeviation", "tier commitment: Payer shall maintain the Contracted Product on the expected tier"),
    ("stDeviation", "utilization-management commitment: step therapy ST is not permitted"),
    ("paDeviation", "utilization-management commitment: prior authorization PA criteria"),
    ("qlDeviation", "utilization-management commitment: quantity limit QL"),
    ("parityDeviation", "parity commitment: no less favorably than the Comparator Product"),
)


def clause_query_text(item):
    flags = to_plain(item).get("flags") or {}
    topics = [topic for field, topic in _CLAUSE_TOPICS if flags.get(field) == "Y"]
    found, _ = describe_deviations(item)
    return " ".join(str(p) for p in [
        ", ".join(item.get("classifications") or []),
        " ".join(topics),
        " ".join(found),
        " ".join(item.get("ambiguities") or []),
        item.get("clauseReference") or "",
    ] if p)


def query_clauses(item, query_fn):
    if not item.get("contractId"):
        return []
    text = clause_query_text(item)
    hits = query_fn(
        text,
        {"$and": [{"docType": {"$eq": "clause"}}, {"contractId": {"$eq": item["contractId"]}}]},
        4,
    )
    return [
        {"section": h["metadata"].get("section"), "title": h["metadata"].get("title"), "text": h["metadata"].get("text")}
        for h in hits
    ]


CONTRACT_SOURCE_WITH_CLAUSES = "Contract clause text is provided in 'clauses'; cite the section."
CONTRACT_SOURCE_TERMS_ONLY = ("No clause text is on file for this contract, only its structured terms. "
                              "Say 'the contract terms on file'; never say the contract 'states' or quote it.")


def build_context(item, query_fn):
    is_data_quality = item.get("status") == STATUS_DATA_QUALITY
    clauses = [] if is_data_quality else query_clauses(item, query_fn)
    facts = build_facts(item)
    # Whether there is contract TEXT behind the terms decides how the agents may phrase them: a contract loaded
    # as a table row has terms but no wording, and "the contract explicitly states" would overstate that.
    facts["contractSource"] = CONTRACT_SOURCE_WITH_CLAUSES if clauses else CONTRACT_SOURCE_TERMS_ONLY
    return {
        "mode": "template" if is_data_quality else "agents",
        "severity": item.get("severity"),
        "facts": facts,
        "clauses": clauses,
        "playbook": query_playbook(item.get("classifications") or [], query_fn),
    }


def recommendation(row, text, source):
    # Everything except the wording comes from the playbook row.
    return {
        "classification": row.get("classification"),
        "persona": row.get("persona"),
        "nextBestAction": text,
        "requiredEvidence": row.get("requiredEvidence"),
        "approvalRequired": row.get("approvalRequired"),
        "deliveryChannel": row.get("deliveryChannel"),
        "doNotDo": row.get("doNotDo"),
        "source": source,
    }


def _template_recommendations(playbook):
    return [recommendation(r, r.get("nextBestAction"), "playbook-template") for r in playbook]


def _row_key(item):
    return (str(item.get("classification", "")).strip().lower(), str(item.get("persona", "")).strip().lower())


def _citations(context):
    return [{"section": c.get("section"), "title": c.get("title")} for c in context.get("clauses", [])]


def _verification(verifier_text, issues):
    if verifier_text is None:
        return {"ran": False, "verdict": "skipped", "issues": []}
    parsed = extract_json(verifier_text)
    if parsed is None or parsed.get("verdict") not in ("pass", "fail"):
        issues.append("Verifier output was unreadable; treat as not verified")
        return {"ran": True, "verdict": "unreadable", "issues": []}
    found = [str(i) for i in (parsed.get("issues") or [])][:10]
    if parsed["verdict"] == "fail":
        issues.append("Verifier flagged the proposal: " + ("; ".join(found) or "no detail given"))
    return {"ran": True, "verdict": parsed["verdict"], "issues": found}


def assemble(context, analyst_text=None, planner_results=None, verifier_text=None, agent_failed=False):
    """The validated, saveable result. Never raises on bad model output."""
    playbook = context.get("playbook") or []
    facts = context.get("facts") or {}
    issues = []

    if context.get("mode") == "template":
        return {
            "rootCause": "; ".join(facts.get("dataQualityReasons") or ["Data-quality exception"]),
            "rootCauseConfidence": "high",
            "ambiguityAssessment": None,
            "recommendations": _template_recommendations(playbook),
            "clauseCitations": [],
            "needsHumanEdit": not playbook,
            "validationIssues": ["No playbook rows matched"] if not playbook else [],
            "verification": {"ran": False, "verdict": "skipped", "issues": []},
            "reasoningSource": "playbook-template",
        }

    analyst = None if agent_failed else extract_json(analyst_text)
    if agent_failed:
        issues.append("An agent step failed; approved templates used instead")
    elif analyst is None:
        issues.append("Analyst output was not valid JSON")

    root_cause = (analyst or {}).get("root_cause")
    if not root_cause or not isinstance(root_cause, str) or FORBIDDEN.search(root_cause):
        if root_cause:
            issues.append("Root cause asserted a breach or financial/legal action and was replaced")
        root_cause = "Root cause could not be produced safely; see the deviation flags and clause citations."
    confidence = (analyst or {}).get("confidence")
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    # One proposal per playbook ROW. The same persona can appear under several
    # classifications (Contracting Team acts on both a tier downgrade and a
    # parity deviation), so the key is (classification, persona), never persona alone.
    proposed = {}
    for result in planner_results or []:
        if not isinstance(result, dict):
            continue
        parsed = extract_json(result.get("text"))
        if parsed and isinstance(parsed.get("next_best_action"), str):
            proposed[_row_key(result)] = parsed["next_best_action"].strip()

    recommendations = []
    for row in playbook:
        persona = str(row.get("persona", ""))
        text = proposed.get(_row_key(row))
        if text and len(text) <= MAX_ACTION_CHARS and not FORBIDDEN.search(text):
            recommendations.append(recommendation(row, text, "personalized"))
            continue
        if text:
            issues.append(f"{persona} ({row.get('classification')}): proposed action rejected by guardrail; approved template used")
        elif not agent_failed:
            issues.append(f"{persona} ({row.get('classification')}): no usable proposal; approved template used")
        recommendations.append(recommendation(row, row.get("nextBestAction"), "playbook-template"))

    if not playbook:
        issues.append("No playbook rows matched; no actions available")

    if facts.get("contractSource") == CONTRACT_SOURCE_TERMS_ONLY:
        spoken = [root_cause] + [r.get("nextBestAction") or "" for r in recommendations if r.get("source") == "personalized"]
        if any(OVERCLAIM.search(str(t)) for t in spoken):
            issues.append("Text says the contract 'states' something, but no clause text is on file for this contract")

    verification = _verification(verifier_text, issues)
    ambiguity = (analyst or {}).get("ambiguity_assessment")

    return {
        "rootCause": root_cause,
        "rootCauseConfidence": confidence,
        "ambiguityAssessment": ambiguity if isinstance(ambiguity, str) else None,
        "recommendations": recommendations,
        "clauseCitations": _citations(context),
        "needsHumanEdit": bool(issues),
        "validationIssues": issues,
        "verification": verification,
        "reasoningSource": "playbook-template" if agent_failed else "agentcore-harness",
    }


def approval_needed(recommendations):
    return any(str(r.get("approvalRequired", "Y")).upper() == "Y" for r in recommendations)
