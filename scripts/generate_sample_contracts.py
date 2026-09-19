"""
Generates synthetic payer formulary agreements (PDF) in the same structure as
sample_data/Synthetic_Payer_Formulary_Access_Agreement.pdf (CTR-1001):
numbered clauses in sections 1-5, then Exhibits A-D.

One PDF per contract in CONTRACTS below. The terms match the market-data file
(MMIT_data1.xlsx) so the same expected outcomes hold when the contracts come
from PDFs instead of a CSV:

    CTR-1002 / PAY-002  Co-preferred, ST not permitted        -> ST added: Restriction escalation
    CTR-1003 / PAY-003  Tier 3 covered, no comparator         -> compliant
    CTR-1004 / PAY-004  Preferred, no UM, comparator PRD-003  -> covered becomes not covered: Coverage loss

Everything is fictional. Run:  python scripts/generate_sample_contracts.py
Requires reportlab (a development-only dependency, not used by the Lambdas).
"""
import os

CONTRACTS = [
    {
        "contract_id": "CTR-1002", "payer_id": "PAY-002", "plan_id": "PLN-2001",
        "payer": "Meridian Health Plan", "plan_name": "Meridian Commercial Select",
        "segment": "Meridian Commercial Select, pharmacy benefit",
        "tier": 2, "status": "Co-preferred",
        "pa": True, "st": False, "ql": None,
        "comparator_id": "PRD-002", "comparator": "BrandBeta (Molecule Beta)", "comparator_short": "BrandBeta",
        "term_start": ("January 1, 2026"), "term_end": ("December 31, 2026"),
        "grace_days": 10,
    },
    {
        "contract_id": "CTR-1003", "payer_id": "PAY-003", "plan_id": "PLN-3001",
        "payer": "Lakeside Health Partners", "plan_name": "Lakeside Value Formulary",
        "segment": "Lakeside Value Formulary, pharmacy benefit",
        "tier": 3, "status": "Covered",
        "pa": True, "st": True, "ql": "2 packages / 28 days",
        "comparator_id": None, "comparator": None, "comparator_short": None,
        "term_start": "January 1, 2026", "term_end": "December 31, 2026",
        "grace_days": 10,
    },
    {
        "contract_id": "CTR-1004", "payer_id": "PAY-004", "plan_id": "PLN-4001",
        "payer": "Summit Care Network", "plan_name": "Summit Advantage Commercial",
        "segment": "Summit Advantage Commercial, pharmacy benefit",
        "tier": 2, "status": "Preferred",
        "pa": False, "st": False, "ql": None,
        "comparator_id": "PRD-003", "comparator": "BrandGamma (Molecule Gamma)", "comparator_short": "BrandGamma",
        "term_start": "April 1, 2026", "term_end": "March 31, 2027",
        "grace_days": 10,
    },
]

BANNER = "SYNTHETIC DEMONSTRATION AGREEMENT - NOT LEGAL ADVICE - NOT FOR COMMERCIAL USE"
MANUFACTURER = "Demo Pharma, Inc."
PRODUCT_ID, PRODUCT = "PRD-001", "BrandAlpha (Molecule Alpha)"


def _ordinal_tier(c):
    return f"Tier {c['tier']} {c['status']}"


def _um_sentence(c):
    parts = [
        "PA is permitted using the criteria described in Exhibit C." if c["pa"] else "PA is not permitted.",
        "ST is permitted." if c["st"] else "ST is not permitted.",
        (f"QL is permitted up to {c['ql'].replace(' / ', ' per ')}." if c["ql"] else "QL is not permitted."),
    ]
    return " ".join(parts) + " Any additional or more restrictive requirement is a potential restriction escalation."


def _tier_definition(c):
    if c["status"] == "Co-preferred":
        return (f'"Co-preferred Tier" means Tier {c["tier"]}, shared with the Comparator Product, under the Payer tier '
                f"taxonomy shown in Exhibit B. If the Payer publishes another label, the operational crosswalk in "
                f"Exhibit B governs for monitoring purposes.")
    if c["status"] == "Covered":
        return (f'"Covered Tier" means Tier {c["tier"]}, a covered but non-preferred placement, under the Payer tier '
                f"taxonomy shown in Exhibit B. If the Payer publishes another label, the operational crosswalk in "
                f"Exhibit B governs for monitoring purposes.")
    return (f'"Preferred Tier" means Tier {c["tier"]} under the Payer tier taxonomy shown in Exhibit B. If the Payer '
            f"publishes another label, the operational crosswalk in Exhibit B governs for monitoring purposes.")


