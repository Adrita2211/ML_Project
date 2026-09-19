"""
Tests for the contract workflow (statemachine/pdf_summarizer.asl.json): the
graph, the real JSONata expressions rendered into the real Lambda handlers, and
the template facts the workflow depends on. No AWS access needed.

Same caveats as test_case_workflow.py: the expression tests need
`pip install jsonata-python`, and that is a third-party engine rather than Step
Functions' own.
"""
import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "SUMMARIES_TABLE": "contracts", "SUMMARY_READY_TOPIC_ARN": "arn:aws:sns:us-east-1:1:ready",
    "JOB_TOKENS_TABLE": "tokens", "TEXTRACT_SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:1:tx",
    "TEXTRACT_ROLE_ARN": "arn:aws:iam::1:role/tx", "VECTOR_BUCKET_NAME": "vb", "VECTOR_INDEX_NAME": "vi",
})

with mock.patch("boto3.resource"), mock.patch("boto3.client"):
    import index_contract_clauses
    import parse_extraction
    import save_and_notify
    import start_textract_job
import extraction_logic  # noqa: E402
from fakes import FakeSfn, FakeSns, FakeTable  # noqa: E402
from test_case_workflow import jsonata, load_template, render, yaml  # noqa: E402
from test_extraction import SOURCE, good_output  # noqa: E402

ASL_PATH = os.path.join(ROOT, "statemachine", "pdf_summarizer.asl.json")
with open(ASL_PATH, encoding="utf-8") as f:
    ASL = json.load(f)
STATES = ASL["States"]

SUBSTITUTIONS = {
    "StartTextractJobFunctionArn", "ParseExtractionFunctionArn", "SaveAndNotifyFunctionArn",
    "IndexContractClausesFunctionArn", "ContractParserHarnessArn",
}
OCR = SOURCE * 3  # stands in for what resume_workflow hands back


def _next(state):
    targets = [state.get("Next"), state.get("Default")]
    targets += [c.get("Next") for c in state.get("Choices", [])] + [c.get("Next") for c in state.get("Catch", [])]
    return [t for t in targets if t]


def _reachable(skip=()):
    seen, stack = set(), [ASL["StartAt"]]
    while stack:
        name = stack.pop()
        if name in seen or name in skip:
            continue
        seen.add(name)
        stack += _next(STATES[name])
    return seen


class WorkflowDefinition(unittest.TestCase):
    def test_jsonata_and_bounded(self):
        self.assertEqual(ASL["QueryLanguage"], "JSONata")
        self.assertLessEqual(ASL["TimeoutSeconds"], 3600)

    def test_every_transition_is_real_and_every_state_reachable(self):
        for name, state in STATES.items():
            for target in _next(state):
                self.assertIn(target, STATES, f"{name} -> {target}")
        self.assertEqual(_reachable(), set(STATES))

    def test_nothing_is_saved_without_passing_the_validator(self):
        self.assertNotIn("SaveAndNotify", _reachable(skip={"ParseExtraction"}))
        self.assertNotIn("IndexClauses", _reachable(skip={"ParseExtraction"}))

    def test_clauses_are_only_indexed_after_the_row_is_saved(self):
        self.assertNotIn("IndexClauses", _reachable(skip={"SaveAndNotify"}))

    def test_an_unchanged_file_reaches_the_end_without_an_agent(self):
        self.assertIn("AlreadyProcessed", _reachable(skip={"ContractParser"}))

    def test_the_agent_is_bounded_retried_and_its_failure_is_loud_not_silent(self):
        agent = STATES["ContractParser"]
        self.assertTrue(agent["Resource"].endswith("invokeHarness"))
        self.assertLessEqual(agent["Arguments"]["MaxIterations"], 5)
        self.assertLessEqual(agent["Arguments"]["TimeoutSeconds"], 900)
        self.assertNotIn("SystemPrompt", agent["Arguments"], "the fixed prompt lives on the harness, in one place")
        self.assertTrue(any("BedrockAgentCore.ThrottlingException" in r["ErrorEquals"] for r in agent["Retry"]))
        self.assertEqual(agent["Catch"][0]["Next"], "ExtractionFailed")
        self.assertEqual(STATES["ExtractionUsable"]["Default"], "ExtractionFailed")
        self.assertEqual(STATES["ExtractionFailed"]["Type"], "Fail")

    def test_lambda_states_retry_service_errors_and_catch_the_rest(self):
        for name in ("ParseExtraction", "SaveAndNotify", "IndexClauses"):
            self.assertTrue(STATES[name].get("Retry"), name)
            self.assertTrue(STATES[name].get("Catch"), name)

    def test_the_old_extraction_lambda_is_gone(self):
        self.assertNotIn("SummarizeWithBedrock", STATES)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "lambdas", "summarize_with_bedrock.py")))

    def test_substitutions_used_are_the_ones_expected(self):
        self.assertEqual(set(re.findall(r"\$\{(\w+)\}", json.dumps(ASL))), SUBSTITUTIONS)


