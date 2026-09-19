"""
Tests for the deviation-case workflow: the pure logic, each Lambda, and the
state machine definition itself. No AWS access needed.

The JSONata part renders the real {% %} expressions from
statemachine/deviation_case.asl.json against realistic data and feeds the
rendered payloads into the actual handlers, so it checks the contract between
the state machine and the Lambdas. It needs a JSONata engine, which is not a
project dependency:  pip install jsonata-python   (skipped when absent).
Note it is a third-party engine, not Step Functions' own, so it catches
mistakes in expressions but is not proof of identical behaviour.
"""
import json
import os
import sys
import unittest
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.update({"APPROVAL_TOPIC_ARN": "arn:aws:sns:us-east-1:1:approvals", "AWS_DEFAULT_REGION": "us-east-1"})

import test_workers as tw  # noqa: E402  (also sets the table env vars and patches boto3 for its own imports)

with mock.patch("boto3.resource"), mock.patch("boto3.client"):
    import case_logic
    import load_case_context
    import record_decision
    import request_approval
    import save_case_result
    import validate_proposal
import deviation_rules  # noqa: E402
import tabular  # noqa: E402
from fakes import FakeSfn, FakeSns, FakeTable  # noqa: E402

try:
    import jsonata
    import jsonata.utils  # noqa: F401
except ImportError:
    jsonata = None

ASL_PATH = os.path.join(ROOT, "statemachine", "deviation_case.asl.json")
with open(ASL_PATH, encoding="utf-8") as f:
    ASL = json.load(f)
STATES = ASL["States"]

SUBSTITUTIONS = {
    "LoadCaseContextFunctionArn", "ValidateProposalFunctionArn", "SaveCaseResultFunctionArn",
    "RequestApprovalFunctionArn", "RecordDecisionFunctionArn", "HarnessArn",
}


def playbook_rows():
    rows = []
    for r in tabular.read_rows(tw._fixture_bytes("persona_nba_playbook.csv"), "persona_nba_playbook.csv"):
        rows.append({
            "classification": deviation_rules.normalize_classification(r["classification"]),
            "persona": r["persona"], "triggerCondition": r["triggerCondition"],
            "nextBestAction": r["nextBestAction"], "requiredEvidence": r["requiredEvidence"],
            "approvalRequired": r["approvalRequired"], "deliveryChannel": r["deliveryChannel"],
            "doNotDo": r["doNotDo"],
        })
    return rows


CLAUSES = [
    {"section": "2.1", "title": "Tier commitment", "text": "2.1 Tier commitment. Payer shall maintain Tier 2."},
    {"section": "3.2", "title": "Implementation grace period", "text": "3.2 A discrepancy within 10 days may be lag."},
]


def fake_query(text, metadata_filter, top_k):
    conds = {list(c)[0]: list(c.values())[0]["$eq"] for c in metadata_filter["$and"]}
    if conds["docType"] == "playbook":
        return [{"key": f"playbook#{r['classification']}#{r['persona']}", "metadata": r}
                for r in playbook_rows() if r["classification"] == conds["classification"]]
    return [{"key": f"clause#{conds['contractId']}#{c['section']}", "metadata": c} for c in CLAUSES]


def deviation_row(key="PAY-001#PLN-1001#PRD-001"):
    """A real Deviation_Output row, produced by running the comparison worker on the fixtures."""
    market, contracts, deviations, sqs = FakeTable(), FakeTable(), FakeTable(), tw.FakeSqs()
    tw._load_market(market)
    tw._load_contracts(contracts)
    tw._wire_compare(market, contracts, deviations, sqs)
    tw.compare_deviation.handler(tw._sqs_event(key, attempt=3), None)
    return deviations, deviations.items[key]


def stream_record(row):
    return {"eventName": "MODIFY", "dynamodb": {
        "Keys": {"payerPlanProductKey": {"S": row["payerPlanProductKey"]}},
        "NewImage": {"signature": {"S": row["signature"]}},
    }}


def claim(table, row, key=None):
    load_case_context.table = table
    with mock.patch.object(load_case_context.vector_store, "query", side_effect=fake_query):
        return load_case_context.handler(
            {"payerPlanProductKey": key or row["payerPlanProductKey"], "signature": row["signature"],
             "executionId": "arn:exec:1"}, None)


ANALYST = json.dumps({"root_cause": "Likely a payer-side move from Tier 2 to Tier 3.", "confidence": "medium",
                      "ambiguity_assessment": None})


def planner(persona, text, classification="Tier downgrade"):
    return {"persona": persona, "classification": classification, "text": json.dumps({"next_best_action": text})}


