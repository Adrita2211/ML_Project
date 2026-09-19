"""
Generic DynamoDB Streams -> SQS forwarder - the "buffer + backpressure"
hop from the architecture diagram. Used by two event source mappings (one
on Contract_Expectations' stream, one on Market_Snapshots' stream); both
tables store items carrying a "payerPlanProductKey" attribute, so one
handler covers both without needing to know which table triggered it.

Forwards just the key onto the queue, not the whole item, so the worker
(compare_deviation.py) always re-reads the current state of both sides at
execution time instead of acting on a payload that might already be stale
by the time SQS delivers it.
"""
import json
import os
import boto3
from boto3.dynamodb.types import TypeDeserializer

sqs = boto3.client("sqs")
QUEUE_URL = os.environ["COMPARISON_QUEUE_URL"]
_deserializer = TypeDeserializer()


def _deserialize(image):
    return {k: _deserializer.deserialize(v) for k, v in image.items()}


def handler(event, context):
    forwarded = 0
    for record in event["Records"]:
        if record["eventName"] not in ("INSERT", "MODIFY"):
            continue
        new_image = record["dynamodb"].get("NewImage")
        if not new_image:
            continue
        item = _deserialize(new_image)
        key = item.get("payerPlanProductKey")
        if not key:
            # Item predates this attribute, or is missing payer/plan/product
            # fields entirely - nothing comparable to forward.
            continue
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"payerPlanProductKey": key}))
        forwarded += 1
    return {"forwarded": forwarded}