def _wire():
    contracts, sns, tokens = FakeTable(pk="documentId"), FakeSns(), FakeTable(pk="jobId")
    save_and_notify.ddb, save_and_notify.sns = contracts, sns
    index_contract_clauses.tokens_table = tokens
    start_textract_job.tokens_table = tokens
    return contracts, sns, tokens


@unittest.skipUnless(jsonata, "pip install jsonata-python to evaluate the state machine's JSONata expressions")
class WorkflowExpressions(unittest.TestCase):
    def setUp(self):
        self.contracts, self.sns, self.tokens = _wire()
        self.callback = {"bucket": "b", "key": "contracts/CTR-1001.pdf", "etag": "abc123", "extractedText": OCR}
        self.vars = {
            "bucket": "b", "key": "contracts/CTR-1001.pdf", "etag": "abc123", "extractedText": OCR, "skipped": False,
            "parserText": json.dumps(good_output()),
        }

    def _assign(self, callback):
        return render(STATES["StartTextractJob"]["Assign"], {}, {"result": json.loads(json.dumps(callback))})

    def test_start_reads_the_eventbridge_event_and_the_callback(self):
        event = {"detail": {"bucket": {"name": "b"}, "object": {"key": "k", "etag": "e"}}}
        payload = render(STATES["StartTextractJob"]["Arguments"]["Payload"], {}, {"input": event, "context": {"Task": {"Token": "T"}}})
        self.assertEqual((payload["detail"], payload["taskToken"]), (event["detail"], "T"))

        normal = self._assign(self.callback)
        self.assertEqual((normal["skipped"], normal["etag"], normal["extractedText"]), (False, "abc123", OCR))
        skipped = self._assign({**self.callback, "extractedText": "", "skipped": True})
        self.assertIs(skipped["skipped"], True)
        no_etag = self._assign({**self.callback, "etag": None})  # a token record written before etags were stored
        self.assertIsNone(no_etag["etag"])

    def test_skip_check_routes_on_the_flag(self):
        body = STATES["SkipCheck"]["Choices"][0]["Condition"][2:-2]
        self.assertTrue(jsonata.Jsonata(body).evaluate(None, {"skipped": True}))
        self.assertFalse(jsonata.Jsonata(body).evaluate(None, {"skipped": False}))

    def test_the_agent_is_given_the_ocr_text_verbatim(self):
        args = render(STATES["ContractParser"]["Arguments"], self.vars, {})
        self.assertEqual(args["Messages"][0]["Content"][0]["Text"], OCR)
        self.assertEqual(len(args["RuntimeSessionId"]), 36)
        result = {"Output": {"Message": {"Role": "assistant", "Content": [{"Text": "{}"}]}}, "StopReason": "end_turn"}
        self.assertEqual(render(STATES["ContractParser"]["Assign"], self.vars, {"result": result})["parserText"], "{}")

    def _parse(self):
        payload = render(STATES["ParseExtraction"]["Arguments"]["Payload"], self.vars, {})
        self.assertEqual(set(payload), {"agentText", "sourceText"})
        return parse_extraction.handler(payload, None)

    def test_the_parse_payload_feeds_the_real_validator_and_its_verdict_routes_correctly(self):
        good = self._parse()
        self.assertTrue(good["ok"])
        body = STATES["ExtractionUsable"]["Choices"][0]["Condition"][2:-2]
        self.assertTrue(jsonata.Jsonata(body).evaluate(None, {"parsed": json.loads(json.dumps(good))}))

        self.vars["parserText"] = "Sorry, I could not read the document."
        bad = self._parse()
        self.assertFalse(bad["ok"])
        self.assertFalse(jsonata.Jsonata(body).evaluate(None, {"parsed": json.loads(json.dumps(bad))}))

    def test_save_payload_feeds_the_real_save_lambda_and_carries_the_validator_notes(self):
        self.vars["parserText"] = json.dumps(good_output(effective_to="sometime soon"))
        parsed = json.loads(json.dumps(self._parse()))
        self.assertTrue(parsed["ok"])
        payload = render(STATES["SaveAndNotify"]["Arguments"]["Payload"], {**self.vars, "parsed": parsed}, {})
        result = save_and_notify.handler(payload, None)
        self.assertEqual(result["rowKeys"], ["ctr-1001#PAY-001#PLN-1001#PRD-001"])
        self.assertEqual(list(self.contracts.items)[0], result["rowKeys"][0])
        self.assertEqual(self.contracts.items[result["rowKeys"][0]]["effectiveFrom"], "2026-01-01")
        self.assertIn("Extraction notes", self.sns.published[0]["Message"])
        self.assertIn("effective_to", self.sns.published[0]["Message"])
        assigned = render(STATES["SaveAndNotify"]["Assign"], {}, {"result": {"Payload": json.loads(json.dumps(result))}})
        self.assertEqual(assigned["contractId"], "ctr-1001")

    def test_index_payload_writes_the_dedupe_marker_and_only_there(self):
        payload = render(STATES["IndexClauses"]["Arguments"]["Payload"], {**self.vars, "contractId": "ctr-1001"}, {})
        with mock.patch.object(index_contract_clauses.vector_store, "put_documents", side_effect=lambda docs: len(docs)):
            result = index_contract_clauses.handler(payload, None)
        self.assertGreater(result["indexed"], 0)
        self.assertEqual(list(self.tokens.items), ["dedupe#b#contracts/CTR-1001.pdf#abc123"])

    def test_the_dedupe_loop_closes_a_successful_run_makes_the_next_upload_a_no_op(self):
        """index_contract_clauses writes the marker; start_textract_job must honour exactly that key."""
        event = {"detail": {"bucket": {"name": "b"}, "object": {"key": "contracts/CTR-1001.pdf", "etag": "abc123"}},
                 "taskToken": "T"}
        start_textract_job.sfn, start_textract_job.textract = FakeSfn(), mock.Mock()
        start_textract_job.textract.start_document_text_detection.return_value = {"JobId": "J1"}
        start_textract_job.handler(event, mock.Mock(aws_request_id="r1"))
        self.assertEqual(start_textract_job.textract.start_document_text_detection.call_count, 1)  # first time: OCR runs
        self.assertNotIn("dedupe#b#contracts/CTR-1001.pdf#abc123", self.tokens.items)  # a failed run must not poison retries

        payload = render(STATES["IndexClauses"]["Arguments"]["Payload"], {**self.vars, "contractId": "ctr-1001"}, {})
        with mock.patch.object(index_contract_clauses.vector_store, "put_documents", side_effect=lambda docs: len(docs)):
            index_contract_clauses.handler(payload, None)

        result = start_textract_job.handler(event, mock.Mock(aws_request_id="r2"))
        self.assertEqual(result, {"skipped": True})
        self.assertEqual(start_textract_job.textract.start_document_text_detection.call_count, 1)  # no second OCR
        released = json.loads(start_textract_job.sfn.successes[0]["output"])
        self.assertIs(released["skipped"], True)
        assigned = render(STATES["StartTextractJob"]["Assign"], {}, {"result": released})
        self.assertIs(assigned["skipped"], True)  # ... and the workflow routes it to AlreadyProcessed


