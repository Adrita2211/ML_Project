"""
The human-approval gate (Step Functions .waitForTaskToken). The workflow
pauses on this state - at no compute cost - until a person decides, and the
token is what resumes it.

This Lambda stores the token on the case row and emails the approvers through
SNS. It does not resume the workflow itself. A person (today via
scripts/decide_case.py, later a dashboard button) calls SendTaskSuccess with
{"decision": "approve" | "reject", ...}.

If the finding changed while the case was being reasoned about, the token is
resolved immediately as "superseded" so the workflow doesn't wait on a case
that no longer exists.
"""
import os
import time

import boto3
from botocore.exceptions import ClientError

table = boto3.resource("dynamodb").Table(os.environ["DEVIATION_OUTPUT_TABLE"])
sns = boto3.client("sns")
sfn = boto3.client("stepfunctions")
TOPIC_ARN = os.environ["APPROVAL_TOPIC_ARN"]


def _evidence(item):
    sections = [c.get("section") for c in item.get("clauseCitations") or [] if c.get("section")]
    return f"clauses {', '.join(sections)}" if sections else "none on file (structured terms only, no clause text)"


def _message(item):
    recs = item.get("recommendations") or []
    lines = [
        f"Potential deviation for review: {item.get('payerPlanProductKey')}",
        f"Classification: {', '.join(item.get('classifications') or [])}   Severity: {item.get('severity')}",
        f"Contract: {item.get('contractId')}   As of: {item.get('asOfDate')}",
        f"Contract evidence: {_evidence(item)}",
        "",
        f"Likely root cause ({item.get('rootCauseConfidence')} confidence): {item.get('rootCause')}",
    ]
    if item.get("needsHumanEdit"):
        lines += ["", "NOTE: automated checks flagged this proposal for careful review:"]
        lines += [f"  - {i}" for i in item.get("validationIssues") or []]
    lines += ["", "Proposed actions (nothing has been sent to anyone):"]
    for r in recs:
        lines.append(f"  [{r.get('persona')}] {r.get('nextBestAction')}  (via {r.get('deliveryChannel')})")
    lines += [
        "", "This is a potential deviation, not a determination of breach.",
        "", "To decide:",
        f"  python scripts/decide_case.py --key \"{item.get('payerPlanProductKey')}\" --decision approve",
        f"  python scripts/decide_case.py --key \"{item.get('payerPlanProductKey')}\" --decision reject",
    ]
    return "\n".join(lines)


def handler(event, context):
    key, signature, token = event["key"], event["signature"], event["taskToken"]

    try:
        item = table.update_item(
            Key={"payerPlanProductKey": key},
            UpdateExpression="SET approvalToken = :t, approvalRequestedAt = :ts",
            ConditionExpression="#sig = :sig",
            ExpressionAttributeNames={"#sig": "signature"},
            ExpressionAttributeValues={":t": token, ":ts": int(time.time()), ":sig": signature},
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        sfn.send_task_success(taskToken=token, output='{"decision": "superseded"}')
        return {"superseded": True}

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=f"Approval needed: {item.get('primaryClassification')} ({item.get('severity')}) {key}"[:100],
        Message=_message(item),
    )
    return {"requested": True}
