"""
EventBridge-triggered (S3 upload under playbook/, .csv or .xlsx) Lambda that
loads the persona next-best-action playbook into the vector index.

Each row becomes one vector keyed by classification + persona, so
re-uploading an edited playbook overwrites those rows instead of duplicating
them. (Rows deleted from the file are NOT removed from the index.)

The classification, persona and approval flag are filterable metadata; the
action text, evidence and do-not-do guardrail are non-filterable metadata
returned with each hit, so the reasoning step gets the approved wording back
verbatim and applies the guardrail from the source of truth rather than from
model output.
"""
import boto3

import vector_store
from contract_items import slugify
from deviation_rules import normalize_classification
from tabular import read_rows

s3 = boto3.client("s3")

REQUIRED = {"classification", "persona", "nextBestAction"}


def handler(event, context):
    bucket = event["detail"]["bucket"]["name"]
    key = event["detail"]["object"]["key"]

    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    rows = read_rows(body, key, sheet="Persona_NBA_Playbook")

    # The workbook's first column is an unnamed "Column1" holding the classification.
    for row in rows:
        if "classification" not in row and "column1" in row:
            row["classification"] = row["column1"]

    if not rows or not REQUIRED.issubset(rows[0].keys()):
        found = sorted(rows[0].keys()) if rows else []
        raise ValueError(f"{key}: playbook needs columns {sorted(REQUIRED)}; found {found}")

    documents = []
    for row in rows:
        if not row.get("classification") or not row.get("persona") or not row.get("nextBestAction"):
            continue
        classification = normalize_classification(row["classification"])
        documents.append({
            "key": f"playbook#{slugify(classification)}#{slugify(row['persona'])}",
            "embedText": " | ".join(filter(None, [
                classification, row["persona"], row.get("triggerCondition"), row["nextBestAction"],
            ])),
            "metadata": {
                "docType": "playbook",
                "classification": classification,
                "persona": row["persona"],
                "approvalRequired": (row.get("approvalRequired") or "Y").upper(),
                "deliveryChannel": row.get("deliveryChannel") or "",
                "triggerCondition": row.get("triggerCondition") or "",
                "nextBestAction": row["nextBestAction"],
                "requiredEvidence": row.get("requiredEvidence") or "",
                "doNotDo": row.get("doNotDo") or "",
                "sourceKey": key,
            },
        })

    indexed = vector_store.put_documents(documents)
    return {"indexed": indexed, "skippedRows": len(rows) - len(documents), "key": key}