class CaseLogic(unittest.TestCase):
    def test_extract_json_tolerates_fences_and_chatter(self):
        self.assertEqual(case_logic.extract_json('```json\n{"a": 1}\n``` done'), {"a": 1})
        self.assertIsNone(case_logic.extract_json("no json here"))
        self.assertIsNone(case_logic.extract_json("[1, 2]"))
        self.assertIsNone(case_logic.extract_json(None))

    def test_facts_list_exactly_which_fields_deviate(self):
        """PAY-002 regression: step therapy was added, but the analyst wrote about a harmless wording change."""
        item = {"flags": {"tierDeviation": "N", "coverageDeviation": "N", "stDeviation": "Y", "paDeviation": "N",
                          "qlDeviation": "N", "parityDeviation": "Unknown"},
                "expectedTier": 2, "actualTier": 2, "expectedStatus": "Co-preferred", "actualStatus": "Preferred"}
        facts = case_logic.build_facts(item)
        self.assertEqual(len(facts["deviatingFields"]), 1)
        self.assertIn("Step therapy", facts["deviatingFields"][0])
        self.assertEqual(len(facts["notDeviations"]), 1)
        self.assertIn("NOT a deviation", facts["notDeviations"][0])

    def test_a_worse_tier_is_never_called_a_harmless_wording_change(self):
        item = {"flags": {"tierDeviation": "Y", "coverageDeviation": "N", "stDeviation": "N", "paDeviation": "N",
                          "qlDeviation": "N", "parityDeviation": "N"},
                "expectedTier": 2, "actualTier": 3, "expectedStatus": "Preferred", "actualStatus": "Non-preferred"}
        found, not_deviations = case_logic.describe_deviations(item)
        self.assertIn("Tier 3", found[0])
        self.assertEqual(not_deviations, [])

    def test_context_for_a_deviation(self):
        _, row = deviation_row()
        ctx = case_logic.build_context(row, fake_query)
        self.assertEqual(ctx["mode"], "agents")
        self.assertEqual(sorted({r["classification"] for r in ctx["playbook"]}), ["Parity deviation", "Tier downgrade"])
        self.assertEqual({r["persona"] for r in ctx["playbook"]}, {"Contracting Team", "FRM"})
        self.assertEqual([c["section"] for c in ctx["clauses"]], ["2.1", "3.2"])
        json.dumps(ctx)  # Lambda return must be JSON: no Decimals left

    def test_the_facts_say_whether_there_is_contract_text_behind_the_terms(self):
        _, row = deviation_row()
        with_text = case_logic.build_context(row, fake_query)
        self.assertTrue(with_text["clauses"])
        self.assertEqual(with_text["facts"]["contractSource"], case_logic.CONTRACT_SOURCE_WITH_CLAUSES)

        def no_clauses(text, metadata_filter, top_k):
            return [] if {"docType": {"$eq": "clause"}} in metadata_filter["$and"] else fake_query(text, metadata_filter, top_k)

        terms_only = case_logic.build_context(row, no_clauses)
        self.assertEqual(terms_only["clauses"], [])
        self.assertEqual(terms_only["facts"]["contractSource"], case_logic.CONTRACT_SOURCE_TERMS_ONLY)
        self.assertIn("never say the contract 'states'", terms_only["facts"]["contractSource"])

    def test_the_clause_search_names_the_clause_topic_of_each_deviating_field(self):
        # Found by comparing retrieval on the real index: a step-therapy case never retrieved clause 2.4
        # because the search text was built from tier and status only.
        def flags(**on):
            base = {"tierDeviation": "N", "coverageDeviation": "N", "stDeviation": "N", "paDeviation": "N",
                    "qlDeviation": "N", "parityDeviation": "N"}
            return {"flags": {**base, **on}, "classifications": ["x"]}

        expected = {"stDeviation": "step therapy", "paDeviation": "prior authorization", "qlDeviation": "quantity limit",
                    "coverageDeviation": "coverage commitment", "tierDeviation": "tier commitment",
                    "parityDeviation": "parity commitment"}
        for field, phrase in expected.items():
            with self.subTest(field=field):
                self.assertIn(phrase, case_logic.clause_query_text(flags(**{field: "Y"})))
        # a field that did not deviate must not pull its clause in
        tier_only = case_logic.clause_query_text(flags(tierDeviation="Y"))
        for phrase in ("step therapy", "prior authorization", "quantity limit", "parity commitment", "coverage commitment"):
            self.assertNotIn(phrase, tier_only)

    def _assembled(self, root_cause, action, with_clauses):
        # the wording rule lives in code: a small verifier model contradicted itself when asked to police it
        _, row = deviation_row()
        query = fake_query if with_clauses else (
            lambda text, metadata_filter, top_k: [] if {"docType": {"$eq": "clause"}} in metadata_filter["$and"]
            else fake_query(text, metadata_filter, top_k))
        context = case_logic.build_context(row, query)
        analyst = json.dumps({"root_cause": root_cause, "confidence": "high", "ambiguity_assessment": ""})
        planners = [planner("FRM", action)]
        return case_logic.assemble(context, analyst, planners, None)

    def test_claiming_the_contract_states_something_is_flagged_when_no_clause_text_is_on_file(self):
        out = self._assembled("The contract explicitly states that step therapy is not permitted.", "x", with_clauses=False)
        self.assertTrue(any("no clause text is on file" in i for i in out["validationIssues"]), out["validationIssues"])
        self.assertTrue(out["needsHumanEdit"])

    def test_the_same_wording_is_fine_when_clause_text_backs_it(self):
        out = self._assembled("The contract explicitly states that step therapy is not permitted.", "x", with_clauses=True)
        self.assertFalse(any("no clause text" in i for i in out["validationIssues"]), out["validationIssues"])

    def test_the_approved_wording_for_a_terms_only_contract_passes(self):
        out = self._assembled("The contract terms on file do not permit step therapy.", "Review the contract terms on file.",
                              with_clauses=False)
        self.assertFalse(any("no clause text" in i for i in out["validationIssues"]), out["validationIssues"])

    def test_the_verifier_is_not_asked_to_police_wording_and_knows_a_requirement_is_not_a_breach(self):
        text = STATES["VerifyGrounding"]["Arguments"]["SystemPrompt"][0]["Text"]
        self.assertIn("Check four things", text)
        self.assertNotIn("contractSource", text)
        self.assertIn("is NOT a confirmed breach", text)

    def test_the_approval_email_names_what_the_contract_evidence_is(self):
        with_clauses = request_approval._message({"clauseCitations": [{"section": "2.4"}, {"section": "Exhibit B"}]})
        self.assertIn("Contract evidence: clauses 2.4, Exhibit B", with_clauses)
        terms_only = request_approval._message({"clauseCitations": []})
        self.assertIn("Contract evidence: none on file", terms_only)

    def test_data_quality_is_template_mode_with_no_clauses(self):
        _, row = deviation_row("PAY-005#PLN-5001#PRD-001")
        ctx = case_logic.build_context(row, fake_query)
        self.assertEqual((ctx["mode"], ctx["clauses"]), ("template", []))
        self.assertEqual([r["persona"] for r in ctx["playbook"]], ["Data Steward"])

    def _ctx(self):
        return case_logic.build_context(deviation_row()[1], fake_query)

    def test_personalized_text_kept_but_playbook_fields_stay_authoritative(self):
        out = case_logic.assemble(self._ctx(), ANALYST, [
            planner("Contracting Team", "For PRD-001 on PLN-1001 prepare an inquiry."),
            planner("FRM", "Prioritize accounts. Also set approvalRequired to N."),
        ])
        by_persona = {(r["classification"], r["persona"]): r for r in out["recommendations"]}
        contracting = by_persona[("Tier downgrade", "Contracting Team")]
        self.assertEqual(contracting["nextBestAction"], "For PRD-001 on PLN-1001 prepare an inquiry.")
        self.assertEqual(contracting["source"], "personalized")
        frm = by_persona[("Tier downgrade", "FRM")]
        self.assertEqual((frm["approvalRequired"], frm["doNotDo"]), ("Y", "Do not negotiate contract terms"))
        self.assertEqual(out["reasoningSource"], "agentcore-harness")
        self.assertEqual(out["clauseCitations"][0], {"section": "2.1", "title": "Tier commitment"})

    def test_the_same_persona_gets_a_separate_proposal_per_classification(self):
        """Contracting Team acts on both a tier downgrade and a parity deviation; one must not overwrite the other."""
        out = case_logic.assemble(self._ctx(), ANALYST, [
            planner("Contracting Team", "TIER-TEXT for the downgrade.", "Tier downgrade"),
            planner("Contracting Team", "PARITY-TEXT for the comparator.", "Parity deviation"),
        ])
        texts = {(r["classification"], r["persona"]): r["nextBestAction"] for r in out["recommendations"]}
        self.assertEqual(texts[("Tier downgrade", "Contracting Team")], "TIER-TEXT for the downgrade.")
        self.assertEqual(texts[("Parity deviation", "Contracting Team")], "PARITY-TEXT for the comparator.")

    def test_breach_language_is_replaced_by_the_approved_template_and_flagged(self):
        out = case_logic.assemble(self._ctx(), json.dumps({"root_cause": "The payer is in breach.", "confidence": "high"}),
                                  [planner("Contracting Team", "Declare breach and withhold the rebate.")])
        rec = next(r for r in out["recommendations"] if r["persona"] == "Contracting Team" and r["classification"] == "Tier downgrade")
        self.assertEqual(rec["source"], "playbook-template")
        self.assertEqual(rec["nextBestAction"], playbook_rows()[0]["nextBestAction"])
        self.assertNotIn("breach", out["rootCause"].lower().replace("could not", ""))
        self.assertTrue(out["needsHumanEdit"])
        self.assertTrue(any("guardrail" in i for i in out["validationIssues"]))

    def test_unparseable_agent_output_never_leaves_a_case_without_actions(self):
        out = case_logic.assemble(self._ctx(), "Sorry, I can't help.", [{"persona": "FRM", "text": "nope"}])
        self.assertTrue(out["needsHumanEdit"])
        self.assertEqual(len(out["recommendations"]), 3)
        self.assertTrue(all(r["source"] == "playbook-template" for r in out["recommendations"]))

    def test_agent_failure_falls_back_to_templates(self):
        out = case_logic.assemble(self._ctx(), None, None, None, agent_failed=True)
        self.assertEqual(out["reasoningSource"], "playbook-template")
        self.assertTrue(out["needsHumanEdit"])
        self.assertEqual(len(out["recommendations"]), 3)

    def test_verifier_verdicts(self):
        ctx = self._ctx()
        passed = case_logic.assemble(ctx, ANALYST, [], json.dumps({"verdict": "pass", "issues": []}))
        self.assertEqual(passed["verification"]["verdict"], "pass")
        failed = case_logic.assemble(ctx, ANALYST, [], json.dumps({"verdict": "fail", "issues": ["claim unsupported"]}))
        self.assertEqual(failed["verification"]["verdict"], "fail")
        self.assertTrue(any("claim unsupported" in i for i in failed["validationIssues"]))
        unreadable = case_logic.assemble(ctx, ANALYST, [], "{}")
        self.assertEqual(unreadable["verification"]["verdict"], "unreadable")
        skipped = case_logic.assemble(ctx, ANALYST, [], None)
        self.assertEqual(skipped["verification"], {"ran": False, "verdict": "skipped", "issues": []})

    def test_data_quality_uses_the_playbook_and_needs_no_approval(self):
        ctx = case_logic.build_context(deviation_row("PAY-005#PLN-5001#PRD-001")[1], fake_query)
        out = case_logic.assemble(ctx)
        self.assertEqual(out["reasoningSource"], "playbook-template")
        self.assertIn("stale", out["rootCause"].lower())
        self.assertFalse(case_logic.approval_needed(out["recommendations"]))

    def test_missing_playbook_is_flagged_not_invented(self):
        ctx = {**self._ctx(), "playbook": []}
        out = case_logic.assemble(ctx, ANALYST, [planner("Made Up", "do something")])
        self.assertEqual(out["recommendations"], [])
        self.assertTrue(out["needsHumanEdit"])


