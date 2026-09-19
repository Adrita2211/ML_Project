"""
Builds Contract_Expectations items for the contract table. Shared by
save_and_notify.py (rows extracted from a PDF) and scripts/load_contract_
expectations.py (rows from a CSV/Model N export), so both produce the same
keys and attributes and the comparison worker can't tell them apart.
"""
import os
import re
import uuid


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip())
    return value.strip("-").lower()


def build_contract_id(extracted: dict, s3_key: str = "") -> str:
    if extracted.get("contract_id"):
        return slugify(extracted["contract_id"])

    payer = extracted.get("payer_name")
    manufacturer = extracted.get("manufacturer_name")
    if payer and manufacturer:
        parts = [payer, manufacturer]
        if extracted.get("effective_from"):
            parts.append(extracted["effective_from"])
        return slugify("-".join(parts))

    if s3_key:
        return slugify(os.path.splitext(os.path.basename(s3_key))[0])

    return str(uuid.uuid4())


def resolve_join_keys(extracted: dict, term: dict) -> tuple[str, str, str]:
    """Payer/plan/product identifiers with fallback placeholders, so keys
    never collide silently on a sparse document. Shared by the row's own
    composite key and its payerPlanProductKey attribute so they can't drift."""
    payer_id = extracted.get("payer_id") or slugify(extracted.get("payer_name") or "unknown-payer")
    plan_id = extracted.get("plan_id") or "unspecified-plan"
    product_id = term.get("product_id") or slugify(term.get("product_name") or "unknown-product")
    return payer_id, plan_id, product_id


def build_contract_item(contract_id: str, extracted: dict, term: dict, bucket=None, source_key=None) -> dict:
    payer_id, plan_id, product_id = resolve_join_keys(extracted, term)
    return {
        # "documentId" is the existing table's partition key; the value is a
        # composite so there is one item per contract/payer/plan/product.
        "documentId": f"{contract_id}#{payer_id}#{plan_id}#{product_id}",
        # GSI key: how the comparison worker finds this row from a market snapshot.
        "payerPlanProductKey": f"{payer_id}#{plan_id}#{product_id}",
        "contractId": contract_id,
        "payerId": extracted.get("payer_id"),
        "payerName": extracted.get("payer_name"),
        "planId": extracted.get("plan_id"),
        "planName": extracted.get("plan_name"),
        "manufacturerName": extracted.get("manufacturer_name"),
        "productId": term.get("product_id"),
        "productName": term.get("product_name"),
        "expectedTier": term.get("expected_tier"),
        "expectedStatus": term.get("expected_status"),
        "paAllowed": term.get("pa_allowed"),
        "stAllowed": term.get("st_allowed"),
        "qlAllowed": term.get("ql_allowed"),
        "qlLimit": term.get("ql_limit"),
        "comparatorProductId": term.get("comparator_product_id"),
        "comparatorProductName": term.get("comparator_product_name"),
        "parityRequired": term.get("parity_required"),
        "clauseReference": term.get("clause_reference"),
        "effectiveFrom": extracted.get("effective_from"),
        "effectiveTo": extracted.get("effective_to"),
        "graceDays": extracted.get("implementation_grace_days"),
        "bucket": bucket,
        "sourceKey": source_key,
    }
