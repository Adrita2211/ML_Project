"""
First state of the deviation-case workflow. Two jobs, both deterministic:

1. CLAIM the case. The Deviation_Output stream delivers at least once and the
   row is written more than once, so without a claim the same deviation could
   start several workflows and run several agents. The claim is a conditional
   write: it succeeds only if this exact finding (signature) is still current
   and nobody has claimed it. `reasoningStartedAt` also keeps the claim write
   itself out of the trigger (the pipe filters on that attribute being absent).

2. RETRIEVE what the agents are shown: the deviation facts, this contract's
   clauses, and the approved playbook rows for the classification. The agents
   never choose what to retrieve.
"""
import os
import time

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

import case_logic
import vector_store

table = boto3.resource("dynamodb").Table(os.environ["DEVIATION_OUTPUT_TABLE"])
_deserializer = TypeDeserializer()


def handler(event, context):
    key, signature = event["payerPlanProductKey"], event["signature"]

    try:
        table.update_item(
            Key={"payerPlanProductKey": key},
            UpdateExpression="SET reasoningStartedAt = :t, caseExecutionId = :e",
            ConditionExpression=(
                "attribute_exists(payerPlanProductKey) AND #sig = :sig AND attribute_not_exists(reasoningStartedAt)"
            ),
            ExpressionAttributeNames={"#sig": "signature"},
            ExpressionAttributeValues={":t": int(time.time()), ":e": event.get("executionId"), ":sig": signature},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Same keys as the claimed return: the state machine Assigns all of
            # them, and Step Functions JSONata errors on undefined (missing) values.
            return {"claimed": False, "key": None, "signature": None, "severity": None, "context": None}
        raise

    item = table.get_item(Key={"payerPlanProductKey": key})["Item"]
    case = case_logic.build_context(item, vector_store.query)
    return {"claimed": True, "key": key, "signature": signature, "severity": item.get("severity"), "context": case}