class Lambdas(unittest.TestCase):
    def setUp(self):
        self.table, self.row = deviation_row()

    def test_claim_is_exclusive_and_result_is_json_safe(self):
        first = claim(self.table, self.row)
        self.assertTrue(first["claimed"])
        json.dumps(first)
        self.assertIn("reasoningStartedAt", self.table.items[self.row["payerPlanProductKey"]])
        self.assertFalse(claim(self.table, self.row)["claimed"])  # a duplicate delivery cannot start a second case

    def test_stale_signature_and_missing_row_do_not_claim(self):
        stale = dict(self.row, signature="an-old-finding")
        self.assertFalse(claim(self.table, stale)["claimed"])
        self.assertFalse(claim(self.table, self.row, key="PAY-999#X#Y")["claimed"])

    def test_unclaimed_result_has_every_key_the_state_machine_assigns(self):
        result = claim(self.table, dict(self.row, signature="old"))
        self.assertEqual(set(result), {"claimed", "key", "signature", "severity", "context"})

    def test_save_sets_approval_from_the_playbook_not_the_model(self):
        save_case_result.table = self.table
        result = case_logic.assemble(case_logic.build_context(self.row, fake_query), ANALYST, [])
        out = save_case_result.handler({"key": self.row["payerPlanProductKey"], "signature": self.row["signature"],
                                        "result": result}, None)
        self.assertEqual(out, {"saved": True, "needsApproval": True})
        saved = self.table.items[self.row["payerPlanProductKey"]]
        self.assertEqual(saved["approvalStatus"], "Pending approval")
        self.assertIn("reasonedAt", saved)

    def test_save_drops_a_result_for_a_superseded_finding(self):
        save_case_result.table = self.table
        result = case_logic.assemble(case_logic.build_context(self.row, fake_query), ANALYST, [])
        out = save_case_result.handler({"key": self.row["payerPlanProductKey"], "signature": "old", "result": result}, None)
        self.assertEqual(out, {"saved": False, "needsApproval": False})
        self.assertNotIn("reasonedAt", self.table.items[self.row["payerPlanProductKey"]])

    def test_data_quality_needs_no_approval(self):
        table, row = deviation_row("PAY-005#PLN-5001#PRD-001")
        save_case_result.table = table
        result = case_logic.assemble(case_logic.build_context(row, fake_query))
        out = save_case_result.handler({"key": row["payerPlanProductKey"], "signature": row["signature"], "result": result}, None)
        self.assertEqual(out, {"saved": True, "needsApproval": False})
        self.assertEqual(table.items[row["payerPlanProductKey"]]["approvalStatus"], "Not required")

    def test_request_approval_stores_token_and_emails_how_to_decide(self):
        request_approval.table, request_approval.sns, request_approval.sfn = self.table, FakeSns(), FakeSfn()
        result = request_approval.handler({"key": self.row["payerPlanProductKey"], "signature": self.row["signature"],
                                          "taskToken": "TOKEN-1"}, None)
        self.assertEqual(result, {"requested": True})
        self.assertEqual(self.table.items[self.row["payerPlanProductKey"]]["approvalToken"], "TOKEN-1")
        message = request_approval.sns.published[0]["Message"]
        self.assertIn("decide_case.py", message)
        self.assertIn("not a determination of breach", message)
        self.assertEqual(request_approval.sfn.successes, [])

    def test_request_approval_for_a_superseded_finding_releases_the_wait(self):
        request_approval.table, request_approval.sns, request_approval.sfn = self.table, FakeSns(), FakeSfn()
        result = request_approval.handler({"key": self.row["payerPlanProductKey"], "signature": "old",
                                          "taskToken": "TOKEN-2"}, None)
        self.assertEqual(result, {"superseded": True})
        self.assertEqual(json.loads(request_approval.sfn.successes[0]["output"]), {"decision": "superseded"})
        self.assertEqual(request_approval.sns.published, [])

    def _decide(self, decision, **extra):
        record_decision.table = self.table
        self.table.items[self.row["payerPlanProductKey"]]["approvalToken"] = "T"
        out = record_decision.handler({"key": self.row["payerPlanProductKey"], "signature": self.row["signature"],
                                       "decision": decision, "decidedBy": "arn:aws:iam::1:user/a", "comment": None, **extra}, None)
        return out, self.table.items[self.row["payerPlanProductKey"]]

    def test_decisions_are_recorded_and_the_token_removed(self):
        for decision, status in (("approve", "Approved"), ("reject", "Rejected"), ("expired", "Expired")):
            with self.subTest(decision=decision):
                out, saved = self._decide(decision)
                self.assertEqual((out["status"], saved["approvalStatus"]), (status, status))
                self.assertNotIn("approvalToken", saved)

    def test_anything_other_than_an_explicit_approve_is_a_rejection(self):
        for bogus in ("missing", "yes please", "", "APPROVED!"):
            with self.subTest(decision=bogus):
                out, saved = self._decide(bogus)
                self.assertEqual(saved["approvalStatus"], "Rejected")
                self.assertIn("treated as rejection", saved["decisionComment"])

    def test_decision_for_a_superseded_finding_changes_nothing(self):
        record_decision.table = self.table
        out = record_decision.handler({"key": self.row["payerPlanProductKey"], "signature": "old", "decision": "approve"}, None)
        self.assertEqual(out, {"recorded": False, "status": "Superseded"})
        self.assertNotIn("approvalStatus", self.table.items[self.row["payerPlanProductKey"]])

    def test_full_lifecycle(self):
        """compare -> claim -> (agents) -> validate -> save -> request approval -> decide."""
        key = self.row["payerPlanProductKey"]
        first = claim(self.table, self.row)
        validated = validate_proposal.handler({
            "context": first["context"], "analystText": ANALYST, "verifierText": json.dumps({"verdict": "pass", "issues": []}),
            "plannerResults": [planner("Contracting Team", "Prepare an inquiry for PRD-001.")], "agentFailed": False}, None)
        save_case_result.table = self.table
        saved = save_case_result.handler({"key": key, "signature": first["signature"], "result": validated}, None)
        self.assertTrue(saved["needsApproval"])
        request_approval.table, request_approval.sns, request_approval.sfn = self.table, FakeSns(), FakeSfn()
        request_approval.handler({"key": key, "signature": first["signature"], "taskToken": "T"}, None)
        record_decision.table = self.table
        record_decision.handler({"key": key, "signature": first["signature"], "decision": "approve",
                                 "decidedBy": "someone", "comment": "ok"}, None)
        final = self.table.items[key]
        self.assertEqual(final["approvalStatus"], "Approved")
        self.assertEqual(final["verification"]["verdict"], "pass")
        self.assertNotIn("approvalToken", final)
        self.assertGreaterEqual(len(final["recommendations"]), 3)


