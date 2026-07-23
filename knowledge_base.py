"""Mock product knowledge base documents for the CRAG demo."""

DOCUMENTS = [
    {
        "title": "Password Reset",
        "content": """
Password Reset Guide

To reset your password:
1. Go to the login page and click "Forgot password"
2. Enter the email associated with your account
3. Check your inbox for a reset link (valid for 30 minutes)
4. Click the link and choose a new password (min 8 characters, one number, one symbol)
5. You will be logged out of all other active sessions automatically

If you don't receive the email within 5 minutes, check your spam folder or
request a new link. Password resets work for both email/password accounts
and SSO-linked accounts (SSO users are redirected to their identity provider).
""",
    },
    {
        "title": "Two-Factor Authentication (2FA) Setup",
        "content": """
Setting Up Two-Factor Authentication

2FA adds an extra layer of security to your account using an authenticator app.

Steps:
1. Go to Account Settings > Security > Two-Factor Authentication
2. Scan the QR code with an authenticator app (Google Authenticator, Authy, etc.)
3. Enter the 6-digit code shown in the app to confirm setup
4. Save your backup codes in a secure location

If you lose access to your authenticator app, use a backup code to log in,
then generate new backup codes immediately. Support cannot manually
disable 2FA without identity verification for security reasons.
""",
    },
    {
        "title": "Billing and Subscription Plans",
        "content": """
Billing and Subscription Plans

We offer three plans: Free, Pro ($12/user/month), and Enterprise (custom pricing).

Changing plans:
- Upgrades take effect immediately with prorated billing
- Downgrades take effect at the end of the current billing cycle
- Annual billing gets a 20% discount vs monthly

Payment methods: credit card, ACH (Enterprise only), and invoicing (Enterprise only).
Failed payments trigger 3 retry attempts over 7 days before the account is
downgraded to Free. Refunds are issued for annual plans within 14 days of purchase.
""",
    },
    {
        "title": "API Rate Limits",
        "content": """
API Rate Limits

Default rate limits by plan:
- Free: 60 requests/minute, 5,000 requests/day
- Pro: 300 requests/minute, 100,000 requests/day
- Enterprise: custom limits, contact your account manager

Rate limit responses return HTTP 429 with a Retry-After header. Limits are
applied per API key, not per account. Burst traffic up to 2x the limit is
allowed for short windows (under 10 seconds) before throttling kicks in.
""",
    },
    {
        "title": "Single Sign-On (SSO) Login",
        "content": """
Single Sign-On (SSO) Login

SSO is available on the Enterprise plan via SAML 2.0 and OIDC.

Setup:
1. Admin goes to Settings > SSO and selects the identity provider (Okta, Azure AD, Google Workspace)
2. Uploads the IdP metadata XML or enters the OIDC client ID/secret
3. Maps user attributes (email, name, role) between the IdP and our platform
4. Enables "Require SSO" to enforce it for all users in the workspace

Note: as of the last product update, SSO login now always redirects through
the central auth gateway at auth.example.com before reaching the identity
provider, and typically completes in under 2 seconds.
""",
    },
    {
        "title": "Data Export",
        "content": """
Data Export

Users can export their data at any time from Settings > Data > Export.

Available formats: CSV, JSON. Exports are generated asynchronously and
emailed as a download link valid for 72 hours. Enterprise customers can
request scheduled automated exports via the Admin API.

Large exports (>1GB) may take up to 30 minutes to generate. Exported data
includes all account records but excludes deleted items older than 90 days.
""",
    },
]

# Ground-truth Q&A pairs for pipeline evaluation (evaluate.py).
# expected_route indicates which CRAG tier should have produced the answer:
#   "docs"          -> Tier 1 docs, no active incident
#   "docs+incident" -> Tier 1 docs, but an active incident should be surfaced first
#   "web"           -> Tier 3 (Tavily) fallback, docs don't cover it well
EVAL_PAIRS = [
    {
        "question": "How do I reset my password?",
        "ground_truth": (
            "Click 'Forgot password' on the login page, enter your account email, "
            "then use the reset link (valid 30 minutes) sent to your inbox to set a "
            "new password of at least 8 characters with one number and one symbol."
        ),
        "expected_route": "docs",
    },
    {
        "question": "What are the default API rate limits on the Pro plan?",
        "ground_truth": (
            "The Pro plan allows 300 requests per minute and 100,000 requests per day, "
            "applied per API key."
        ),
        "expected_route": "docs",
    },
    {
        # The internal SSO doc's "typically completes in under 2 seconds" claim gets
        # flagged by the grader as possibly-outdated (verdict: ambiguous), so per the
        # correct->refine / ambiguous-or-incorrect->web_fallback routing rule this
        # correctly falls through to Tier 3 (web+incident), not straight docs+incident.
        "question": "How does SSO login work and how long does it take?",
        "ground_truth": (
            "SSO establishes a trust relationship between the service and an identity "
            "provider (SAML/OIDC) to authenticate users. However, there is currently an "
            "active incident: the central auth gateway is experiencing elevated latency, "
            "causing SSO logins to fail or take over 60 seconds for some users, with a fix "
            "ETA of about 30 minutes. Non-SSO email/password login is unaffected."
        ),
        "expected_route": "web+incident",
    },
    {
        # A plausible follow-on support question about a topic the docs DO cover
        # (Data Export), but the specific issue (encoding/garbled characters) isn't
        # addressed in knowledge_base.py. It's still a well-known, widely-documented
        # generic issue on the real web (not company-specific), so Tavily's results
        # are genuinely relevant — unlike asking about "this" fictional product's
        # policies, which wouldn't exist on the live web at all. See README.
        "question": "My exported CSV file shows garbled/broken special characters when I open it in Excel — why does that happen?",
        "ground_truth": (
            "This is typically a character-encoding mismatch: the CSV is encoded in "
            "UTF-8 but Excel opens it assuming a different (often ANSI/Windows-1252) "
            "encoding, corrupting non-ASCII characters. Common fixes are saving/exporting "
            "the CSV with a UTF-8 byte-order-mark (BOM), or importing it via Excel's "
            "Text Import Wizard and explicitly selecting UTF-8 encoding."
        ),
        "expected_route": "web",
    },
]
