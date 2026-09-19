"""
Tests for the deterministic validator that sits between the Contract Parser
agent and the database (lambdas/extraction_logic.py). No AWS access needed.

The point of the validator is that everything downstream joins on what the
agent extracted, so an invented id, a date in the wrong format, or an
unreadable answer must never be saved silently.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import contract_items  # noqa: E402
import extraction_logic as ex  # noqa: E402
import tabular  # noqa: E402

SOURCE = """
Synthetic Payer Formulary Access Agreement  Agreement ID CTR-1001
Term January 1, 2026 through December 31, 2026
Exhibit A  Payer ID PAY-001  Plan ID PLN-1001  Plan name NorthStar Commercial Plus
Product ID PRD-001  Comparator product ID PRD-002
3.2 Implementation grace period A discrepancy observed within 10 calendar days may be classified as administrative lag.
"""


def good_output(**overrides):
    """What a competent parser returns for the sample agreement."""
    out = {
        "contract_id": "CTR-1001", "payer_id": "PAY-001", "payer_name": "NorthStar Health Plan",
        "plan_id": "PLN-1001", "plan_name": "NorthStar Commercial Plus", "manufacturer_name": "Demo Pharma, Inc.",
        "effective_from": "2026-01-01", "effective_to": "2026-12-31", "implementation_grace_days": 10,
        "coverage_terms": [{
            "product_id": "PRD-001", "product_name": "BrandAlpha", "strength": None, "expected_tier": 2,
            "expected_status": "Preferred", "pa_allowed": "Y", "st_allowed": "N", "ql_allowed": "Y",
            "ql_limit": "1 package / 28 days", "comparator_product_id": "PRD-002",
            "comparator_product_name": "BrandBeta", "parity_required": "Y", "clause_reference": "Sections 2.1-2.4",
        }],
        "rebate_terms": [], "key_dates_and_amounts": ["Term ends 2026-12-31"], "executive_summary": "Tier 2 commitment.",
    }
    out.update(overrides)
    return out


def parse(output, source=SOURCE):
    text = output if isinstance(output, str) else json.dumps(output)
    return ex.parse(text, source)


class HappyPath(unittest.TestCase):
    def test_a_good_extraction_is_accepted_unchanged(self):
        result = parse(good_output())
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])
        term = result["extracted"]["coverage_terms"][0]
        self.assertEqual((term["product_id"], term["expected_tier"], term["pa_allowed"], term["st_allowed"]),
                         ("PRD-001", 2, "Y", "N"))
        self.assertEqual((result["extracted"]["effective_from"], result["extracted"]["implementation_grace_days"]),
                         ("2026-01-01", 10))

    def test_the_result_is_json_safe_for_the_workflow(self):
        json.dumps(parse(good_output()))

    def test_code_fences_and_chatter_around_the_json_are_tolerated(self):
        wrapped = "Here is the extraction:\n```json\n" + json.dumps(good_output()) + "\n```\nLet me know if you need more."
        self.assertTrue(parse(wrapped)["ok"])

    def test_what_it_extracts_joins_to_the_market_data(self):
        """The whole pipeline turns on this: contract keys must equal market snapshot keys."""
        extracted = parse(good_output())["extracted"]
        item = contract_items.build_contract_item(
            contract_items.build_contract_id(extracted), extracted, extracted["coverage_terms"][0])
        with open(os.path.join(ROOT, "sample_data", "market_snapshots.csv"), "rb") as f:
            rows = tabular.read_rows(f.read(), "market_snapshots.csv")
        market_keys = {f"{r['payerId']}#{r['planId']}#{r['productId']}" for r in rows}
        self.assertIn(item["payerPlanProductKey"], market_keys)
        self.assertEqual(item["graceDays"], 10)

    def test_the_real_contract_pdf(self):
        try:
            import pypdf
        except ImportError:
            self.skipTest("pypdf not installed")
        pdf = os.path.join(ROOT, "sample_data", "Synthetic_Payer_Formulary_Access_Agreement.pdf")
        text = "\n".join(p.extract_text() for p in pypdf.PdfReader(pdf).pages)
        result = parse(good_output(), text)
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [], "every id a good parser reads must be found in the real OCR text")


class Grounding(unittest.TestCase):
    def test_an_invented_id_is_discarded_not_saved(self):
        out = good_output(payer_id="PAY-777")
        result = parse(out)
        self.assertIsNone(result["extracted"]["payer_id"])
        self.assertTrue(any("payer_id" in i and "does not appear" in i for i in result["issues"]))
        self.assertTrue(result["ok"])  # still identified by name

    def test_an_invented_product_and_comparator_id_are_discarded(self):
        out = good_output()
        out["coverage_terms"][0].update(product_id="PRD-999", comparator_product_id="PRD-888")
        term = parse(out)["extracted"]["coverage_terms"][0]
        self.assertEqual((term["product_id"], term["comparator_product_id"]), (None, None))
        self.assertEqual(term["product_name"], "BrandAlpha")  # kept: the row is still usable

    def test_ocr_that_splits_an_id_still_grounds_it(self):
        spaced = SOURCE.replace("PAY-001", "PAY - 001").replace("PLN-1001", "PLN 1001")
        result = parse(good_output(), spaced)
        self.assertEqual((result["extracted"]["payer_id"], result["extracted"]["plan_id"]), ("PAY-001", "PLN-1001"))
        self.assertEqual(result["issues"], [])

    def test_a_document_that_never_states_an_id_yields_none_not_a_guess(self):
        result = parse(good_output(), "An agreement with no identifiers at all. Tier 2.")
        e = result["extracted"]
        self.assertEqual((e["contract_id"], e["payer_id"], e["plan_id"]), (None, None, None))
        self.assertIsNone(e["coverage_terms"][0]["product_id"])


class Normalization(unittest.TestCase):
    def test_dates_are_converted_to_iso_because_the_comparison_worker_compares_text(self):
        for written, iso in (("January 1, 2026", "2026-01-01"), ("Dec 31, 2026", "2026-12-31"),
                             ("01/01/2026", "2026-01-01"), ("2026-01-01T00:00:00", "2026-01-01")):
            with self.subTest(written=written):
                self.assertEqual(parse(good_output(effective_from=written))["extracted"]["effective_from"], iso)

    def test_an_unreadable_date_is_dropped_and_reported(self):
        result = parse(good_output(effective_to="the end of next year"))
        self.assertIsNone(result["extracted"]["effective_to"])
        self.assertTrue(any("effective_to" in i for i in result["issues"]))

    def test_tiers_flags_and_grace_days_are_coerced(self):
        out = good_output(implementation_grace_days="ten")
        out["coverage_terms"][0].update(expected_tier="Tier 2", pa_allowed="Yes", st_allowed="no",
                                        ql_allowed="N/A", parity_required=True)
        e = parse(out)["extracted"]
        term = e["coverage_terms"][0]
        self.assertEqual((term["expected_tier"], term["pa_allowed"], term["st_allowed"], term["ql_allowed"],
                          term["parity_required"]), (2, "Y", "N", None, "Y"))
        self.assertIsNone(e["implementation_grace_days"])

    def test_an_implausible_tier_is_dropped_and_reported(self):
        out = good_output()
        out["coverage_terms"][0]["expected_tier"] = "Preferred"
        result = parse(out)
        self.assertIsNone(result["extracted"]["coverage_terms"][0]["expected_tier"])
        self.assertTrue(any("expected_tier" in i for i in result["issues"]))

    def test_junk_in_the_wrong_shape_does_not_crash(self):
        out = good_output(rebate_terms="none", key_dates_and_amounts={"a": 1}, plan_name={"x": 1})
        out["coverage_terms"].append("not a dict")
        result = parse(out)
        self.assertTrue(result["ok"])
        self.assertEqual((result["extracted"]["rebate_terms"], result["extracted"]["key_dates_and_amounts"]), ([], []))
        self.assertIsNone(result["extracted"]["plan_name"])


class Rejection(unittest.TestCase):
    """Nothing is saved for these: the workflow fails visibly instead of writing a placeholder row."""

    def test_output_that_is_not_json(self):
        for text in ("I could not read this contract.", "", None, "[1, 2, 3]"):
            with self.subTest(text=text):
                result = ex.parse(text, SOURCE)
                self.assertFalse(result["ok"])
                self.assertEqual(result["extracted"], {})

    def test_no_coverage_terms(self):
        result = parse(good_output(coverage_terms=[]))
        self.assertFalse(result["ok"])
        self.assertTrue(any("No coverage terms" in i for i in result["issues"]))

    def test_terms_that_name_no_product_are_dropped_then_rejected(self):
        out = good_output(coverage_terms=[{"expected_tier": 2}])
        result = parse(out)
        self.assertFalse(result["ok"])
        self.assertTrue(any("no product" in i for i in result["issues"]))

    def test_payer_not_identified(self):
        result = parse(good_output(payer_id=None, payer_name=None))
        self.assertFalse(result["ok"])
        self.assertTrue(any("payer" in i.lower() for i in result["issues"]))

    def test_a_grounded_payer_id_alone_is_enough_to_identify_the_payer(self):
        self.assertTrue(parse(good_output(payer_name=None))["ok"])

    def test_the_number_of_terms_is_bounded(self):
        many = good_output(coverage_terms=[{"product_name": f"Drug {i}", "expected_tier": 2} for i in range(500)])
        self.assertEqual(len(parse(many)["extracted"]["coverage_terms"]), ex.MAX_TERMS)


if __name__ == "__main__":
    unittest.main()
