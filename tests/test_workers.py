"""
Exercises the three worker Lambdas end to end against in-memory fakes of
DynamoDB, SQS, S3, Bedrock and the vector store. No AWS access needed.
Not a substitute for a deployed run, but it executes every branch of the
control flow (wait / requeue / write / refresh / reason / guardrail / loop
guard) with the real fixture data.

    python -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import unittest
from decimal import Decimal
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # fakes.py, so this file also runs on its own

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "MARKET_SNAPSHOTS_TABLE": "market", "CONTRACT_EXPECTATIONS_TABLE": "contracts",
    "CONTRACT_EXPECTATIONS_INDEX": "PayerPlanProductIndex", "DEVIATION_OUTPUT_TABLE": "deviations",
    "COMPARISON_QUEUE_URL": "https://sqs.example/queue", "STALE_SOURCE_DAYS": "30",
    "VECTOR_BUCKET_NAME": "vb", "VECTOR_INDEX_NAME": "vi",
})

with mock.patch("boto3.resource"), mock.patch("boto3.client"):
    import compare_deviation
    import ingest_market_snapshot
    import load_contract_expectations as loader
    import tabular

SAMPLE = os.path.join(ROOT, "sample_data")


from fakes import FakeSqs, FakeTable  # noqa: E402


def _sqs_event(key, attempt=0):
    return {"Records": [{"body": json.dumps({"payerPlanProductKey": key, "attempt": attempt})}]}


def _fixture_bytes(name):
    with open(os.path.join(SAMPLE, name), "rb") as f:
        return f.read()


def _wire_compare(market, contracts, deviations, sqs):
    compare_deviation.market_table, compare_deviation.contract_table = market, contracts
    compare_deviation.deviation_table, compare_deviation.sqs = deviations, sqs


def _load_market(market, csv_name="market_snapshots.csv"):
    s3 = mock.Mock()
    s3.get_object.return_value = {"Body": io.BytesIO(_fixture_bytes(csv_name))}
    ingest_market_snapshot.s3, ingest_market_snapshot.market_table = s3, market
    event = {"detail": {"bucket": {"name": "b"}, "object": {"key": f"market-data/{csv_name}"}}}
    return ingest_market_snapshot.handler(event, None)


def _load_contracts(contracts):
    for row in tabular.read_rows(_fixture_bytes("contract_expectations.csv"), "contract_expectations.csv"):
        item = loader.to_item(row)
        contracts.items[item["documentId"]] = item
    contracts.pk = "documentId"


class MarketIngestion(unittest.TestCase):
    def test_latest_snapshot_wins_and_counts(self):
        market = FakeTable()
        result = _load_market(market)
        self.assertEqual(result["rowsWritten"], 8)
        # SNP-001/002/003 share a key: the August snapshot (tier 3) must be what is stored
        stored = market.items["PAY-001#PLN-1001#PRD-001"]
        self.assertEqual((stored["snapshotId"], stored["actualTier"]), ("SNP-003", 3))
        self.assertIsNone(market.items["PAY-004#PLN-4001#PRD-001"]["actualTier"])

    def test_older_file_cannot_roll_data_back(self):
        market = FakeTable()
        _load_market(market)
        market.items["PAY-001#PLN-1001#PRD-001"]["snapshotDate"] = "2026-09-30"  # something newer is stored
        result = _load_market(market)
        self.assertGreaterEqual(result["rowsSkippedOlderThanStored"], 1)
        self.assertEqual(market.items["PAY-001#PLN-1001#PRD-001"]["snapshotDate"], "2026-09-30")


class CompareWorker(unittest.TestCase):
    def setUp(self):
        self.market, self.contracts, self.deviations, self.sqs = FakeTable(), FakeTable(), FakeTable(), FakeSqs()
        _load_market(self.market)
        _load_contracts(self.contracts)
        _wire_compare(self.market, self.contracts, self.deviations, self.sqs)

    def run_key(self, key, attempt=0):
        return compare_deviation.handler(_sqs_event(key, attempt), None)

    def test_golden_scenarios_end_to_end(self):
        expected = {  # key -> (status, severity, classifications)
            "PAY-001#PLN-1001#PRD-001": ("Potential deviation - review required", "Critical",
                                         ["Tier downgrade", "Parity deviation"]),
            "PAY-003#PLN-3001#PRD-001": ("Closed - compliant", "None", []),
            "PAY-004#PLN-4001#PRD-001": ("Potential deviation - review required", "Critical", ["Coverage loss"]),
            "PAY-005#PLN-5001#PRD-001": ("Route to data steward", "Data quality", ["Data-quality exception"]),
        }
        for key, (status, severity, classes) in expected.items():
            with self.subTest(key=key):
                self.run_key(key, attempt=compare_deviation.MAX_PARITY_RETRIES)
                row = self.deviations.items[key]
                self.assertEqual((row["status"], row["severity"], row["classifications"]), (status, severity, classes))

    def test_pa_pay002_restriction_escalation_and_decimal_safe(self):
        self.run_key("PAY-002#PLN-2001#PRD-001", attempt=compare_deviation.MAX_PARITY_RETRIES)
        row = self.deviations.items["PAY-002#PLN-2001#PRD-001"]
        self.assertEqual((row["severity"], row["classifications"]), ("High", ["Restriction escalation"]))
        self.assertIsInstance(row["evidenceConfidence"], Decimal)  # would have raised on a float

    def test_missing_comparator_requeues_with_delay_then_settles_as_unknown(self):
        key = "PAY-002#PLN-2001#PRD-001"  # comparator PRD-002 has no snapshot on this plan
        result = self.run_key(key, attempt=0)
        self.assertEqual(result["requeued"], 1)
        self.assertNotIn(key, self.deviations.items)  # no provisional row -> no wasted Bedrock call
        sent = self.sqs.sent[0]
        self.assertEqual(json.loads(sent["MessageBody"])["attempt"], 1)
        self.assertEqual(sent["DelaySeconds"], compare_deviation.PARITY_RETRY_DELAY_SECONDS)
        self.run_key(key, attempt=compare_deviation.MAX_PARITY_RETRIES)
        self.assertEqual(self.deviations.items[key]["flags"]["parityDeviation"], "Unknown")

    def test_no_contract_and_fresh_source_waits(self):
        self.market.items["PAY-009#PLN-9#PRD-001"] = {
            "payerPlanProductKey": "PAY-009#PLN-9#PRD-001", "snapshotDate": "2026-08-31", "sourceFreshnessDays": 1,
        }
        self.assertEqual(self.run_key("PAY-009#PLN-9#PRD-001")["waiting"], 1)
        self.assertNotIn("PAY-009#PLN-9#PRD-001", self.deviations.items)

    def test_an_identical_re_evaluation_writes_nothing_so_it_cannot_start_another_workflow(self):
        key = "PAY-003#PLN-3001#PRD-001"
        self.run_key(key)
        self.deviations.items[key]["evaluatedAt"] = 1          # sentinel: any write would overwrite it
        result = self.run_key(key)
        self.assertEqual((result["unchanged"], result["refreshed"], result["written"]), (1, 0, 0))
        self.assertEqual(self.deviations.items[key]["evaluatedAt"], 1)

    def test_unchanged_finding_refreshes_without_dropping_reasoning(self):
        key = "PAY-003#PLN-3001#PRD-001"
        self.run_key(key)
        self.deviations.items[key]["rootCause"] = "kept"
        self.deviations.items[key]["reasonedAt"] = 123
        self.market.items[key]["snapshotDate"] = "2026-09-30"  # a later snapshot, same finding
        result = self.run_key(key)
        self.assertEqual((result["refreshed"], result["written"]), (1, 0))
        row = self.deviations.items[key]
        self.assertEqual((row["asOfDate"], row["rootCause"], row["reasonedAt"]), ("2026-09-30", "kept", 123))

    def test_changed_finding_replaces_row_and_clears_old_reasoning(self):
        key = "PAY-001#PLN-1001#PRD-001"
        self.run_key(key, attempt=3)
        self.deviations.items[key]["reasonedAt"] = 123
        self.market.items[key]["actualTier"] = 4  # now a different actual value -> different finding
        self.run_key(key, attempt=3)
        self.assertNotIn("reasonedAt", self.deviations.items[key])


if __name__ == "__main__":
    unittest.main()
