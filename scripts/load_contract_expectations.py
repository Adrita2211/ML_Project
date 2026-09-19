"""
Loads structured contract expectations (CSV or XLSX, e.g. a Model N export or
sample_data/contract_expectations.csv) straight into the contract table,
bypassing Textract/Bedrock.

Builds items with the same function the PDF pipeline uses
(lambdas/contract_items.py), so rows loaded here are indistinguishable from
extracted ones to the comparison worker.

  python scripts/load_contract_expectations.py --dry-run
  python scripts/load_contract_expectations.py --table FormularyAgreementSummaries

Uses your default AWS credentials. Writes to a live table unless --dry-run.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from contract_items import build_contract_id, build_contract_item  # noqa: E402
from tabular import read_rows  # noqa: E402


def _int(value):
    try:
        return int(float(str(value))) if value is not None else None
    except ValueError:
        return None


def to_item(row: dict) -> dict:
    extracted = {
        "contract_id": row.get("contractId"),
        "payer_id": row.get("payerId"),
        "plan_id": row.get("planId"),
        "effective_from": row.get("effectiveFrom"),
        "effective_to": row.get("effectiveTo"),
        "implementation_grace_days": _int(row.get("graceDays")),
    }
    term = {
        "product_id": row.get("productId"),
        "expected_tier": _int(row.get("expectedTier")),
        "expected_status": row.get("expectedStatus"),
        "pa_allowed": row.get("paAllowed"),
        "st_allowed": row.get("stAllowed"),
        "ql_allowed": row.get("qlAllowed"),
        "ql_limit": row.get("qlLimit"),
        "comparator_product_id": row.get("comparatorProductId"),
        "parity_required": row.get("parityRequired"),
        "clause_reference": row.get("clauseReference"),
    }
    contract_id = build_contract_id(extracted)
    return build_contract_item(contract_id, extracted, term, source_key="loaded-from-file")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=os.path.join(ROOT, "sample_data", "contract_expectations.csv"))
    parser.add_argument("--table", default="FormularyAgreementSummaries")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--exclude", default="",
                        help="comma-separated contract ids to skip, e.g. CTR-1001 when that one comes from the PDF")
    parser.add_argument("--dry-run", action="store_true", help="print the items, write nothing")
    args = parser.parse_args()
    excluded = {c.strip().upper() for c in args.exclude.split(",") if c.strip()}

    with open(args.file, "rb") as f:
        rows = read_rows(f.read(), args.file, sheet="Contract_Expectations")
    items = [
        to_item(r) for r in rows
        if r.get("payerId") and r.get("planId") and r.get("productId")
        and str(r.get("contractId", "")).upper() not in excluded
    ]

    for item in items:
        print(f"{item['documentId']}  ->  {item['payerPlanProductKey']}  tier={item['expectedTier']} "
              f"comparator={item['comparatorProductId']} grace={item['graceDays']}")

    if args.dry_run:
        print(f"\ndry run: {len(items)} items would be written to {args.table}")
        return

    import boto3
    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    for item in items:
        table.put_item(Item=item)
    print(f"\nwrote {len(items)} items to {args.table}")


if __name__ == "__main__":
    main()
