"""
Records the outcome of the approval step on the case row. Recording only:
nothing is sent to a payer or anyone else here. Contract Sec 5.2 requires human
approval before external communication, and a release step that acts on an
approved case is not built.

Fail-safe on input: anything other than an explicit approve is recorded as
Rejected, so a malformed callback can never approve a case by accident.
"""
import os
import time

import boto3
from botocore.exceptions import ClientError

table = boto3.resource("dynamodb").Table(os.environ["DEVIATION_OUTPUT_TABLE"])

_STATUS = {"approve": "Approved", "reject": "Rejected", "expired": "Expired"}


def handler(event, context):
    key, signature = event["key"], event["signature"]
    decision = str(event.get("decision", "")).strip().lower()

    if decision == "superseded":
        return {"recorded": False, "status": "Superseded"}

    status = _STATUS.get(decision, "Rejected")
    comment = event.get("comment")
    if decision not in _STATUS:
        comment = f"Unrecognized decision {decision!r} treated as rejection. {comment or ''}".strip()

    try:
        table.update_item(
            Key={"payerPlanProductKey": key},
            UpdateExpression=(
                "SET approvalStatus = :s, decidedAt = :ts, decidedBy = :by, decisionComment = :c "
                "REMOVE approvalToken"
            ),
            ConditionExpression="#sig = :sig",
            ExpressionAttributeNames={"#sig": "signature"},
            ExpressionAttributeValues={
                ":s": status, ":ts": int(time.time()), ":by": event.get("decidedBy"),
                ":c": comment, ":sig": signature,
            },
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {"recorded": False, "status": "Superseded"}
        raise

    return {"recorded": True, "status": status}
