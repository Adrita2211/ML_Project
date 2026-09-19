"""In-memory stand-ins for AWS services, just enough for the worker tests."""
import re

from botocore.exceptions import ClientError


def has_float(value):
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(has_float(v) for v in value.values())
    if isinstance(value, list):
        return any(has_float(v) for v in value)
    return False


def _conditional_failure(operation):
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, operation)


class FakeTable:
    """PK defaults to payerPlanProductKey. Rejects floats like real DynamoDB."""

    def __init__(self, pk="payerPlanProductKey"):
        self.pk, self.items = pk, {}

    def get_item(self, Key):
        item = self.items.get(Key[self.pk])
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None):
        if has_float(Item):
            raise TypeError("Float types are not supported. Use Decimal types instead.")
        existing = self.items.get(Item[self.pk])
        if ConditionExpression and existing is not None:  # the snapshot-date guard used by market ingestion
            stored = existing.get("snapshotDate")
            if not (stored is not None and stored <= ExpressionAttributeValues[":d"]):
                raise _conditional_failure("PutItem")
        self.items[Item[self.pk]] = dict(Item)

    def _check(self, condition, item, names, values):
        for clause in condition.split(" AND "):
            clause = clause.strip()
            exists = re.fullmatch(r"attribute_exists\((\w+)\)", clause)
            missing = re.fullmatch(r"attribute_not_exists\((\w+)\)", clause)
            equals = re.fullmatch(r"(#?\w+)\s*=\s*(:\w+)", clause)
            if exists:
                ok = item is not None and exists.group(1) in item
            elif missing:
                ok = item is None or missing.group(1) not in item
            elif equals:
                attr = names.get(equals.group(1), equals.group(1))
                ok = item is not None and item.get(attr) == values[equals.group(2)]
            else:
                raise NotImplementedError(f"condition not supported by FakeTable: {clause}")
            if not ok:
                raise _conditional_failure("UpdateItem")

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None, ConditionExpression=None,
                    ExpressionAttributeNames=None, ReturnValues=None):
        values, names = ExpressionAttributeValues or {}, ExpressionAttributeNames or {}
        if has_float(values):
            raise TypeError("Float types are not supported. Use Decimal types instead.")
        item = self.items.get(Key[self.pk])
        if ConditionExpression:
            self._check(ConditionExpression, item, names, values)
        if item is None:
            raise KeyError(Key)

        match = re.fullmatch(r"\s*SET (.*?)(?: REMOVE (.*))?\s*", UpdateExpression, re.S)
        for assignment in re.split(r",\s*(?=\w+\s*=)", match.group(1)):
            name, placeholder = [p.strip() for p in assignment.split("=")]
            item[names.get(name, name)] = values[placeholder]
        for name in [n.strip() for n in (match.group(2) or "").split(",") if n.strip()]:
            item.pop(names.get(name, name), None)
        return {"Attributes": dict(item)} if ReturnValues == "ALL_NEW" else {}


    def query(self, IndexName, KeyConditionExpression, **_):
        wanted = KeyConditionExpression._values[1]  # boto3's Key("x").eq(value) keeps (Key, value)
        return {"Items": [dict(i) for i in self.items.values() if i.get("payerPlanProductKey") == wanted]}


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)


class FakeSns:
    def __init__(self):
        self.published = []

    def publish(self, **kwargs):
        self.published.append(kwargs)


class FakeSfn:
    def __init__(self):
        self.successes = []

    def send_task_success(self, taskToken, output):
        self.successes.append({"taskToken": taskToken, "output": output})