class DedupeByContent(unittest.TestCase):
    """The dedupe must tell file VERSIONS apart. S3 -> EventBridge sends the hash as lowercase "etag"; the first
    version of this code read "eTag", so every file shared one key and an edited re-upload was silently skipped."""

    def setUp(self):
        _, _, self.tokens = _wire()
        start_textract_job.sfn, start_textract_job.textract = FakeSfn(), mock.Mock()
        start_textract_job.textract.start_document_text_detection.return_value = {"JobId": "J1"}

    def _upload(self, object_fields):
        event = {"detail": {"bucket": {"name": "b"}, "object": {"key": "contract.pdf", **object_fields}}, "taskToken": "T"}
        return start_textract_job.handler(event, mock.Mock(aws_request_id="r"))

    def test_the_real_s3_event_shape_is_understood(self):
        real_event = {"key": "contract.pdf", "size": 14743, "etag": "cc8f88fef6294ad874e00696775b07a7", "sequencer": "006AAE872FDCB5E3E6"}
        self.assertEqual(self._upload({k: v for k, v in real_event.items() if k != "key"}), {"jobId": "J1"})
        stored = [i for i in self.tokens.items.values() if i.get("etag")]
        self.assertEqual(stored[0]["etag"], "cc8f88fef6294ad874e00696775b07a7", "the etag must reach the token record")

    def test_an_edited_file_with_the_same_name_is_processed_not_skipped(self):
        self.tokens.items["dedupe#b#contract.pdf#version-one"] = {"jobId": "dedupe#b#contract.pdf#version-one"}
        self.assertEqual(self._upload({"etag": "version-one"}), {"skipped": True})            # the same version: skipped
        self.assertEqual(self._upload({"etag": "version-two"}), {"jobId": "J1"})                # an edited version: processed
        self.assertEqual(start_textract_job.textract.start_document_text_detection.call_count, 1)

    def test_no_etag_means_no_dedupe_rather_than_one_shared_key(self):
        self.tokens.items["dedupe#b#contract.pdf#None"] = {"jobId": "dedupe#b#contract.pdf#None"}
        self.tokens.items["dedupe#b#contract.pdf#unknown-etag"] = {"jobId": "dedupe#b#contract.pdf#unknown-etag"}
        self.assertEqual(self._upload({}), {"jobId": "J1"})


