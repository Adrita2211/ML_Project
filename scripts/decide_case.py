"""
Approve or reject a deviation case that is waiting for a human decision.

The deviation-case workflow pauses at a task-token wait. This script reads the
stored token from the case row and resumes the workflow with your decision,
recorded against your AWS identity. A dashboard button would make the same call.

  python scripts/decide_case.py --list
  python scripts/decide_case.py --key "PAY-001#PLN-1001#PRD-001" --decision approve --comment "checked with payer"
  python scripts/decide_case.py --key "PAY-001#PLN-1001#PRD-001" --decision reject

Approving records the decision only. Nothing is sent to a payer or anyone else:
contract Sec 5.2 requires approval before external communication, and the step
that would act on an approved case is not built.

Uses your default AWS credentials against a live account.
"""
import argparse
import json


def pending_cases(table):
    items, kwargs = [], {"FilterExpression": "approvalStatus = :p", "ExpressionAttributeValues": {":p": "Pending approval"}}
    while True:
        page = table.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default="FormularyDeviations")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--list", action="store_true", help="show cases waiting for approval")
    parser.add_argument("--key", help="payerPlanProductKey of the case")
    parser.add_argument("--decision", choices=["approve", "reject"])
    parser.add_argument("--comment")
    args = parser.parse_args()

    import boto3
    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)

    if args.list:
        cases = pending_cases(table)
        for c in cases:
            print(f"{c['payerPlanProductKey']:<32} {c.get('severity'):<10} {', '.join(c.get('classifications', []))}"
                  f"{'   [needs careful review]' if c.get('needsHumanEdit') else ''}")
        print(f"\n{len(cases)} case(s) pending approval")
        return

    if not args.key or not args.decision:
        parser.error("--key and --decision are required (or use --list)")

    item = table.get_item(Key={"payerPlanProductKey": args.key}).get("Item")
    if not item:
        raise SystemExit(f"No case with key {args.key!r}")
    token = item.get("approvalToken")
    if item.get("approvalStatus") != "Pending approval" or not token:
        raise SystemExit(f"Case is not waiting for approval (status: {item.get('approvalStatus')!r}).")

    decided_by = boto3.client("sts", region_name=args.region).get_caller_identity()["Arn"]
    boto3.client("stepfunctions", region_name=args.region).send_task_success(
        taskToken=token,
        output=json.dumps({"decision": args.decision, "decidedBy": decided_by, "comment": args.comment}),
    )
    print(f"Recorded '{args.decision}' for {args.key} as {decided_by}. The workflow will finish shortly.")


if __name__ == "__main__":
    main()
