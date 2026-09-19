"""
The deterministic validator between the agents and anything that is saved or
approved. Agents propose; this decides what is kept. No AWS calls - all logic
is in case_logic.assemble so it can be unit tested.

Also the fallback path: if an agent step failed or returned rubbish, the
result is built from the approved playbook templates and flagged for human
review, so a case is never left without actions because a model misbehaved.
"""
import case_logic


def handler(event, context):
    return case_logic.assemble(
        event["context"],
        analyst_text=event.get("analystText"),
        planner_results=event.get("plannerResults"),
        verifier_text=event.get("verifierText"),
        agent_failed=bool(event.get("agentFailed")),
    )