@unittest.skipUnless(yaml, "pip install pyyaml to check template.yaml invariants")
class TemplateConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = load_template()
        cls.resources = cls.template["Resources"]

    def test_state_machine_gets_exactly_the_substitutions_the_definition_uses(self):
        self.assertEqual(set(self.resources["PdfSummarizerStateMachine"]["Properties"]["DefinitionSubstitutions"]), SUBSTITUTIONS)

    def test_the_parser_harness_is_capped_tool_less_and_memory_less(self):
        harness = self.resources["ContractParserHarness"]["Properties"]
        self.assertLessEqual(harness["MaxIterations"], 5)
        self.assertLessEqual(harness["TimeoutSeconds"], 900)
        self.assertIn("MaxTokens", harness)
        self.assertEqual(harness["Memory"], {"Disabled": {}})
        self.assertTrue(harness["AllowedTools"])
        self.assertNotIn("*", harness["AllowedTools"])
        self.assertNotIn("Tools", harness)

    def test_the_agents_prompt_asks_for_every_field_the_validator_reads(self):
        """If the schema in the prompt and the validator drift apart, extraction breaks quietly."""
        prompt = self.resources["ContractParserHarness"]["Properties"]["SystemPrompt"][0]["Text"]
        expected = (set(extraction_logic.TOP_STRING_KEYS) | set(extraction_logic.TOP_DATE_KEYS)
                    | set(extraction_logic.TERM_STRING_KEYS) | set(extraction_logic.TERM_FLAG_KEYS)
                    | {"implementation_grace_days", "coverage_terms", "expected_tier", "rebate_terms", "key_dates_and_amounts"})
        # a key only mentioned in the prose notes does not count: it must be a line of the JSON schema itself
        missing = sorted(k for k in expected if not re.search(rf'^\s*"{k}":', prompt, re.M))
        self.assertEqual(missing, [])
        self.assertIn("YYYY-MM-DD", prompt, "dates are compared as ISO text downstream")

    def test_the_pdf_state_machine_has_its_own_role_and_cannot_run_commands_on_the_harness(self):
        props = self.resources["PdfSummarizerStateMachine"]["Properties"]
        self.assertNotIn("Role", props, "no more hand-made sfn-execution-role")
        # unset means STANDARD. Setting it explicitly would make CloudFormation REPLACE the already-deployed machine,
        # which fails for a fixed name (found in a real changeset).
        self.assertNotIn("Type", props)
        statements = [s for p in props["Policies"] if "Statement" in p for s in p["Statement"]]
        harness = [s for s in statements if "bedrock-agentcore:InvokeHarness" in s["Action"]]
        self.assertEqual(len(harness), 1)
        self.assertEqual(harness[0]["Resource"], "ContractParserHarness.Arn")  # the parser harness only
        self.assertNotIn("bedrock-agentcore:InvokeAgentRuntimeCommand", json.dumps(props["Policies"]))

    def test_the_validator_function_has_no_aws_access_and_its_own_role(self):
        props = self.resources["ParseExtractionFunction"]["Properties"]
        self.assertNotIn("Role", props)
        self.assertNotIn("Policies", props)

    def test_the_harness_role_can_invoke_both_models_and_run_both_identities(self):
        role = json.dumps(self.resources["HarnessExecutionRole"])
        for needle in ("${HarnessModelId}", "${ContractParserModelId}", "harness_DeviationCaseAgent-", "harness_ContractParserAgent-"):
            self.assertIn(needle, role)

    def test_parameters_that_no_longer_exist_are_not_still_passed_by_samconfig(self):
        parameters = set(self.template["Parameters"])
        with open(os.path.join(ROOT, "samconfig.toml"), encoding="utf-8") as f:
            passed = set(re.findall(r'(\w+)=\\"', f.read()))
        self.assertEqual(sorted(passed - parameters), [], "sam deploy would fail on parameters the template does not declare")
        self.assertNotIn("SfnExecutionRoleArn", parameters)
        self.assertNotIn("BedrockModelId", parameters)


if __name__ == "__main__":
    unittest.main()
