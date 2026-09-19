"""
Final Step Functions task. Persists the structured extraction to DynamoDB
and emails a readable summary via SNS.

Writes one item per (contract_id, payer_id, plan_id, product_id) coverage
row - not one blob per contract - so this table is directly queryable by
the deviation comparison engine later (Contract_Expectations shape: given a
payer/plan/product key from a market-data snapshot, look up the matching
row here and diff tier/PA/ST/QL/parity). A contract with no coverage_terms
still gets a single fallback row so nothing is silently dropped.

contract_id is derived from the extracted payer_name + manufacturer_name +
effective_from when Bedrock found them (so re-processing a corrected version
of the same agreement updates its existing rows instead of creating
duplicates), falling back to the S3 object key, then a random UUID.
"""
import os

import boto3

from contract_items import build_contract_id, build_contract_item

ddb = boto3.resource("dynamodb").Table(os.environ["SUMMARIES_TABLE"])
sns = boto3.client("sns")
TOPIC_ARN = os.environ["SUMMARY_READY_TOPIC_ARN"]


def format_email_body(extracted: dict) -> str:
    lines = [extracted.get("executive_summary", "(no executive summary extracted)"), ""]

    lines.append(f"Payer: {extracted.get('payer_name', 'n/a')}")
    lines.append(f"Manufacturer: {extracted.get('manufacturer_name', 'n/a')}")
    lines.append(f"Effective: {extracted.get('effective_from', 'n/a')} - {extracted.get('effective_to', 'n/a')}")
    lines.append("")

    coverage_terms = extracted.get("coverage_terms") or []
    if coverage_terms:
        lines.append("Coverage terms:")
        for t in coverage_terms:
            lines.append(
                f"  - {t.get('product_name', 'n/a')}: Tier {t.get('expected_tier', 'n/a')} "
                f"({t.get('expected_status', 'n/a')}), PA={t.get('pa_allowed', 'n/a')} "
                f"ST={t.get('st_allowed', 'n/a')} QL={t.get('ql_allowed', 'n/a')}"
                + (f" [{t.get('clause_reference')}]" if t.get("clause_reference") else "")
            )
        lines.append("")

    rebates = extracted.get("rebate_terms") or []
    if rebates:
        lines.append("Rebate Terms:")
        for r in rebates:
            lines.append(
                f"  - Tier {r.get('tier', 'n/a')}: base {r.get('base_rebate_pct', 'n/a')}, "
                f"performance {r.get('performance_rebate_pct', 'n/a')} "
                f"(if {r.get('performance_condition', 'n/a')})"
            )
        lines.append("")

    flagged = extracted.get("key_dates_and_amounts") or []
    if flagged:
        lines.append("Flagged dates/amounts:")
        for item in flagged:
            lines.append(f"  - {item}")
        lines.append("")

    notes = extracted.get("validation_issues") or []
    if notes:
        lines.append("Extraction notes (values the validator discarded or could not read - review the source):")
        for note in notes:
            lines.append(f"  - {note}")

    return "\n".join(lines).rstrip()


def handler(event, context):
    extracted = event["extracted"]
    s3_key = event["key"]
    contract_id = build_contract_id(extracted, s3_key)

    coverage_terms = extracted.get("coverage_terms") or [{}]  # fallback row if extraction found none

    row_keys = []
    for term in coverage_terms:
        item = build_contract_item(contract_id, extracted, term, bucket=event["bucket"], source_key=s3_key)
        ddb.put_item(Item=item)
        row_keys.append(item["documentId"])

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=f"Formulary agreement summary ready: {s3_key}",
        Message=format_email_body(extracted),
    )

    return {"contractId": contract_id, "rowKeys": row_keys}