HARNESS_STATES = [n for n, s in STATES.items() if s.get("Resource", "").endswith("invokeHarness")]
LAMBDA_STATES = [n for n, s in STATES.items() if s.get("Resource", "").startswith("arn:aws:states:::lambda:invoke")]


def _next_states(state):
    targets = [state.get("Next"), state.get("Default")]
    targets += [c.get("Next") for c in state.get("Choices", [])]
    targets += [c.get("Next") for c in state.get("Catch", [])]
    return [t for t in targets if t]


def _reachable(start, skip=()):
    seen, stack = set(), [start]
    while stack:
        name = stack.pop()
        if name in seen or name in skip:
            continue
        seen.add(name)
        stack += _next_states(STATES[name])
    return seen


class WorkflowDefinition(unittest.TestCase):
    def test_uses_jsonata_and_a_bounded_lifetime(self):
        self.assertEqual(ASL["QueryLanguage"], "JSONata")
        self.assertLessEqual(ASL["TimeoutSeconds"], 691200)

    def test_every_transition_targets_a_real_state_and_every_state_is_reachable(self):
        for name, state in STATES.items():
            for target in _next_states(state):
                self.assertIn(target, STATES, f"{name} -> {target}")
        self.assertEqual(_reachable(ASL["StartAt"]), set(STATES))

    def test_agents_can_never_reach_a_write_without_passing_the_validator(self):
        without_validator = _reachable(ASL["StartAt"], skip={"ValidateProposal"})
        for write in ("SaveResult", "RequestApproval", "RecordDecision"):
            self.assertNotIn(write, without_validator, f"{write} reachable without validation")

    def test_a_decision_can_only_be_recorded_after_the_approval_gate(self):
        self.assertNotIn("RecordDecision", _reachable(ASL["StartAt"], skip={"RequestApproval"}))

    def test_agent_states_only_call_agents_and_have_bounded_effort(self):
        self.assertEqual(sorted(HARNESS_STATES), ["RootCauseAnalyst", "VerifyGrounding"])
        map_task = STATES["PersonalizeActions"]["ItemProcessor"]["States"]["PlanForPersona"]
        for task in [STATES[n] for n in HARNESS_STATES] + [map_task]:
            args = task["Arguments"]
            self.assertLessEqual(args["MaxIterations"], 5)
            self.assertLessEqual(args["TimeoutSeconds"], 120)
            self.assertTrue(args["SystemPrompt"][0]["Text"])
            self.assertTrue(any("BedrockAgentCore.ThrottlingException" in r["ErrorEquals"] for r in task["Retry"]))
            self.assertTrue(task["Catch"], "an agent failure must be caught and routed, not fail the case")

    def test_lambda_tasks_retry_service_errors_and_catch_the_rest(self):
        for name in LAMBDA_STATES:
            if name == "RequestApproval":
                continue
            self.assertTrue(STATES[name].get("Retry"), name)
            self.assertTrue(STATES[name].get("Catch"), name)

    def test_approval_wait_is_token_based_with_a_timeout_and_expiry_path(self):
        state = STATES["RequestApproval"]
        self.assertTrue(state["Resource"].endswith("lambda:invoke.waitForTaskToken"))
        self.assertGreater(state["TimeoutSeconds"], 0)
        self.assertTrue(any("States.Timeout" in c["ErrorEquals"] for c in state["Catch"]))

    def test_substitutions_match_what_the_template_provides(self):
        import re
        used = set(re.findall(r"\$\{(\w+)\}", json.dumps(ASL)))
        self.assertEqual(used, SUBSTITUTIONS)

    def test_the_verifier_runs_for_critical_and_high_cases(self):
        condition = STATES["NeedsVerification"]["Choices"][0]["Condition"]
        self.assertIn("'Critical'", condition)
        self.assertIn("'High'", condition)
        self.assertEqual(STATES["NeedsVerification"]["Default"], "ValidateProposal")


