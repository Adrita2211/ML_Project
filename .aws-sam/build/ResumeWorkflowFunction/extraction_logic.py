"""
Deterministic validation of the Contract Parser agent's output (pure, unit
tested). The agent proposes a structured reading of the contract; this decides
what is safe to save, because everything downstream joins on it.

Three things the prompt alone cannot guarantee, now enforced in code:

  Identifiers are grounded. contract_id, payer_id, plan_id, product_id and
  comparator_product_id are the join keys for market data. An id that does not
  appear in the document text is discarded, so a model cannot invent a key that
  silently fails to match (or worse, matches the wrong row). The check ignores
  punctuation and spacing, since OCR often splits "PAY-001".

  Dates are ISO. The comparison worker compares dates as YYYY-MM-DD strings.
  "January 1, 2026" would compare wrongly and never raise an error, so common
  formats are converted and anything else is discarded.

  Types are normalized. Tiers to integers, PA/ST/QL/parity to Y or N.

Nothing is saved unless there is at least one coverage term and the payer is
identified: an empty or unreadable extraction fails the workflow visibly
instead of writing a placeholder row.
"""
import re
from datetime import date, datetime

from case_logic import extract_json

TOP_STRING_KEYS = (
    "contract_id", "payer_id", "payer_name", "plan_id", "plan_name",
    "manufacturer_name", "executive_summary",
)
TOP_DATE_KEYS = ("effective_from", "effective_to")
TERM_STRING_KEYS = (
    "product_id", "product_name", "strength", "expected_status", "ql_limit",
    "comparator_product_id", "comparator_product_name", "clause_reference",
)
TERM_FLAG_KEYS = ("pa_allowed", "st_allowed", "ql_allowed", "parity_required")
GROUNDED_TOP = ("contract_id", "payer_id", "plan_id")
GROUNDED_TERM = ("product_id", "comparator_product_id")

MAX_TERMS = 50
MAX_LIST_ITEMS = 50
DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%m/%d/%Y", "%d %B %Y")


def _str(value):
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text or None


def _flag(value):
    text = str(value).strip().lower() if value is not None else ""
    if text in ("y", "yes", "true"):
        return "Y"
    if text in ("n", "no", "false"):
        return "N"
    return None


def _tier(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        number = value
    else:
        match = re.search(r"\d+", str(value))
        number = int(match.group()) if match else None
    return number if number is not None and 1 <= number <= 9 else None


def _iso_date(value):
    text = _str(value)
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:40].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _squash(text):
    return re.sub(r"[^A-Za-z0-9]", "", text or "").lower()


def _grounded(identifier, squashed_source):
    return bool(identifier) and _squash(identifier) in squashed_source


def _clean_list(value, limit=MAX_LIST_ITEMS):
    if not isinstance(value, list):
        return []
    return [text for text in (_str(v) for v in value[:limit]) if text]


def _rebate(entry):
    return {k: _str(entry.get(k)) for k in
            ("tier", "base_rebate_pct", "performance_rebate_pct", "performance_condition")}


def normalize(raw, source_text):
    """(extracted, issues) from the agent's parsed JSON and the document text."""
    issues = []
    source = _squash(source_text)
    out = {key: _str(raw.get(key)) for key in TOP_STRING_KEYS}

    for key in TOP_DATE_KEYS:
        out[key] = _iso_date(raw.get(key))
        if raw.get(key) and not out[key]:
            issues.append(f"{key} {raw.get(key)!r} is not a date I can read; ignored")

    grace = raw.get("implementation_grace_days")
    out["implementation_grace_days"] = grace if isinstance(grace, int) and not isinstance(grace, bool) and 0 <= grace <= 365 else None

    for key in GROUNDED_TOP:
        if out[key] and not _grounded(out[key], source):
            issues.append(f"{key} {out[key]!r} does not appear in the document; ignored")
            out[key] = None

    terms = []
    raw_terms = raw.get("coverage_terms")
    for entry in (raw_terms if isinstance(raw_terms, list) else [])[:MAX_TERMS]:
        if not isinstance(entry, dict):
            continue
        term = {key: _str(entry.get(key)) for key in TERM_STRING_KEYS}
        term["expected_tier"] = _tier(entry.get("expected_tier"))
        if entry.get("expected_tier") is not None and term["expected_tier"] is None:
            issues.append(f"expected_tier {entry.get('expected_tier')!r} for {term['product_name'] or term['product_id']} is not a tier number; ignored")
        for key in TERM_FLAG_KEYS:
            term[key] = _flag(entry.get(key))
        for key in GROUNDED_TERM:
            if term[key] and not _grounded(term[key], source):
                issues.append(f"{key} {term[key]!r} does not appear in the document; ignored")
                term[key] = None
        if not (term["product_id"] or term["product_name"]):
            issues.append("a coverage term with no product was dropped")
            continue
        terms.append(term)
    out["coverage_terms"] = terms

    out["rebate_terms"] = [_rebate(e) for e in (raw.get("rebate_terms") or [])[:MAX_LIST_ITEMS] if isinstance(e, dict)] \
        if isinstance(raw.get("rebate_terms"), list) else []
    out["key_dates_and_amounts"] = _clean_list(raw.get("key_dates_and_amounts"))
    return out, issues


def parse(agent_text, source_text):
    """{"ok", "extracted", "issues"}. `ok` is False when nothing usable can be saved."""
    raw = extract_json(agent_text)
    if raw is None:
        return {"ok": False, "extracted": {}, "issues": ["The agent's output was not a JSON object"]}

    extracted, issues = normalize(raw, source_text)

    if not extracted["coverage_terms"]:
        issues.append("No coverage terms could be extracted; nothing to compare against")
    if not (extracted["payer_id"] or extracted["payer_name"]):
        issues.append("The payer could not be identified")
    ok = bool(extracted["coverage_terms"]) and bool(extracted["payer_id"] or extracted["payer_name"])

    extracted["validation_issues"] = issues
    return {"ok": ok, "extracted": extracted, "issues": issues}
