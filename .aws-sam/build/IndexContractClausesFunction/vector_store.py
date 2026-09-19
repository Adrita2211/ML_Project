"""
Thin wrapper over Amazon S3 Vectors + Bedrock Titan embeddings. One index
holds two kinds of documents, told apart by the filterable `docType`
metadata key:

  docType = "playbook"  next-best-action rows (filter: classification, persona)
  docType = "clause"    contract clause chunks  (filter: contractId, section)

Retrieval is "filter first, then rank": the metadata filter narrows to the
right classification or contract using values the rules engine already knows
exactly, and similarity only orders what is left.

Clients are created lazily so importing this module needs no AWS region
(local tests import modules that import this one).
"""
import json
import os
from functools import lru_cache

import boto3

EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "1024"))
PUT_BATCH_SIZE = 100


@lru_cache(maxsize=1)
def _bedrock():
    return boto3.client("bedrock-runtime")


@lru_cache(maxsize=1)
def _vectors():
    return boto3.client("s3vectors")


def _bucket() -> str:
    return os.environ["VECTOR_BUCKET_NAME"]


def _index() -> str:
    return os.environ["VECTOR_INDEX_NAME"]


def embed(text: str) -> list[float]:
    response = _bedrock().invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": text[:8000], "dimensions": EMBEDDING_DIMENSION, "normalize": True}),
    )
    return json.loads(response["body"].read())["embedding"]


def put_documents(documents: list[dict]) -> int:
    """documents: [{"key", "embedText", "metadata"}]. Keys are deterministic,
    so re-ingesting the same source overwrites instead of duplicating."""
    vectors = [
        {"key": d["key"], "data": {"float32": embed(d["embedText"])}, "metadata": d["metadata"]}
        for d in documents
    ]
    for start in range(0, len(vectors), PUT_BATCH_SIZE):
        _vectors().put_vectors(
            vectorBucketName=_bucket(), indexName=_index(), vectors=vectors[start:start + PUT_BATCH_SIZE]
        )
    return len(vectors)


def query(text: str, metadata_filter: dict, top_k: int = 5) -> list[dict]:
    response = _vectors().query_vectors(
        vectorBucketName=_bucket(),
        indexName=_index(),
        topK=top_k,
        queryVector={"float32": embed(text)},
        filter=metadata_filter,
        returnMetadata=True,
        returnDistance=True,
    )
    return [
        {"key": v["key"], "distance": v.get("distance"), "metadata": v.get("metadata", {})}
        for v in response.get("vectors", [])
    ]
