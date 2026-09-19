"""
Subscribed to the textract-job-complete SNS topic.
Looks up the paused Step Functions task token for the finished Textract job,
pages through the OCR results, and resumes the workflow with the extracted
text (or fails it, if the Textract job itself failed).
"""
import os
import json
import boto3

sfn = boto3.client("stepfunctions")
textract = boto3.client("textract")
tokens_table = boto3.resource("dynamodb").Table(os.environ["JOB_TOKENS_TABLE"])

MAX_CHARS = 100_000  # guard against oversized Step Functions payloads


def handler(event, context):
    message = json.loads(event["Records"][0]["Sns"]["Message"])
    job_id = message["JobId"]
    status = message["Status"]

    record = tokens_table.get_item(Key={"jobId": job_id}).get("Item")
    if record is None:
        # Nothing we can resume - log and exit rather than raising, since
        # SNS will otherwise retry this delivery indefinitely.
        print(f"No task token found for jobId={job_id}; ignoring")
        return

    task_token = record["taskToken"]

    if status != "SUCCEEDED":
        sfn.send_task_failure(taskToken=task_token, error="TextractJobFailed", cause=status)
        return

    lines = []
    next_token = None
    while True:
        kwargs = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token
        page = textract.get_document_text_detection(**kwargs)
        lines += [b["Text"] for b in page["Blocks"] if b["BlockType"] == "LINE"]
        next_token = page.get("NextToken")
        if not next_token:
            break

    sfn.send_task_success(
        taskToken=task_token,
        output=json.dumps({
            "bucket": record["bucket"],
            "key": record["key"],
            "etag": record.get("etag"),
            "extractedText": "\n".join(lines)[:MAX_CHARS],
        }),
    )
