"""
Last Step Functions task. Splits the agreement's OCR text into clause chunks,
embeds them, and stores them in the vector index so the reasoning step can
retrieve and cite the exact clause (Sec 5.3 audit trail).

Also writes the dedupe marker. It lives here, at the end, on purpose: the
marker means "this exact file fully succeeded", so a run that failed at
Bedrock or here is retried on the next upload instead of being skipped.
"""
import os

import boto3

import vector_store
from clause_chunker import chunk_agreement

tokens_table = boto3.resource("dynamodb").Table(os.environ["JOB_TOKENS_TABLE"])


def handler(event, context):
    contract_id = event["contractId"]
    chunks = chunk_agreement(event["extractedText"])

    indexed = vector_store.put_documents([
        {
            "key": f"clause#{contract_id}#{chunk['section']}",
            "embedText": chunk["text"],
            "metadata": {
                "docType": "clause",
                "contractId": contract_id,
                "section": chunk["section"],
                "title": chunk["title"],
                "text": chunk["text"],
                "sourceKey": event["key"],
            },
        }
        for chunk in chunks
    ])

    etag = event.get("etag")
    if etag:
        tokens_table.put_item(Item={"jobId": f"dedupe#{event['bucket']}#{event['key']}#{etag}"})

    return {"contractId": contract_id, "indexed": indexed}
