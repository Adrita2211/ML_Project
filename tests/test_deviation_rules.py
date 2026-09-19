"""
Local tests for the deterministic rules and the tabular/chunking helpers.
No AWS access needed:   python -m unittest discover -s tests -v

The golden test replays sample_data/MMIT_data1.xlsx (sheet "Deviations")
through lambdas/deviation_rules.py using the fixture CSVs.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import deviation_rules as rules  # noqa: E402
import tabular  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample_data")


def _rows(name, sheet=None):
    with open(os.path.join(SAMPLE, name), "rb") as f:
        return tabular.read_rows(f.read(), name, sheet)


def _keyed_contracts():
    return {f"{r['payerId']}#{r['planId']}#{r['productId']}": r for r in _rows("contract_expectations.csv")}


def _latest_snapshots():
    latest = {}
    for r in _rows("market_snapshots.csv"):
        key = f"{r['payerId']}#{r['planId']}#{r['productId']}"
        if key not in latest or r["snapshotDate"] >= latest[key]["snapshotDate"]:
            latest[key] = r
    return latest


def _evaluate(key):
    contracts, snaps = _keyed_contracts(), _latest_snapshots()
    contract = contracts.get(key)
    snap = snaps[key]
    comparator = None
    if contract and contract.get("comparatorProductId"):
        payer, plan, _ = key.split("#")
        comparator = snaps.get(f"{payer}#{plan}#{contract['comparatorProductId']}")
    return rules.evaluate(contract, snap, comparator)


class GoldenSheet(unittest.TestCase):
    # Column in the golden sheet -> key in the engine's result.
    FIELDS = {
        "tier_deviation": ("flags", "tierDeviation"),
        "st_deviation": ("flags", "stDeviation"),
        "coverage_deviation": ("flags", "coverageDeviation"),
        "parity_deviation": ("flags", "parityDeviation"),
        "severity": (None, "severity"),
        "status": (None, "status"),
    }
    # The fixtures hold no snapshot for DEV-002's comparator (PRD-002 on PAY-002),
    # so the engine reports parity 'Unknown' where the golden sheet says 'N'.
    KNOWN_DIFFERENCES = {("DEV-002", "parity_deviation")}

    def test_replay(self):
        golden = _rows("MMIT_data1.xlsx", "Deviations")
        self.assertEqual(len(golden), 5)
        for row in golden:
            key = f"{row['payerId']}#{row['planId']}#{row['productId']}"
            result = _evaluate(key)
            for column, (group, name) in self.FIELDS.items():
                actual = result[group][name] if group else result[name]
                expected = row[tabular.camelize(column)]
                if (row["deviationId"], column) in self.KNOWN_DIFFERENCES:
                    continue
                with self.subTest(deviation=row["deviationId"], field=column):
                    self.assertEqual(actual, expected)


class Rules(unittest.TestCase):
    CONTRACT = {"expectedTier": 2, "expectedStatus": "Preferred", "paAllowed": "Y", "stAllowed": "N",
                "qlAllowed": "Y", "parityRequired": "N", "graceDays": 10,
                "effectiveFrom": "2026-01-01", "effectiveTo": "2026-12-31"}
    SNAP = {"actualTier": 2, "actualStatus": "Preferred", "paFlag": "Y", "stFlag": "N", "qlFlag": "Y",
            "coverageFlag": "Y", "snapshotDate": "2026-08-31", "effectiveDate": "2026-08-01",
            "sourceFreshnessDays": 1}

    def test_compliant(self):
        r = rules.evaluate(self.CONTRACT, self.SNAP)
        self.assertEqual((r["status"], r["severity"], r["classifications"]), (rules.STATUS_COMPLIANT, "None", []))

    def test_better_tier_than_contracted_is_not_a_deviation(self):
        r = rules.evaluate({**self.CONTRACT, "expectedTier": 3}, self.SNAP)
        self.assertEqual(r["flags"]["tierDeviation"], "N")

    def test_st_where_prohibited_is_restriction_escalation(self):
        r = rules.evaluate(self.CONTRACT, {**self.SNAP, "stFlag": "Y"})
        self.assertEqual(r["classifications"], ["Restriction escalation"])
        self.assertEqual(r["severity"], "High")
        self.assertEqual(r["routing"], ["Contracting", "FRM", "Patient Services"])

    def test_pa_only_is_medium(self):
        r = rules.evaluate({**self.CONTRACT, "paAllowed": "N"}, self.SNAP)
        self.assertEqual((r["classifications"], r["severity"]), (["Restriction escalation"], "Medium"))

    def test_expected_preferred_actual_non_preferred_same_tier_number(self):
        r = rules.evaluate(self.CONTRACT, {**self.SNAP, "actualStatus": "Non-preferred"})
        self.assertEqual(r["flags"]["tierDeviation"], "Y")

    def test_stale_source_routes_to_data_steward_without_flagging(self):
        r = rules.evaluate(self.CONTRACT, {**self.SNAP, "actualTier": 3, "sourceFreshnessDays": 125})
        self.assertEqual((r["status"], r["classifications"]), (rules.STATUS_DATA_QUALITY, ["Data-quality exception"]))
        self.assertIn("STALE_SOURCE", r["dataQualityCodes"])

    def test_grace_period_is_an_ambiguity_not_a_suppression(self):
        r = rules.evaluate(self.CONTRACT, {**self.SNAP, "actualTier": 3, "effectiveDate": "2026-08-25"})
        self.assertEqual(r["status"], rules.STATUS_DEVIATION)
        self.assertTrue(r["withinGracePeriod"])
        self.assertIn("GRACE_PERIOD", r["ambiguityCodes"])

    def test_outside_contract_term_is_not_evaluated(self):
        r = rules.evaluate({**self.CONTRACT, "effectiveTo": "2026-06-30"}, self.SNAP)
        self.assertEqual(r["status"], rules.STATUS_OUT_OF_TERM)

    def test_parity_worse_tier_and_more_um(self):
        contract = {**self.CONTRACT, "parityRequired": "Y", "comparatorProductId": "PRD-002"}
        worse = rules.evaluate(contract, {**self.SNAP, "actualTier": 3}, {**self.SNAP, "actualTier": 2})
        self.assertEqual(worse["flags"]["parityDeviation"], "Y")
        more_um = rules.evaluate(contract, self.SNAP, {**self.SNAP, "qlFlag": "N"})
        self.assertEqual(more_um["flags"]["parityDeviation"], "Y")
        equal = rules.evaluate(contract, self.SNAP, dict(self.SNAP))
        self.assertEqual(equal["flags"]["parityDeviation"], "N")

    def test_missing_comparator_is_unknown_and_pending(self):
        contract = {**self.CONTRACT, "parityRequired": "Y", "comparatorProductId": "PRD-002"}
        r = rules.evaluate(contract, self.SNAP, None)
        self.assertEqual(r["flags"]["parityDeviation"], "Unknown")
        self.assertTrue(rules.parity_pending(contract, None, r))

    def test_signature_ignores_dates_but_tracks_findings(self):
        a = rules.evaluate(self.CONTRACT, {**self.SNAP, "actualTier": 3})
        b = rules.evaluate(self.CONTRACT, {**self.SNAP, "actualTier": 3, "snapshotDate": "2026-09-30",
                                            "effectiveDate": "2026-08-01"})
        c = rules.evaluate(self.CONTRACT, {**self.SNAP, "actualTier": 4})
        self.assertEqual(rules.signature(a), rules.signature(b))
        self.assertNotEqual(rules.signature(a), rules.signature(c))

    def test_classification_aliases(self):
        self.assertEqual(rules.normalize_classification("Any data-quality exception"), "Data-quality exception")
        self.assertEqual(rules.normalize_classification("Potential parity deviation"), "Parity deviation")
        self.assertEqual(rules.normalize_classification("tier downgrade"), "Tier downgrade")


class Tabular(unittest.TestCase):
    def test_camelize(self):
        self.assertEqual(tabular.camelize("source_freshness_days"), "sourceFreshnessDays")
        self.assertEqual(tabular.camelize("payerId"), "payerId")
        self.assertEqual(tabular.camelize("Column1"), "column1")

    def test_csv_blank_becomes_none(self):
        rows = _rows("market_snapshots.csv")
        not_covered = next(r for r in rows if r["snapshotId"] == "SNP-007")
        self.assertIsNone(not_covered["actualTier"])
        self.assertEqual(not_covered["actualStatus"], "Not covered")

    def test_xlsx_dates_are_iso_strings(self):
        golden = _rows("MMIT_data1.xlsx", "Deviations")
        self.assertEqual(golden[0]["asOfDate"], "2026-08-31")

    def test_playbook_fixture(self):
        rows = _rows("persona_nba_playbook.csv")
        self.assertEqual(len(rows), 7)
        self.assertEqual({r["approvalRequired"] for r in rows}, {"Y", "N"})


class ContractItems(unittest.TestCase):
    def test_keys_align_with_market_side(self):
        import contract_items as ci
        extracted = {"contract_id": "CTR-1001", "payer_id": "PAY-001", "plan_id": "PLN-1001",
                     "effective_from": "2026-01-01", "implementation_grace_days": 10}
        item = ci.build_contract_item(ci.build_contract_id(extracted), extracted,
                                      {"product_id": "PRD-001", "expected_tier": 2})
        # market_snapshots rows are keyed payerId#planId#productId - these must be identical
        self.assertEqual(item["payerPlanProductKey"], "PAY-001#PLN-1001#PRD-001")
        self.assertEqual(item["documentId"], "ctr-1001#PAY-001#PLN-1001#PRD-001")
        self.assertEqual(item["graceDays"], 10)

    def test_sparse_document_still_gets_distinct_keys(self):
        import contract_items as ci
        a = ci.build_contract_item("c", {"payer_name": "Acme"}, {"product_name": "Drug A"})
        b = ci.build_contract_item("c", {"payer_name": "Acme"}, {"product_name": "Drug B"})
        self.assertNotEqual(a["documentId"], b["documentId"])


class ClauseChunker(unittest.TestCase):
    TEXT = "\n".join([
        "Title page noise", "1. Parties, scope and definitions", "1.1 Parties", "Agreement between A and B.",
        "Page 2", "2.1 Tier commitment", "Payer shall keep Tier 2.", "Exhibit B - Expected state",
        "Tier Tier 2 Preferred", "Illustrative signatures", "Name: ____", "Legal disclaimer",
    ])

    def test_splits_on_clauses_and_exhibits(self):
        import clause_chunker
        chunks = clause_chunker.chunk_agreement(self.TEXT)
        self.assertEqual([c["section"] for c in chunks], ["1.1", "2.1", "Exhibit B"])

    def test_page_noise_and_signature_block_are_excluded(self):
        import clause_chunker
        joined = " ".join(c["text"] for c in clause_chunker.chunk_agreement(self.TEXT))
        for unwanted in ("Page 2", "Name:", "Legal disclaimer", "Title page noise"):
            self.assertNotIn(unwanted, joined)

    def test_a_wrapped_sentence_starting_with_exhibit_is_not_a_heading(self):
        # Found by the real run: clause 1.4 wrapped so a line began "Exhibit B. If the Payer publishes ...", which
        # was read as a second Exhibit B and made the vector write fail on a duplicate key.
        import clause_chunker
        text = "\n".join(["1.4 Contracted Tier", "Tier 2 under the taxonomy shown in", "Exhibit B. If the Payer publishes",
                          "another label, the crosswalk governs.", "Exhibit B - Expected state", "Tier Tier 2 Preferred"])
        chunks = clause_chunker.chunk_agreement(text)
        self.assertEqual([c["section"] for c in chunks], ["1.4", "Exhibit B"])
        self.assertIn("another label", chunks[0]["text"])

    def test_a_repeated_section_label_can_never_produce_duplicate_vector_keys(self):
        import clause_chunker
        text = "\n".join(["2.1 Tier commitment", "one.", "2.1 Tier commitment again", "two."])
        sections = [c["section"] for c in clause_chunker.chunk_agreement(text)]
        self.assertEqual(sections, ["2.1", "2.1 (2)"])

    def test_every_sample_pdf_chunks_into_unique_clauses(self):
        try:
            import pypdf
        except ImportError:
            self.skipTest("pypdf not installed")
        import glob
        import clause_chunker
        pdfs = glob.glob(os.path.join(SAMPLE, "Synthetic_Payer_Formulary_Access_Agreement*.pdf"))
        self.assertGreaterEqual(len(pdfs), 4)
        for pdf in pdfs:
            text = "\n".join(p.extract_text() for p in pypdf.PdfReader(pdf).pages)
            sections = [c["section"] for c in clause_chunker.chunk_agreement(text)]
            with self.subTest(pdf=os.path.basename(pdf)):
                self.assertEqual(len(sections), len(set(sections)), "duplicate section labels")
                self.assertEqual(len(sections), 25)

    def test_real_contract_pdf(self):
        try:
            import pypdf
        except ImportError:
            self.skipTest("pypdf not installed")
        import clause_chunker
        pdf = os.path.join(SAMPLE, "Synthetic_Payer_Formulary_Access_Agreement.pdf")
        text = "\n".join(p.extract_text() for p in pypdf.PdfReader(pdf).pages)
        by_section = {c["section"]: c["text"] for c in clause_chunker.chunk_agreement(text)}
        self.assertEqual(len(by_section), 25)
        self.assertIn("Tier 2", by_section["2.1"])
        self.assertIn("10 calendar days", by_section["3.2"])
        self.assertNotIn("Legal and data disclaimer", by_section["Exhibit D"])


if __name__ == "__main__":
    unittest.main()
