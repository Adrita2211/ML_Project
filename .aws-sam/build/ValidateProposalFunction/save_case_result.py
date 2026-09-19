"""
Writes the validated result onto the Deviation_Output row and decides whether
a human must approve. Conditional on the finding still being current: if the
comparison worker replaced the row while agents were working (a changed
finding), this result is for an old finding and is dropped.

`approvalStatus` is set from the playbook's own approval flags, not from
model output: any recommendation marked approval-required means a person
signs off before anything else happens (contract Sec 5.2).
"""
import os
import time

import boto3
from botocore.exceptions import ClientError

import case_logic

table = boto3.resource("dynamodb").Table(os.environ["DEVIATION_OUTPUT_TABLE"])


def handler(event, context):
    result, key, signature = event["result"], event["key"], event["signature"]
    needs_approval = case_logic.approval_needed(result["recommendations"])

    try:
        table.update_item(
            Key={"payerPlanProductKey": key},
            UpdateExpression=(
                "SET rootCause = :rc, rootCauseConfidence = :rcc, ambiguityAssessment = :aa, "
                "recommendations = :recs, clauseCitations = :cit, needsHumanEdit = :nhe, "
                "validationIssues = :vi, verification = :ver, reasoningSource = :src, "
                "approvalStatus = :ap, reasonedAt = :ts"
            ),
            ConditionExpression="#sig = :sig",
            ExpressionAttributeNames={"#sig": "signature"},
            ExpressionAttributeValues={
                ":rc": result["rootCause"], ":rcc": result["rootCauseConfidence"],
                ":aa": result["ambiguityAssessment"], ":recs": result["recommendations"],
                ":cit": result["clauseCitations"], ":nhe": result["needsHumanEdit"],
                ":vi": result["validationIssues"], ":ver": result["verification"],
                ":src": result["reasoningSource"],
                ":ap": "Pending approval" if needs_approval else "Not required",
                ":ts": int(time.time()), ":sig": signature,
            },
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {"saved": False, "needsApproval": False}
        raise

    return {"saved": True, "needsApproval": needs_approval}
