"""
Mock live incident feed — simulates a status-page/incident-management API
(e.g. Statuspage, PagerDuty) that CRAG's Tier 2 check queries in real time.
"""

from datetime import datetime, timedelta

_NOW = datetime.utcnow()

ACTIVE_INCIDENTS = [
    {
        "component": "sso",
        "keywords": ["sso", "single sign-on", "saml", "oidc", "identity provider", "okta", "azure ad", "auth gateway"],
        "status": "investigating",
        "message": (
            "The central auth gateway (auth.example.com) is experiencing elevated "
            "latency and intermittent timeouts, causing SSO logins to fail or take "
            "over 60 seconds for some users. Non-SSO email/password login is unaffected."
        ),
        "started_at": (_NOW - timedelta(hours=1, minutes=45)).isoformat() + "Z",
        "eta": "Engineering is deploying a fix; ETA ~30 minutes.",
    },
]


def check_incident(topic: str) -> dict | None:
    """Look up whether there's an active incident related to the given topic/query.

    Simulates a real-time API call to a status page. Returns the matching
    incident dict, or None if the component is currently healthy.
    """
    topic_lower = topic.lower()
    for incident in ACTIVE_INCIDENTS:
        if any(kw in topic_lower for kw in incident["keywords"]):
            return incident
    return None
