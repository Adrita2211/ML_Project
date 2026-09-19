"""
Deterministic validator between the Contract Parser agent and the database.
The agent proposes; this decides what is saved. All logic is in
extraction_logic.parse so it can be unit tested; this Lambda has no AWS access.
"""
import extraction_logic


def handler(event, context):
    return extraction_logic.parse(event["agentText"], event["sourceText"])