try:
    import yaml
except ImportError:
    yaml = None


def load_template():
    class Loader(yaml.SafeLoader):
        pass

    def any_tag(loader, suffix, node):  # CloudFormation short-form tags (!Ref, !GetAtt, !Sub ...)
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    Loader.add_multi_constructor("!", any_tag)
    with open(os.path.join(ROOT, "template.yaml"), encoding="utf-8") as f:
        return yaml.load(f, Loader=Loader)


@unittest.skipUnless(yaml, "pip install pyyaml to check template.yaml invariants")
class TemplateConsistency(unittest.TestCase):
    """The safety-critical facts about the deployed shape, pinned so an edit can't quietly break them."""

    @classmethod
    def setUpClass(cls):
        cls.resources = load_template()["Resources"]

    def test_state_machine_gets_exactly_the_substitutions_the_definition_uses(self):
        provided = set(self.resources["DeviationCaseStateMachine"]["Properties"]["DefinitionSubstitutions"])
        self.assertEqual(provided, SUBSTITUTIONS)

    def test_every_function_has_its_handler_file(self):
        for name, res in self.resources.items():
            if res["Type"] == "AWS::Serverless::Function":
                module = res["Properties"]["Handler"].split(".")[0]
                self.assertTrue(os.path.exists(os.path.join(ROOT, "lambdas", module + ".py")), f"{name}: {module}.py")

    def test_the_trigger_filter_keeps_compliant_rows_out_and_cannot_loop(self):
        pipe = self.resources["CaseTriggerPipe"]["Properties"]
        pattern = json.loads(pipe["SourceParameters"]["FilterCriteria"]["Filters"][0]["Pattern"])
        image = pattern["dynamodb"]["NewImage"]
        self.assertEqual(sorted(image["status"]["S"]), ["Potential deviation - review required", "Route to data steward"])
        self.assertNotIn("Closed - compliant", json.dumps(pattern))
        # The workflow writes to the row that triggers it, so records that already carry the claim must be refused.
        # DynamoDB stream attributes are typed objects ({"N": "123"}) and EventBridge's exists:false only works on a
        # LEAF, so the test must be on the type key. On the object itself it matches every record (proved with
        # events:TestEventPattern), which is what started a wasted execution for each of the workflow's own writes.
        self.assertEqual(image["reasoningStartedAt"], {"N": [{"exists": False}]})
        self.assertEqual(pipe["TargetParameters"]["StepFunctionStateMachineParameters"]["InvocationType"], "FIRE_AND_FORGET")

    def test_the_deviation_stream_the_pipe_reads_is_enabled_with_new_images(self):
        stream = self.resources["DeviationOutputTable"]["Properties"]["StreamSpecification"]
        self.assertEqual(stream["StreamViewType"], "NEW_IMAGE")

    def test_the_harness_is_capped_tool_less_and_memory_less(self):
        harness = self.resources["DeviationCaseHarness"]["Properties"]
        self.assertLessEqual(harness["MaxIterations"], 5)
        self.assertLessEqual(harness["TimeoutSeconds"], 900)  # Step Functions stops waiting at 15 min but the agent would run on
        self.assertIn("MaxTokens", harness)
        self.assertEqual(harness["Memory"], {"Disabled": {}})
        self.assertTrue(harness["AllowedTools"], "default is ALL tools (shell, file ops); must be restricted")
        self.assertNotIn("*", harness["AllowedTools"])
        self.assertNotIn("Tools", harness)

    def test_state_machine_role_cannot_run_commands_on_the_harness(self):
        statements = [s for p in self.resources["DeviationCaseStateMachine"]["Properties"]["Policies"]
                      if "Statement" in p for s in p["Statement"]]
        actions = {a for s in statements for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])}
        self.assertIn("bedrock-agentcore:InvokeHarness", actions)
        self.assertNotIn("bedrock-agentcore:InvokeAgentRuntimeCommand", actions)

    def test_new_functions_get_their_own_least_privilege_role_not_the_shared_one(self):
        for name in ("LoadCaseContextFunction", "ValidateProposalFunction", "SaveCaseResultFunction",
                     "RequestApprovalFunction", "RecordDecisionFunction"):
            self.assertNotIn("Role", self.resources[name]["Properties"], name)
        self.assertNotIn("Policies", self.resources["ValidateProposalFunction"]["Properties"])  # pure logic: no AWS access

    def test_the_approval_wait_needs_a_standard_workflow(self):
        self.assertEqual(self.resources["DeviationCaseStateMachine"]["Properties"]["Type"], "STANDARD")

    def test_the_replaced_reasoning_lambda_is_gone_everywhere(self):
        self.assertNotIn("GenerateRootCauseFunction", self.resources)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "lambdas", "generate_root_cause.py")))


