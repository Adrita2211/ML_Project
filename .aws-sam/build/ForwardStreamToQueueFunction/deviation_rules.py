"""
Deterministic deviation rules: contract expected state vs. market snapshot.

Pure functions, no AWS calls - the same logic runs in the comparison Lambda
and in the local test that replays the golden Deviations sheet.

Encodes the sample agreement:
  Exhibit B  deviation triggers  (tier worse than expected, not covered,
             ST where prohibited, PA/QL where not permitted, parity)
  Exhibit D  classification and primary routing
  Sec 3.2    implementation grace period  -> surfaced as an ambiguity, not
             suppressed (the contract says "may be classified", and only
             with written confirmation, so a person or the reasoning step
             decides)
  Sec 3.4    stale source / missing mapping -> data-quality exception,
             routed to the data steward instead of raising a deviation

Flags are 'Y', 'N' or 'Unknown'. 'Unknown' never creates a deviation on its
own; it lowers evidence confidence and is listed as an ambiguity so the
reasoning step (Bedrock) can address it.

What stays with the reasoning step rather than being decided here:
  - whether PA criteria are "materially more restrictive than Exhibit C"
    and whether a QL limit is lower than the contracted one (the snapshot
    only carries Y/N flags for these)
  - whether a discrepancy inside the grace period is administrative lag
  - root cause and the persona-specific next action
"""
import hashlib
import json
from datetime import date

CLASSIFICATION_ROUTING = {  # Exhibit D "Primary routing"
    "Tier downgrade": ["Contracting", "Account Director"],
    "Parity deviation": ["Contracting", "Market Access Strategy"],
    "Restriction escalation": ["Contracting", "FRM", "Patient Services"],
    "Coverage loss": ["Contracting", "Account Director", "FRM"],
    "Data-quality exception": ["Data Steward"],
}

STATUS_DEVIATION = "Potential deviation - review required"
STATUS_COMPLIANT = "Closed - compliant"
STATUS_DATA_QUALITY = "Route to data steward"
STATUS_OUT_OF_TERM = "Not evaluated - outside contract term"

_ALIASES = {
    "any data-quality exception": "Data-quality exception",
    "potential parity deviation": "Parity deviation",
}
_CANONICAL = {name.lower(): name for name in CLASSIFICATION_ROUTING}

_NOT_COVERED_STATUSES = {"not covered", "excluded", "non-formulary", "non formulary"}
_PREFERRED_STATUSES = {"preferred", "co-preferred"}

FLAG_NAMES = (
    "tierDeviation", "coverageDeviation", "paDeviation",
    "stDeviation", "qlDeviation", "parityDeviation",
)


def normalize_classification(label):
    if not label:
        return None
    key = str(label).strip().lower()
    return _ALIASES.get(key) or _CANONICAL.get(key) or str(label).strip()


def _num(value):
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _yn(value):
    text = str(value).strip().upper() if value is not None else ""
    return text if text in ("Y", "N") else None


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _lower(value):
    return str(value).strip().lower() if value else ""


def _not_covered(snapshot):
    return _yn(snapshot.get("coverageFlag")) == "N" or _lower(snapshot.get("actualStatus")) in _NOT_COVERED_STATUSES


def _um_count(snapshot):
    return sum(1 for field in ("paFlag", "stFlag", "qlFlag") if _yn(snapshot.get(field)) == "Y")


def is_stale(snapshot, stale_days):
    freshness = _num(snapshot.get("sourceFreshnessDays"))
    return freshness is not None and freshness > stale_days


def _base_result(snapshot, contract):
    return {
        "expectedTier": _num(contract.get("expectedTier")) if contract else None,
        "actualTier": _num(snapshot.get("actualTier")),
        "expectedStatus": contract.get("expectedStatus") if contract else None,
        "actualStatus": snapshot.get("actualStatus"),
        "asOfDate": snapshot.get("snapshotDate"),
        "ambiguities": [],
        "ambiguityCodes": [],
        "dataQualityReasons": [],
        "dataQualityCodes": [],
        "withinGracePeriod": False,
        "daysSinceEffective": None,
    }


def _short_circuit(base, status, severity, classifications, flag_value, confidence):
    return {
        **base,
        "flags": {name: flag_value for name in FLAG_NAMES},
        "classifications": classifications,
        "primaryClassification": classifications[0] if classifications else None,
        "routing": _routing(classifications),
        "severity": severity,
        "status": status,
        "evidenceConfidence": confidence,
    }


def _routing(classifications):
    seen = []
    for name in classifications:
        for persona in CLASSIFICATION_ROUTING.get(name, []):
            if persona not in seen:
                seen.append(persona)
    return seen


def _restriction(allowed, actual, not_covered):
    """ST/PA/QL: a deviation only where the contract does not permit it and
    the market data shows it. A contract silent on the point makes no
    commitment; a missing market flag is Unknown, not a deviation."""
    if not_covered:
        return "N"
    allowed, actual = _yn(allowed), _yn(actual)
    if allowed is None:
        return "N"
    if actual is None:
        return "Unknown"
    return "Y" if (allowed == "N" and actual == "Y") else "N"