def _trigger_tier(c):
    if c["tier"] == 2:
        return "Tier 3, Tier 4, non-preferred or worse"
    return f"Tier {c['tier'] + 1}, non-formulary or worse"


def _exhibit_d_rows(c):
    rows = [
        ("Observed condition", "Classification", "Primary routing"),
        (f"Expected Tier {c['tier']}; actual Tier {c['tier'] + 1}", "Tier downgrade", "Contracting + Account Director"),
    ]
    if c["comparator_id"]:
        rows.append((f"Brand worse than {c['comparator_short']} in the same plan", "Potential parity deviation",
                     "Contracting + Market Access Strategy"))
    if not c["st"]:
        rows.append(("ST added where prohibited", "Restriction escalation", "Contracting + FRM + Patient Services"))
    rows.append(("Covered becomes not covered", "Coverage loss", "Contracting + Account Director + FRM"))
    rows.append(("Source stale or mapping ambiguous", "Data-quality exception", "Data Steward"))
    return rows


def build(c, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=20, leading=24)
    h1 = ParagraphStyle("h1", parent=ss["Heading2"], spaceBefore=10, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading3"], spaceBefore=6, spaceAfter=2)
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=13, spaceAfter=5)

    def clause(story, number, heading, text):
        story.append(Paragraph(f"{number} {heading}", h2))
        story.append(Paragraph(text, body))

    def table(rows, widths, header=True):
        t = Table(rows, colWidths=widths)
        style = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("FONTSIZE", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 5)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3864")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(style))
        return t

    def wrap(rows):  # cells as Paragraphs so long text wraps
        return [[Paragraph(str(cell), body) for cell in row] for row in rows]

    has_cmp = bool(c["comparator_id"])
    term = f"{c['term_start']} through {c['term_end']}"
    story = []

    # ---- cover
    story += [Spacer(1, 0.6 * inch), Paragraph("Synthetic Payer Formulary Access Agreement", title),
              Paragraph(f"Between {MANUFACTURER} and {c['payer']}", ss["Heading3"]), Spacer(1, 0.2 * inch)]
    cover = [("Agreement ID", c["contract_id"]), ("Product", PRODUCT),
             ("Comparator", c["comparator"] if has_cmp else "None"), ("Term", term),
             ("Covered segment", c["segment"])]
    story.append(table(wrap(cover), [1.6 * inch, 4.9 * inch], header=False))
    story += [Spacer(1, 0.2 * inch), Paragraph(
        "<b>Purpose of this artifact.</b> This fictional agreement is designed to test contract-clause extraction, "
        "expected-state creation, formulary deviation detection, evidence assembly, and persona-specific next-best-action "
        "generation. All parties, products, plans, identifiers, financial terms, and events are synthetic.", body),
        Paragraph("PoC artifact prepared for Formulary Deviation Agent demonstration", body), PageBreak()]

    # ---- 1. parties
    story.append(Paragraph("1. Parties, scope and definitions", h1))
    clause(story, "1.1", "Parties",
           f'This Formulary Access Agreement (the "Agreement") is entered into by and between {MANUFACTURER} '
           f'("Manufacturer") and {c["payer"]} ("Payer"). The Agreement applies only to the plan and benefit segment listed in Exhibit A.')
    clause(story, "1.2", "Contracted Product",
           '"Contracted Product" means BrandAlpha, including the package identifiers listed in Exhibit A. Product mappings '
           'outside Exhibit A are not automatically in scope.')
    if has_cmp:
        clause(story, "1.3", "Comparator Product",
               f'"Comparator Product" means {c["comparator_short"]} for Condition X. Comparator status is evaluated within '
               f'the same plan, benefit type, indication, and formulary effective period.')
    else:
        clause(story, "1.3", "Comparator Product",
               "No Comparator Product is designated under this Agreement. No parity commitment applies.")
    clause(story, "1.4", "Contracted Tier", _tier_definition(c))
    clause(story, "1.5", "Utilization Management",
           '"Utilization Management" or "UM" includes prior authorization (PA), step therapy (ST), quantity limits (QL), '
           'indication restrictions, and other access edits.')
    clause(story, "1.6", "Data discrepancy vs. confirmed breach",
           "An observed difference between the contractual expected state and a formulary data source is a potential "
           "deviation. It becomes a confirmed contractual breach only after plan applicability, dates, exclusions, source "
           "quality, implementation periods, and written evidence have been reviewed by authorized personnel.")

    # ---- 2. commitments
    story.append(Paragraph("2. Formulary access commitments", h1))
    clause(story, "2.1", "Tier commitment",
           f"During the Term, Payer shall maintain the Contracted Product on {_ordinal_tier(c)} for the Covered Segment, "
           f"subject to the exclusions and transition provisions in this Agreement.")
    if has_cmp:
        clause(story, "2.2", "Parity commitment",
               f"The Contracted Product shall be placed no less favorably than the Comparator Product with respect to formulary "
               f"status, coverage status, PA, ST, and QL, within the Covered Segment. A difference is not a parity deviation "
               f"if it results from a documented indication, benefit, product-form, or plan-design distinction permitted by this Agreement.")
    else:
        clause(story, "2.2", "Parity commitment",
               "This Agreement contains no parity commitment. Placement of other products is not evaluated against the Contracted Product.")
    clause(story, "2.3", "Coverage commitment",
           "The Contracted Product shall remain covered for the Covered Segment. A status of not covered, excluded, "
           "non-formulary, or equivalent shall constitute a potential coverage deviation unless an approved exception applies.")
    clause(story, "2.4", "Utilization-management commitment", _um_sentence(c))

    # ---- 3. change management
    story.append(Paragraph("3. Formulary change management", h1))
    clause(story, "3.1", "Advance notification",
           "Payer shall provide written notice of a material change affecting tier, coverage, PA, ST, QL, or comparator "
           "positioning at least 30 calendar days before the planned effective date, except where a shorter period is "
           "required by law or an urgent safety action.")
    clause(story, "3.2", "Implementation grace period",
           f"A discrepancy observed within {c['grace_days']} calendar days after an approved formulary update may be classified "
           f"as administrative lag while the Payer completes system propagation, provided written confirmation and a "
           f"corrective date are supplied.")
    clause(story, "3.3", "Evidence hierarchy",
           "For investigation, the parties may consider: (a) the executed Agreement and amendments; (b) Payer-issued "
           "formulary and policy documents; (c) structured formulary datasets; (d) archived snapshots; and (e) written Payer "
           "confirmation. Conflicting evidence must be reconciled before enforcement action.")
    clause(story, "3.4", "Data quality safeguards",
           "An automated alert shall be suppressed or routed to data stewardship when a source is stale, a plan mapping is "
           "incomplete, the product mapping is ambiguous, or an effective date cannot be established.")

    # ---- 4. remedies
    story.append(Paragraph("4. Review, cure and remedies", h1))
    clause(story, "4.1", "Notice of potential deviation",
           "Manufacturer may submit an evidence package identifying the affected plan, product, expected state, observed "
           "state, source, effective date, and applicable clause. Submission does not by itself constitute a legal determination.")
    clause(story, "4.2", "Payer review",
           "Payer shall acknowledge the inquiry within five business days and provide a substantive response within ten "
           "business days, unless the parties agree otherwise in writing.")
    clause(story, "4.3", "Cure",
           "If the parties confirm a deviation, Payer shall restore the compliant status within 15 calendar days or provide "
           "an agreed remediation plan. The cure date shall be captured in the deviation case record.")
    clause(story, "4.4", "Illustrative financial reconciliation",
           "For PoC purposes only, a confirmed uncured Critical deviation lasting more than 30 calendar days may trigger a "
           "synthetic rebate reconciliation flag. No automatic withholding, offset, or legal remedy shall be executed by the agent.")

    # ---- 5. governance
    story.append(Paragraph("5. Governance and human oversight", h1))
    clause(story, "5.1", "Authorized decision makers",
           "Contracting personnel determine contractual applicability and enforcement. Field roles may receive approved "
           "access guidance and account-prioritization recommendations but shall not characterize an alert as a confirmed breach.")
    clause(story, "5.2", "Permitted automated actions",
           "The agent may extract clauses, create an expected-state record, compare expected and observed access, rank "
           "potential deviations, assemble evidence, draft an inquiry, and recommend next actions. Human approval is "
           "required before external payer communication or financial action.")
    clause(story, "5.3", "Audit trail",
           "The agent shall retain an audit trail for each deviation case, including the clause relied upon, the expected "
           "and observed states, the evidence sources and retrieval dates, the classification and routing decision, any "
           "human approval, and the final disposition. Audit records shall be retained for the duration of the Term and any "
           "agreed reconciliation period.")
    story.append(PageBreak())

    # ---- Exhibit A
    story.append(Paragraph("Exhibit A - Contract scope and product identifiers", h1))
    a_rows = [("Field", "Contract value"), ("Payer ID", c["payer_id"]), ("Plan ID", c["plan_id"]),
              ("Plan name", c["plan_name"]), ("Line of business", "Commercial"), ("Benefit type", "Pharmacy"),
              ("Product ID", PRODUCT_ID), ("Illustrative NDC11", "00011111101"),
              ("Comparator product ID", c["comparator_id"] or "None"), ("Indication", "Condition X")]
    story.append(table(wrap(a_rows), [2.2 * inch, 4.3 * inch]))

    # ---- Exhibit B
    story.append(Paragraph("Exhibit B - Expected state and tier crosswalk", h1))
    b_rows = [("Attribute", "Expected state", "Deviation trigger"),
              ("Tier", _ordinal_tier(c), _trigger_tier(c)),
              ("Coverage", "Covered", "Not covered, excluded or non-formulary"),
              ("PA", "Permitted per Exhibit C" if c["pa"] else "Not permitted",
               "Criteria materially more restrictive than Exhibit C" if c["pa"] else "Any PA requirement"),
              ("ST", "Permitted" if c["st"] else "Not permitted", "Criteria more restrictive than agreed" if c["st"] else "Any ST requirement"),
              ("QL", c["ql"] or "Not permitted", "Lower limit or shorter refill allowance" if c["ql"] else "Any QL requirement"),
              ("Parity", f"No less favorable than {c['comparator_id']}" if has_cmp else "Not applicable",
               "Comparator has better tier, coverage or UM" if has_cmp else "Not applicable")]
    story.append(table(wrap(b_rows), [1.2 * inch, 2.4 * inch, 2.9 * inch]))
    story.append(PageBreak())

    # ---- Exhibit C
    story.append(Paragraph("Exhibit C - Approved PA criteria (synthetic)", h1))
    if c["pa"]:
        story.append(Paragraph(
            "PA may confirm: (1) diagnosis of Condition X; (2) prescribing by or consultation with an appropriate specialist; "
            "and (3) use according to the approved label. This exhibit is fictional and is not clinical guidance.", body))
    else:
        story.append(Paragraph("No PA criteria are approved because PA is not permitted under this Agreement. "
                               "This exhibit is fictional and is not clinical guidance.", body))

    # ---- Exhibit D
    story.append(Paragraph("Exhibit D - Deviation classification and routing", h1))
    story.append(table(wrap(_exhibit_d_rows(c)), [2.6 * inch, 1.7 * inch, 2.2 * inch]))
    story += [Spacer(1, 0.2 * inch), Paragraph("Illustrative signatures", h2)]
    for party in (MANUFACTURER, c["payer"]):
        story.append(Paragraph(f"<b>{party}</b><br/>Name: ____________________________<br/>"
                               f"Title: _____________________________<br/>Date: _____________________________", body))
    story.append(Paragraph(
        "Legal and data disclaimer: This is a synthetic training and demonstration artifact. It is not an MMIT export, not a "
        "payer-issued agreement, not legal advice, and not intended to represent actual coverage, clinical policy, or commercial terms.", body))

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(0.75 * inch, 10.6 * inch, BANNER)
        canvas.drawString(0.75 * inch, 10.45 * inch, f"Page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(path, pagesize=letter, topMargin=0.95 * inch, bottomMargin=0.7 * inch,
                      leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                      title=f"Synthetic Payer Formulary Access Agreement {c['contract_id']}",
                      author="Synthetic demo").build(story, onFirstPage=page, onLaterPages=page)


def output_name(c):
    return f"Synthetic_Payer_Formulary_Access_Agreement_{c['contract_id']}.pdf"


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sample_data")
    for c in CONTRACTS:
        path = os.path.normpath(os.path.join(out, output_name(c)))
        build(c, path)
        print("wrote", path)


if __name__ == "__main__":
    main()
