"""
The synthetic contract PDFs must state exactly the terms the CSV expectations hold for the same contracts (and the
market-data file was built against those), so an outcome proven with the CSV is still proven when the contract arrives
as a PDF. Reads the committed PDFs; skipped without pypdf.
"""
import csv
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

import generate_sample_contracts as gen  # noqa: E402


def _text(contract):
    path = os.path.join(ROOT, "sample_data", gen.output_name(contract))
    return "\n".join(p.extract_text() for p in PdfReader(path).pages)


def _flat(text):
    return re.sub(r"\s+", " ", text)


def _csv_rows():
    with open(os.path.join(ROOT, "sample_data", "contract_expectations.csv"), encoding="utf-8") as f:
        return {r["contract_id"]: r for r in csv.DictReader(f)}


@unittest.skipUnless(PdfReader, "pip install pypdf to read the sample PDFs")
class SampleContractsMatchTheCsv(unittest.TestCase):
    def test_every_pdf_states_the_csv_terms(self):
        rows = _csv_rows()
        for contract in gen.CONTRACTS:
            row = rows[contract["contract_id"]]
            with self.subTest(contract=contract["contract_id"]):
                text = _flat(_text(contract))
                for key in ("contract_id", "payer_id", "plan_id", "product_id"):
                    self.assertIn(row[key], text, key)
                self.assertIn(f"Tier {row['expected_tier']} {row['expected_status']}", text)
                self.assertIn("ST is permitted." if row["st_allowed"] == "Y" else "ST is not permitted.", text)
                self.assertIn("PA is not permitted." if row["pa_allowed"] == "N" else "PA is permitted", text)
                if row["ql_allowed"] == "Y":
                    self.assertIn(row["ql_limit"].replace(" / ", " per "), text)
                else:
                    self.assertIn("QL is not permitted.", text)
                self.assertIn(f"within {row['grace_days']} calendar days", text)
                if row["parity_required"] == "Y":
                    self.assertIn(f"No less favorable than {row['comparator_product_id']}", text)
                else:
                    self.assertIn("no parity commitment", text.lower())
                    self.assertNotIn("PRD-002", text)

    def test_the_term_dates_match(self):
        from datetime import datetime
        rows = _csv_rows()
        for contract in gen.CONTRACTS:
            row = rows[contract["contract_id"]]
            start = datetime.strptime(contract["term_start"], "%B %d, %Y").date().isoformat()
            end = datetime.strptime(contract["term_end"], "%B %d, %Y").date().isoformat()
            self.assertEqual((start, end), (row["effective_from"], row["effective_to"]), contract["contract_id"])

    def test_no_other_contracts_ids_leak_into_a_pdf(self):
        ids = {c["contract_id"] for c in gen.CONTRACTS}
        for contract in gen.CONTRACTS:
            text = _text(contract)
            for other in ids - {contract["contract_id"]}:
                self.assertNotIn(other, text, f"{contract['contract_id']} mentions {other}")

    def test_the_market_data_file_has_a_contract_for_each_pdf(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        wb = openpyxl.load_workbook(os.path.join(ROOT, "sample_data", "MMIT_data1.xlsx"), read_only=True)
        rows = list(wb["Deviations"].iter_rows(values_only=True))
        header = [str(h) for h in rows[0]]
        golden = {(r[header.index("contract_id")], r[header.index("payer_id")], r[header.index("plan_id")])
                  for r in rows[1:] if r[header.index("contract_id")]}
        for contract in gen.CONTRACTS:
            self.assertIn((contract["contract_id"], contract["payer_id"], contract["plan_id"]), golden)


if __name__ == "__main__":
    unittest.main()
