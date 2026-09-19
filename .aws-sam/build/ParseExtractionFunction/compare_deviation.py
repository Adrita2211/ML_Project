"""
SQS-triggered comparison worker - the "parallel Lambda workers" layer.

Each message carries a payerPlanProductKey. The worker re-reads the current
state of both sides, runs the deterministic rules (deviation_rules.py) and
writes Deviation_Output. No LLM here: the deviation-case workflow (Step
Functions + AgentCore agents) is started separately by the table's stream, and
only for rows this worker marks as deviations or data-quality exceptions.

Behaviours that matter:
- No contract yet, source fresh: no-op. The contract's own stream event
  re-queues this key when it lands, so either arrival order converges.
- No contract, source stale (Sec 3.4): a data-quality exception routed to
  the data steward - a market row nobody can map to a contract.
- Parity needs the comparator's snapshot, and a file is written row by row,
  so the comparator row may not exist yet. The message is re-queued with a
  delay (MAX_PARITY_RETRIES times) instead of writing a provisional result,
  which would start agents for a result about to change.
- Same finding again (same signature): the row keeps its reasoning. If the
  as-of date moved it is refreshed; if nothing changed at all, nothing is
  written. Every write emits a stream event and can start a workflow, so
  no-op writes are avoided.
"""
import json
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

import deviation_rules as rules

ddb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
market_table = ddb.Table(os.environ["MARKET_SNAPSHOTS_TABLE"])
contract_table = ddb.Table(os.environ["CONTRACT_EXPECTATIONS_TABLE"])
deviation_table = ddb.Table(os.environ["DEVIATION_OUTPUT_TABLE"])
CONTRACT_INDEX = os.environ["CONTRACT_EXPECTATIONS_INDEX"]
QUEUE_URL = os.environ["COMPARISON_QUEUE_URL"]
STALE_SOURCE_DAYS = int(os.environ.get("STALE_SOURCE_DAYS", "30"))
MAX_PARITY_RETRIES = int(os.environ.get("MAX_PARITY_RETRIES", "3"))
PARITY_RETRY_DELAY_SECONDS = int(os.environ.get("PARITY_RETRY_DELAY_SECONDS", "60"))


def _contracts_for(key):
    items, kwargs = [], {"IndexName": CONTRACT_INDEX, "KeyConditionExpression": Key("payerPlanProductKey").eq(key)}
    while True:
        page = contract_table.query(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _pick_contract(contracts, as_of):
    """The row whose term covers the snapshot date; otherwise the most recently effective."""
    if not contracts:
        return None
    covering = [
        c for c in contracts
        if (not c.get("effectiveFrom") or not as_of or c["effectiveFrom"] <= as_of)
        and (not c.get("effectiveTo") or not as_of or as_of <= c["effectiveTo"])
    ]
    return max(covering or contracts, key=lambda c: c.get("effectiveFrom") or "")


def _dynamo_safe(value):
    """DynamoDB rejects Python floats."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dynamo_safe(v) for v in value]
    return value


def _requeue(key, attempt):
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({"payerPlanProductKey": key, "attempt": attempt + 1}),
        DelaySeconds=PARITY_RETRY_DELAY_SECONDS,
    )


def handler(event, context):
    written = refreshed = unchanged = waiting = requeued = 0

    for record in event["Records"]:
        message = json.loads(record["body"])
        key, attempt = message["payerPlanProductKey"], int(message.get("attempt", 0))

        snapshot = market_table.get_item(Key={"payerPlanProductKey": key}).get("Item")
        if not snapshot:
            waiting += 1
            continue

        contract = _pick_contract(_contracts_for(key), snapshot.get("snapshotDate"))
        if contract is None and not rules.is_stale(snapshot, STALE_SOURCE_DAYS):
            waiting += 1
            continue

        comparator = None
        if contract and contract.get("comparatorProductId"):
            payer_id, plan_id, _ = key.split("#", 2)
            comparator = market_table.get_item(
                Key={"payerPlanProductKey": f"{payer_id}#{plan_id}#{contract['comparatorProductId']}"}
            ).get("Item")

        result = rules.evaluate(contract, snapshot, comparator, stale_days=STALE_SOURCE_DAYS)

        if rules.parity_pending(contract, comparator, result) and attempt < MAX_PARITY_RETRIES:
            _requeue(key, attempt)
            requeued += 1
            continue

        new_signature = rules.signature(result)
        existing = deviation_table.get_item(Key={"payerPlanProductKey": key}).get("Item")

        if existing and existing.get("signature") == new_signature:
            if (existing.get("asOfDate") == result["asOfDate"]
                    and existing.get("daysSinceEffective") == result["daysSinceEffective"]):
                # Nothing changed. Writing anyway would emit a stream event and start a case workflow
                # that only finds the case already claimed (seen: 11 of 15 executions on the first run).
                unchanged += 1
                continue
            deviation_table.update_item(
                Key={"payerPlanProductKey": key},
                UpdateExpression="SET asOfDate = :a, evaluatedAt = :t, daysSinceEffective = :d",
                ExpressionAttributeValues={
                    ":a": result["asOfDate"], ":t": int(time.time()), ":d": result["daysSinceEffective"],
                },
            )
            refreshed += 1
            continue

        item = {
            "payerPlanProductKey": key,
            "signature": new_signature,
            "contractId": contract.get("contractId") if contract else None,
            "payerId": snapshot.get("payerId"),
            "planId": snapshot.get("planId"),
            "productId": snapshot.get("productId"),
            "comparatorProductId": contract.get("comparatorProductId") if contract else None,
            "clauseReference": contract.get("clauseReference") if contract else None,
            "evaluatedAt": int(time.time()),
            **{k: result[k] for k in (
                "flags", "classifications", "primaryClassification", "routing", "severity", "status",
                "evidenceConfidence", "ambiguities", "ambiguityCodes", "dataQualityReasons", "dataQualityCodes",
                "withinGracePeriod", "daysSinceEffective", "expectedTier", "actualTier",
                "expectedStatus", "actualStatus", "asOfDate",
            )},
        }
        # A full put replaces the item, which also clears any earlier reasoning:
        # a changed finding needs fresh root cause and next actions.
        deviation_table.put_item(Item=_dynamo_safe(item))
        written += 1

    return {"written": written, "refreshed": refreshed, "unchanged": unchanged, "waiting": waiting, "requeued": requeued}
