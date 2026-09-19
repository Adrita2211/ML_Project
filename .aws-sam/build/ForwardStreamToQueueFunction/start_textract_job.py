"""
Step Functions task (waitForTaskToken pattern).
Starts an async Textract job on the uploaded formulary agreement PDF and
records the mapping from Textract JobId -> Step Functions task token, so
resume_workflow.py can look it up when Textract's completion notification
arrives on SNS.

Dedupes on (bucket, key, etag) before spending a Textract/Bedrock call: if
this exact object version was already processed, skip straight to resolving
the task token instead of re-running OCR + extraction. This is the cost
optimization from the architecture review - re-uploads of an unchanged file
(a common occurrence with manual/scripted uploads) shouldn't burn Bedrock
tokens. The dedupe marker lives in the same job-tokens table under a
"dedupe#..." key, distinct from real Textract JobIds. It is written by the
LAST workflow step (index_contract_clauses.py), only after the run fully
succeeded - writing it here would mark a file "processed" even if Bedrock or
a later step failed, and the retry would then be skipped forever.
"""
import json
import os
import boto3

textract = boto3.client("textract")
sfn = boto3.client("stepfunctions")
tokens_table = boto3.resource("dynamodb").Table(os.environ["JOB_TOKENS_TABLE"])

SNS_TOPIC_ARN = os.environ["TEXTRACT_SNS_TOPIC_ARN"]
TEXTRACT_ROLE_ARN = os.environ["TEXTRACT_ROLE_ARN"]


def handler(event, context):
    bucket = event["detail"]["bucket"]["name"]
    key = event["detail"]["object"]["key"]
    # S3 -> EventBridge sends the field as lowercase "etag". Reading "eTag" (as this did at first) always
    # missed, so every file shared one key per name and an edited re-upload was wrongly skipped.
    etag = event["detail"]["object"].get("etag")
    task_token = event["taskToken"]

    # No etag means no way to tell versions apart: process it rather than risk skipping a changed file.
    dedupe_key = f"dedupe#{bucket}#{key}#{etag}" if etag else None
    already_processed = dedupe_key and tokens_table.get_item(Key={"jobId": dedupe_key}).get("Item")

    if already_processed:
        # Same object version already ran through the pipeline - resolve the
        # wait immediately with a "skipped" marker instead of starting a new
        # Textract job. The workflow's SkipCheck state routes on this flag.
        sfn.send_task_success(
            taskToken=task_token,
            output=json.dumps({"bucket": bucket, "key": key, "etag": etag, "extractedText": "", "skipped": True}),
        )
        return {"skipped": True}

    response = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
        NotificationChannel={
            "SNSTopicArn": SNS_TOPIC_ARN,
            "RoleArn": TEXTRACT_ROLE_ARN,
        },
        ClientRequestToken=context.aws_request_id,
    )

    tokens_table.put_item(Item={
        "jobId": response["JobId"],
        "taskToken": task_token,
        "bucket": bucket,
        "key": key,
        "etag": etag,
    })

    return {"jobId": response["JobId"]}
