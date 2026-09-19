"""
EventBridge-triggered (S3 upload under market-data/, .csv or .xlsx) Lambda
that parses a market/formulary snapshot file into Market_Snapshots. This is
the deterministic "parse" path - no LLM, because MMIT-style data already
arrives structured.

Accepts MMIT-style snake_case columns (actual_tier, pa_flag,
source_freshness_days ...) or camelCase. Stands in for a real MMIT API pull:
swap the trigger for a scheduled EventBridge rule that calls the API and the
parse + write logic below is unchanged.

The table holds the LATEST snapshot per payer/plan/product. A row only
replaces the stored one if its snapshot_date is the same or newer, so
uploading an older file after a newer one can't roll the data back
(and the file order within one upload doesn't matter).
"""
import os

import boto3
from botocore.exceptions import ClientError

from tabular import read_rows

s3 = boto3.client("s3")
market_table = boto3.resource("dynamodb").Table(os.environ["MARKET_SNAPSHOTS_TABLE"])

REQUIRED_COLUMNS = {"payerId", "planId", "productId", "snapshotDate"}


def _int_or_none(value):
    try:
        return int(float(str(value))) if value is not None else None
    except ValueError:
        return None


def _flag(value):
    text = str(value).strip().upper() if value is not None else ""
    return text if text in ("Y", "N") else None


def handler(event, context):
    bucket = event["detail"]["bucket"]["name"]
    key = event["detail"]["object"]["key"]

    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    rows = read_rows(body, key, sheet="Formulary_Snapshots")

    if not rows or not REQUIRED_COLUMNS.issubset(rows[0].keys()):
        found = sorted(rows[0].keys()) if rows else []
        raise ValueError(f"{key}: market data needs columns {sorted(REQUIRED_COLUMNS)}; found {found}")

    written, skipped_incomplete, skipped_older = 0, 0, 0
    for row in rows:
        if not (row.get("payerId") and row.get("planId") and row.get("productId") and row.get("snapshotDate")):
            skipped_incomplete += 1
            continue

        item = {
            "payerPlanProductKey": f"{row['payerId']}#{row['planId']}#{row['productId']}",
            "snapshotId": row.get("snapshotId"),
            "snapshotDate": str(row["snapshotDate"]),
            "payerId": row["payerId"],
            "planId": row["planId"],
            "productId": row["productId"],
            "benefitType": row.get("benefitType"),
            "actualTier": _int_or_none(row.get("actualTier")),
            "actualStatus": row.get("actualStatus"),
            "paFlag": _flag(row.get("paFlag")),
            "stFlag": _flag(row.get("stFlag")),
            "qlFlag": _flag(row.get("qlFlag")),
            "coverageFlag": _flag(row.get("coverageFlag")),
            "effectiveDate": row.get("effectiveDate"),
            "sourceRecordId": row.get("sourceRecordId"),
            "sourceFreshnessDays": _int_or_none(row.get("sourceFreshnessDays")),
            "sourceSystem": row.get("sourceSystem"),
            "bucket": bucket,
            "sourceKey": key,
        }

        try:
            market_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(payerPlanProductKey) OR snapshotDate <= :d",
                ExpressionAttributeValues={":d": item["snapshotDate"]},
            )
            written += 1
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            skipped_older += 1

    return {
        "rowsWritten": written,
        "rowsSkippedIncomplete": skipped_incomplete,
        "rowsSkippedOlderThanStored": skipped_older,
        "key": key,
    }