def evaluate(contract, snapshot, comparator=None, stale_days=30):
    """Compare one contract row with one market snapshot.

    `contract` may be None only when the caller has decided the missing
    mapping is itself the finding (see compare_deviation.py)."""
    base = _base_result(snapshot, contract)

    # Sec 3.4 - suppress and route to data stewardship rather than raise a deviation.
    if is_stale(snapshot, stale_days):
        base["dataQualityCodes"].append("STALE_SOURCE")
        base["dataQualityReasons"].append(
            f"Source is stale: {_num(snapshot.get('sourceFreshnessDays'))} days old (threshold {stale_days})"
        )
    if contract is None:
        base["dataQualityCodes"].append("NO_CONTRACT_MAPPING")
        base["dataQualityReasons"].append("No contract mapping found for this payer/plan/product")
    if base["dataQualityCodes"]:
        return _short_circuit(base, STATUS_DATA_QUALITY, "Data quality",
                              ["Data-quality exception"], "Unknown", 0.4)

    as_of = _date(snapshot.get("snapshotDate"))
    term_from, term_to = _date(contract.get("effectiveFrom")), _date(contract.get("effectiveTo"))
    if as_of and ((term_from and as_of < term_from) or (term_to and as_of > term_to)):
        return _short_circuit(base, STATUS_OUT_OF_TERM, "None", [], "Unknown", 0.9)

    not_covered = _not_covered(snapshot)
    expected_tier, actual_tier = base["expectedTier"], base["actualTier"]
    codes, messages = [], []

    # Exhibit B: Coverage / Tier
    coverage = "Y" if not_covered else "N"
    if not_covered:
        tier = "Y" if expected_tier is not None else "Unknown"
    elif expected_tier is None or actual_tier is None:
        tier = "Unknown"
        codes.append("MISSING_TIER")
        messages.append("Tier missing on the contract or the market snapshot; tier not evaluated")
    else:
        tier = "Y" if actual_tier > expected_tier else "N"
        if (tier == "N" and _lower(contract.get("expectedStatus")) in _PREFERRED_STATUSES
                and _lower(snapshot.get("actualStatus")) == "non-preferred"):
            tier = "Y"

    pa = _restriction(contract.get("paAllowed"), snapshot.get("paFlag"), not_covered)
    st = _restriction(contract.get("stAllowed"), snapshot.get("stFlag"), not_covered)
    ql = _restriction(contract.get("qlAllowed"), snapshot.get("qlFlag"), not_covered)
    if "Unknown" in (pa, st, ql):
        codes.append("MISSING_FLAGS")
        messages.append("A PA/ST/QL flag was missing on the market snapshot")

    # Exhibit B: Parity - "comparator has better tier, coverage or UM"
    comparator_id = contract.get("comparatorProductId")
    if _yn(contract.get("parityRequired")) != "Y" or not comparator_id:
        parity = "N"
    elif comparator is None:
        parity = "Unknown"
        codes.append("COMPARATOR_MISSING")
        messages.append(f"No market snapshot for comparator {comparator_id} on this plan; parity not evaluated")
    elif not_covered:
        parity = "N" if _not_covered(comparator) else "Y"
    elif _not_covered(comparator):
        parity = "N"
    else:
        comparator_tier = _num(comparator.get("actualTier"))
        worse_tier = comparator_tier is not None and actual_tier is not None and actual_tier > comparator_tier
        parity = "Y" if (worse_tier or _um_count(comparator) < _um_count(snapshot)) else "N"

    flags = {
        "tierDeviation": tier, "coverageDeviation": coverage, "paDeviation": pa,
        "stDeviation": st, "qlDeviation": ql, "parityDeviation": parity,
    }

    # Exhibit D classification
    classifications = []
    if coverage == "Y":
        classifications.append("Coverage loss")
    elif tier == "Y":
        classifications.append("Tier downgrade")
    if "Y" in (pa, st, ql):
        classifications.append("Restriction escalation")
    if parity == "Y":
        classifications.append("Parity deviation")

    if "Coverage loss" in classifications or "Tier downgrade" in classifications:
        severity = "Critical"
    elif st == "Y" or parity == "Y":
        severity = "High"
    elif classifications:
        severity = "Medium"
    else:
        severity = "None"

    # Sec 3.2 - within the grace period a discrepancy "may be" administrative lag.
    effective = _date(snapshot.get("effectiveDate"))
    grace_days = _num(contract.get("graceDays"))
    if as_of and effective:
        base["daysSinceEffective"] = (as_of - effective).days
    if (classifications and grace_days is not None and base["daysSinceEffective"] is not None
            and 0 <= base["daysSinceEffective"] <= grace_days):
        base["withinGracePeriod"] = True
        codes.append("GRACE_PERIOD")
        messages.append(
            f"Observed {base['daysSinceEffective']} days after the payer's effective date, within the "
            f"{grace_days}-day implementation grace period (Sec 3.2); may be administrative lag"
        )

    base["ambiguityCodes"], base["ambiguities"] = codes, messages
    return {
        **base,
        "flags": flags,
        "classifications": classifications,
        "primaryClassification": classifications[0] if classifications else None,
        "routing": _routing(classifications),
        "severity": severity,
        "status": STATUS_DEVIATION if classifications else STATUS_COMPLIANT,
        "evidenceConfidence": max(0.5, round(0.99 - 0.05 * len(codes), 2)),
    }


def signature(result):
    """Stable hash of what the reasoning step depends on. Dates and day
    counts are excluded on purpose: the same deviation seen again in next
    month's snapshot is the same finding and must not trigger a new Bedrock
    call."""
    core = {
        "flags": result["flags"],
        "classifications": result["classifications"],
        "severity": result["severity"],
        "status": result["status"],
        "expected": [result["expectedTier"], result["expectedStatus"]],
        "actual": [result["actualTier"], result["actualStatus"]],
        "codes": sorted(result["ambiguityCodes"] + result["dataQualityCodes"]),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def parity_pending(contract, comparator, result):
    """True when parity could only be Unknown because the comparator's
    snapshot has not been ingested yet (files are written row by row, so the
    brand row can be compared before the comparator row exists)."""
    return comparator is None and "COMPARATOR_MISSING" in result["ambiguityCodes"] and contract is not None