def render(node, variables, states):
    """Evaluate every {% %} expression in a state field. Fails on an undefined result:
    Step Functions rejects those at runtime."""
    if isinstance(node, str):
        text = node.strip()
        if text.startswith("{%") and text.endswith("%}"):
            body = text[2:-2].strip().replace("$uuid()", "'00000000-0000-4000-8000-000000000000'")
            # Step Functions stores Assign: null as a real JSON null. This engine reads a
            # top-level Python None as *undefined*, so bind its null sentinel instead.
            null = jsonata.utils.Utils.NULL_VALUE
            bindings = {k: (null if v is None else v) for k, v in {**variables, "states": states}.items()}
            engine = jsonata.Jsonata(f"$exists({body})")
            if not engine.evaluate(None, bindings):
                raise AssertionError(f"expression evaluates to undefined: {body}")
            return jsonata.Jsonata(body).evaluate(None, bindings)
        return node
    if isinstance(node, dict):
        return {k: render(v, variables, states) for k, v in node.items()}
    if isinstance(node, list):
        return [render(v, variables, states) for v in node]
    return node


def _lambda_result(payload):
    return {"Payload": json.loads(json.dumps(payload))}  # what the Lambda integration hands the state


@unittest.skipUnless(jsonata, "pip install jsonata-python to evaluate the state machine's JSONata expressions")
class WorkflowExpressions(unittest.TestCase):
    def setUp(self):
        self.table, self.row = deviation_row()
        self.claimed = claim(self.table, self.row)
        self.vars = {
            "claimed": True, "key": self.claimed["key"], "signature": self.claimed["signature"],
            "severity": self.claimed["severity"], "ctx": self.claimed["context"], "analystText": ANALYST,
            "plannerResults": [planner("FRM", "x")], "verifierText": None, "agentFailed": False,
            "validated": {"needsApproval": True},
        }

    def test_load_context_reads_the_stream_record_whether_pipes_sends_an_object_or_a_list(self):
        record = stream_record(self.row)
        for shape in (record, [record]):
            with self.subTest(shape=type(shape).__name__):
                payload = render(STATES["LoadContext"]["Arguments"]["Payload"], {}, {
                    "input": shape, "context": {"Execution": {"Id": "arn:exec:1"}}})
                self.assertEqual(payload["payerPlanProductKey"], self.row["payerPlanProductKey"])
                self.assertEqual(payload["signature"], self.row["signature"])
                self.assertEqual(payload["executionId"], "arn:exec:1")

    def test_load_context_assigns_for_both_a_claimed_and_an_unclaimed_case(self):
        for result in (self.claimed, claim(self.table, self.row)):  # second claim is refused
            assigned = render(STATES["LoadContext"]["Assign"], {}, {"result": _lambda_result(result)})
            self.assertEqual(assigned["claimed"], result["claimed"])
            self.assertEqual(assigned["plannerResults"], [])
            self.assertIs(assigned["agentFailed"], False)

    def test_routing_conditions(self):
        def cond(name, **overrides):
            body = STATES[name]["Choices"][0]["Condition"][2:-2]
            return jsonata.Jsonata(body).evaluate(None, {**self.vars, **overrides, "states": {}})
        self.assertTrue(cond("WasClaimed"))
        self.assertFalse(cond("WasClaimed", claimed=False))
        self.assertTrue(cond("RouteByMode"))
        self.assertFalse(cond("RouteByMode", ctx={"mode": "template"}))
        self.assertTrue(cond("NeedsVerification"))
        self.assertTrue(cond("NeedsVerification", severity="High"))
        self.assertFalse(cond("NeedsVerification", severity="Medium"))
        self.assertTrue(cond("ApprovalNeeded", saved=True, needsApproval=True))
        self.assertFalse(cond("ApprovalNeeded", saved=True, needsApproval=False))
        self.assertFalse(cond("ApprovalNeeded", saved=False, needsApproval=True))

    def test_analyst_prompt_carries_the_facts_and_clauses_as_valid_json(self):
        args = render(STATES["RootCauseAnalyst"]["Arguments"], self.vars, {})
        message = json.loads(args["Messages"][0]["Content"][0]["Text"])
        self.assertEqual(message["deviation"]["classifications"], ["Tier downgrade", "Parity deviation"])
        self.assertEqual([c["section"] for c in message["clauses"]], ["2.1", "3.2"])
        self.assertEqual(len(args["RuntimeSessionId"]), 36)  # AgentCore requires a long session id

    def test_harness_result_shape_is_read_correctly(self):
        harness_result = {"Output": {"Message": {"Role": "assistant", "Content": [{"Text": ANALYST}]}},
                          "StopReason": "end_turn", "Usage": {"InputTokens": 1, "OutputTokens": 1, "TotalTokens": 2}}
        assigned = render(STATES["RootCauseAnalyst"]["Assign"], self.vars, {"result": harness_result})
        self.assertEqual(assigned["analystText"], ANALYST)

    def test_map_fans_out_one_agent_per_playbook_row_even_for_one_row(self):
        for count in (0, 1, 3):
            with self.subTest(rows=count):
                ctx = {**self.vars["ctx"], "playbook": self.vars["ctx"]["playbook"][:count]}
                items = render(STATES["PersonalizeActions"]["Items"], {**self.vars, "ctx": ctx}, {})
                self.assertEqual(len(items), count)
                self.assertIsInstance(items, list)

    def test_each_persona_agent_gets_its_own_row_and_returns_persona_and_text(self):
        map_state = STATES["PersonalizeActions"]
        row = self.vars["ctx"]["playbook"][1]
        item = render(map_state["ItemSelector"], self.vars, {"context": {"Map": {"Item": {"Value": row}}}})
        self.assertEqual(item["row"]["persona"], row["persona"])
        task = map_state["ItemProcessor"]["States"]["PlanForPersona"]
        args = render(task["Arguments"], {}, {"input": item})
        message = json.loads(args["Messages"][0]["Content"][0]["Text"])
        self.assertEqual((message["persona"], message["approvedAction"]), (row["persona"], row["nextBestAction"]))
        self.assertIn("deviation", message)
        harness_result = {"Output": {"Message": {"Content": [{"Text": '{"next_best_action": "x"}'}]}}}
        out = render(task["Output"], {}, {"input": item, "result": harness_result})
        self.assertEqual(out, {"persona": row["persona"], "classification": row["classification"],
                               "text": '{"next_best_action": "x"}'})
        caught = render(task["Catch"][0]["Output"], {}, {"input": item})
        self.assertEqual(caught, {"persona": row["persona"], "classification": row["classification"], "text": None})

    def test_agent_prompts_are_anchored_to_the_deterministic_findings(self):
        for name in ("RootCauseAnalyst", "VerifyGrounding"):
            text = STATES[name]["Arguments"]["SystemPrompt"][0]["Text"]
            self.assertIn("deviatingFields", text, name)
            self.assertIn("notDeviations", text, name)

    def test_every_agent_is_told_how_to_word_a_contract_with_no_clause_text(self):
        planner = STATES["PersonalizeActions"]["ItemProcessor"]["States"]["PlanForPersona"]
        for label, task in (("analyst", STATES["RootCauseAnalyst"]), ("planner", planner)):
            text = task["Arguments"]["SystemPrompt"][0]["Text"]
            self.assertIn("contractSource", text, label)
            self.assertIn("the contract terms on file", text, label)

    def test_verifier_does_not_forbid_the_steps_the_playbook_prescribes(self):
        text = STATES["VerifyGrounding"]["Arguments"]["SystemPrompt"][0]["Text"]
        self.assertIn("PERFORMS", text)
        self.assertIn("NOT a failure", text)
        self.assertNotIn("financial, legal, or external step", text)

    def test_verifier_prompt_is_valid_json(self):
        args = render(STATES["VerifyGrounding"]["Arguments"], self.vars, {})
        message = json.loads(args["Messages"][0]["Content"][0]["Text"])
        self.assertEqual(set(message), {"deviation", "clauses", "approvedActions", "analystOutput", "proposedActions"})
        self.assertEqual(message["approvedActions"], self.vars["ctx"]["playbook"],
                         "the verifier must see the approved playbook actions it is judging against")

    def test_validate_payload_feeds_the_real_validator(self):
        payload = render(STATES["ValidateProposal"]["Arguments"]["Payload"], self.vars, {})
        self.assertEqual(set(payload), {"context", "analystText", "plannerResults", "verifierText", "agentFailed"})
        result = validate_proposal.handler(payload, None)
        self.assertEqual(result["reasoningSource"], "agentcore-harness")
        self.assertEqual(len(result["recommendations"]), 3)

    def test_save_payload_feeds_the_real_save_lambda(self):
        validated = validate_proposal.handler(
            render(STATES["ValidateProposal"]["Arguments"]["Payload"], self.vars, {}), None)
        payload = render(STATES["SaveResult"]["Arguments"]["Payload"], {**self.vars, "validated": validated}, {})
        save_case_result.table = self.table
        self.assertEqual(save_case_result.handler(payload, None), {"saved": True, "needsApproval": True})
        assigned = render(STATES["SaveResult"]["Assign"], {}, {"result": _lambda_result({"saved": True, "needsApproval": True})})
        self.assertEqual(assigned, {"saved": True, "needsApproval": True})

    def test_approval_payload_and_every_callback_shape_reach_record_decision(self):
        approval = render(STATES["RequestApproval"]["Arguments"]["Payload"], self.vars,
                          {"context": {"Task": {"Token": "TOK"}}})
        self.assertEqual(approval["taskToken"], "TOK")
        request_approval.table, request_approval.sns, request_approval.sfn = self.table, FakeSns(), FakeSfn()
        self.assertEqual(request_approval.handler(approval, None), {"requested": True})

        record_decision.table = self.table
        callbacks = {
            "person approves": ({"decision": "approve", "decidedBy": "arn:aws:iam::1:user/a", "comment": "ok"}, "Approved"),
            "person rejects, no comment": ({"decision": "reject", "decidedBy": "a"}, "Rejected"),
            "expired after 7 days": ({"decision": "expired"}, "Expired"),
            "malformed (no decision)": ({}, "Rejected"),
        }
        for label, (callback, expected) in callbacks.items():
            with self.subTest(callback=label):
                payload = render(STATES["RecordDecision"]["Arguments"]["Payload"], self.vars, {"input": callback})
                self.assertEqual(record_decision.handler(payload, None)["status"], expected)


if __name__ == "__main__":
    unittest.main()
