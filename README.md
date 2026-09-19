# Payer Formulary Deviation Agent

A serverless AWS pipeline that watches for drift between what a payer
formulary access agreement **promises** and what the payer's formulary data
**actually shows**, classifies each deviation, routes it, and drafts
persona-specific next actions that a human approves.

It runs as two Step Functions workflows, and both use **Bedrock AgentCore agents
orchestrated by Step Functions**: one turns a contract PDF into structured terms,
the other handles each deviation. Both follow the pattern AWS describes for that
pairing: agents *propose*, deterministic code *validates*, a person *approves*,
and no agent step writes to any system.

All data in `sample_data/` is synthetic. Nothing here is legal advice, and by
design nothing here decides that a breach occurred or contacts a payer.

---

## 1. Start here: what it does, in plain language

**The problem.** A manufacturer signs a contract that says "this drug stays on
Tier 2, no step therapy." Months later the payer's real formulary may have
quietly changed, and nobody notices until it costs money.

**The two things compared**

| | Source | Form | Becomes |
|---|---|---|---|
| Expected state | Signed contract | PDF (unstructured) | `Contract_Expectations` rows |
| Actual state | Market data (MMIT-style) | CSV / Excel (structured) | `Market_Snapshots` rows |

**The flow, in the order things happen**

1. A contract PDF is uploaded to S3. **Textract** turns it into text. A **contract
   parser agent** reads that text and proposes the terms (tier, PA/ST/QL rules,
   comparator, dates, grace period). **Deterministic code validates the proposal**:
   an id that isn't in the document is discarded, dates are converted to ISO,
   types are normalized, and an unusable extraction fails visibly instead of being
   saved. The validated terms become one row per product, and the contract's
   clauses go into a **vector index** so a later step can quote them.
2. A market-data file is uploaded. A plain Lambda parses it into a second table
   (no AI: the data is already structured).
3. **Plain rules** compare the two: tier, coverage, PA, ST, QL, and parity with
   the comparator drug. The result is classified (Tier downgrade, Coverage loss,
   Restriction escalation, Parity deviation) and routed per the contract's
   Exhibit D. Stale or unmappable data goes to a data steward instead of being
   reported as a deviation.
4. **Each real deviation starts a case workflow.** A Lambda gathers the facts,
   the contract's clauses and the approved playbook actions. Then AI agents work
   on it: one explains the likely root cause, one per persona adapts that
   persona's approved action to this case, and for Critical cases a separate
   verifier agent double-checks the proposal.
5. **Deterministic code validates what the agents proposed.** It rejects breach
   language or financial/legal steps, and takes "who acts", "approval required"
   and the "do not" guardrail from the playbook, never from the agents.
6. **A person approves or rejects.** The workflow pauses (at no cost) until someone
   decides. Approving records the decision; nothing is sent to anyone.

**Why part of it is code and part is AI**

- Comparing `expected tier 2` with `actual tier 3` has one right answer, so it is
  code: repeatable, auditable, free.
- Reading contract language, explaining *why* something changed, and wording an
  action for a specific case need judgement, so those are the agents, and the
  case agents only run for rows that need them.
- Everything an agent could get wrong in a way that matters is checked by code or
  copied from the playbook, and a human signs off before anything happens.

**Glossary**

| Term | Meaning here |
|---|---|
| S3 / Lambda / DynamoDB / SQS / SNS | File storage / small functions / database / queue / notifications |
| Textract | OCR: PDF to text, no understanding |
| Bedrock | AWS's AI service (a chat model, and Titan for embeddings) |
| **AgentCore harness** | A managed agent: you declare a model, prompt and tools; AWS runs the agent loop in an isolated session |
| **Step Functions** | Runs a workflow as a graph of states with retries, error routing and waits |
| **`InvokeHarness` state** | A Step Functions state that calls a harness directly, with no Lambda glue in between |
| **EventBridge Pipes** | Connects a source (a DynamoDB stream) to a target (a workflow), with filtering, and no code |
| **Task token / `waitForTaskToken`** | The workflow pauses until something calls back with the token: how the OCR callback and the human approval work |
| **JSONata** | The expression language Step Functions uses to reshape data between states (`{% ... %}`) |
| S3 Vectors | Vector database inside S3: stores embeddings, answers "find similar" |
| Embedding | Numbers representing a text's meaning, so similar texts can be found |
| SAM | `template.yaml` describes all resources; `sam deploy` creates them |

---

## 2. Architecture

```
 WORKFLOW 1  pdf-summarizer          contract PDF -> validated structured terms
 ---------------------------------------------------------------------------------------------------------
 S3 *.pdf -> EventBridge -> Step Functions
   StartTextractJob     Lambda   starts OCR, waits for the SNS callback (task token); dedupes an unchanged file
        |
   SkipCheck --already succeeded--> AlreadyProcessed        (no OCR, no agent, no spend)
        |
   ContractParser       AGENT    InvokeHarness   PROPOSES the terms as JSON; writes nothing
        |                        \--fails--> ExtractionFailed
   ParseExtraction      Lambda   deterministic validator: ids grounded in the text, ISO dates, types
        |
   ExtractionUsable? --no--> ExtractionFailed               (loud failure; nothing saved; re-upload retries)
        |
   SaveAndNotify        Lambda   one contract row per product; emails a summary incl. the validator's notes
        |
   IndexClauses         Lambda   clauses -> vector index; writes the dedupe marker (only on full success)

 S3 market-data/*.csv|xlsx -> ingest_market_snapshot -> Market_Snapshots table
 S3 playbook/*.csv|xlsx    -> ingest_playbook ---------> S3 Vectors index  (docType = playbook; clauses = clause)

 COMPARISON            both tables -stream-> forward_stream_to_queue -> SQS (+DLQ) -> compare_deviation
 ---------------------------------------------------------------------------------------------------------
   compare_deviation runs deviation_rules.py (pure code) -> Deviation_Output table

 WORKFLOW 2  deviation-case-workflow   one execution per distinct deviation
 ---------------------------------------------------------------------------------------------------------
 Deviation_Output stream
   -> EventBridge Pipe   filter: deviation or data-quality  AND  reasoningStartedAt absent   (no Lambda)
   -> Step Functions
        LoadContext          Lambda   claim the case (idempotent) + retrieve clauses & playbook rows
             |                        deterministic; the agents never choose what to retrieve
        WasClaimed? --no--> AlreadyHandled
             |
        RouteByMode --data quality--> ValidateProposal  (playbook template only: no agent, no cost)
             |
        RootCauseAnalyst     AGENT 1  InvokeHarness   likely cause + the ambiguities the rules couldn't settle
             |
        PersonalizeActions   AGENT 2  Map, one InvokeHarness per playbook row, in parallel
             |
        NeedsVerification?   Critical only
             |
        VerifyGrounding      AGENT 3  independent judge; flags the case, decides nothing
             |
        ValidateProposal     Lambda   deterministic validator: parse, guardrail, playbook fields, fallback
             |
        SaveResult           Lambda   conditional write (dropped if the finding changed meanwhile)
             |
        ApprovalNeeded? --no--> Done
             |
        RequestApproval      Lambda   .waitForTaskToken: stores token, emails approvers, then WAITS
             |                        <-- person runs scripts/decide_case.py  (a dashboard button later)
        RecordDecision       Lambda   records Approved / Rejected / Expired. Sends nothing.
```

In workflow 2, any agent that fails or returns unusable output is caught: the case
falls back to the approved playbook templates and is flagged `needsHumanEdit`, so
a case is never left without actions because a model misbehaved. Workflow 1 is
deliberately stricter: a contract that can't be read into usable terms fails
loudly, because saving a guess would corrupt every comparison that follows.

### Why it is shaped this way

- **Agents propose; code decides what is kept.** `ParseExtraction` and
  `ValidateProposal` sit between every agent and every write. Tests prove there is
  no path from an agent state to a save that skips them.
- **The human gate is a task token, not a poll.** The execution waits up to 7 days
  at no compute cost. A separate test proves a decision can only be recorded after
  that gate.
- **Idempotent claim.** Streams deliver at least once and the row is written
  several times. `LoadContext` claims a finding with a conditional write, so a
  duplicate can't start a second set of agents.
- **Loop-proof trigger.** The case workflow writes to the same row that triggers
  it. The pipe filter requires `reasoningStartedAt` to be absent, and the claim
  sets it, so those writes cannot start another execution. Pinned by a test.
- **Stream, then SQS, then worker** for comparison: the queue absorbs bursts and
  `ReservedConcurrentExecutions` caps parallelism; the DLQ stops poison messages.
- **Filter first, then rank.** Retrieval narrows by metadata the rules already
  know (`classification`, `contractId`), then orders by similarity.

---

## 3. How it decides

### Contract extraction (workflow 1)

The **contract parser** agent's prompt is the harness's default system prompt (one
place, in `template.yaml`). It returns a JSON proposal; `lambdas/extraction_logic.py`
(pure code, unit tested) decides what is safe to save, because everything
downstream joins on it:

| Check | Why |
|---|---|
| **Every id must appear in the document.** `contract_id`, `payer_id`, `plan_id`, `product_id`, `comparator_product_id` that aren't in the OCR text are discarded (punctuation and spacing ignored, since OCR splits `PAY-001`) | These are the join keys to market data. An invented id silently fails to match, or matches the wrong row |
| **Dates become ISO** (`January 1, 2026` to `2026-01-01`); unreadable ones are dropped | The comparison worker compares dates as text. The previous prompt never required ISO, so a `January 1, 2026` would have compared wrongly with no error |
| **Types normalized**: tier to an integer 1-9, PA/ST/QL/parity to `Y`/`N`, grace days to a bounded integer | Downstream logic assumes these shapes |
| **Unusable means failure**: no coverage terms, no identifiable payer, or output that isn't JSON fails the workflow (`ContractExtractionFailed`) | Previously a bad answer stored a placeholder row. Now nothing is saved and the dedupe marker isn't written, so re-uploading retries |

Anything the validator discarded is listed under "Extraction notes" in the summary
email, so a person can see what to check against the source.

### Deviation rules (comparison)

`lambdas/deviation_rules.py` is pure code (no AWS calls). It implements the sample
agreement:

| Contract source | Rule |
|---|---|
| Exhibit B, Tier | Deviation if actual tier is **worse** (higher number) than expected, or the contract expects Preferred/Co-preferred and the payer shows Non-preferred. A **better** tier is not a deviation. |
| Exhibit B, Coverage | Not covered / excluded / non-formulary is Coverage loss (which also counts as the tier deviation) |
| Exhibit B, ST | ST observed where the contract says not permitted |
| Exhibit B, PA / QL | PA or QL observed where the contract does not permit it |
| Exhibit B, Parity | Contract requires parity and the comparator has a better tier, coverage, or fewer restrictions |
| Sec 3.4 | Source older than `StaleSourceDays` (default 30), or a market row with no contract mapping, is a **Data-quality exception** routed to the Data Steward |
| Sec 3.2 | A discrepancy inside the grace period is **not suppressed**; it is recorded as an ambiguity for the analyst agent and a person to weigh (the contract says it "may be" lag, and only with written confirmation) |
| Outside contract term | Not evaluated |

Each flag is `Y`, `N`, or `Unknown`. `Unknown` never creates a deviation; it lowers
`evidenceConfidence` and is listed under `ambiguities`.

| Classification (Exhibit D) | Severity | Routing |
|---|---|---|
| Coverage loss | Critical | Contracting, Account Director, FRM |
| Tier downgrade | Critical | Contracting, Account Director |
| Restriction escalation | High if ST, else Medium | Contracting, FRM, Patient Services |
| Parity deviation | High | Contracting, Market Access Strategy |
| Data-quality exception | Data quality | Data Steward |

**Left to the agents, on purpose:** whether PA criteria are "materially more
restrictive than Exhibit C", whether a QL limit is lower than contracted (the
snapshot only has Y/N flags), and whether an in-grace-period discrepancy is
administrative lag.

**Test oracle.** `sample_data/MMIT_data1.xlsx` (sheet `Deviations`) is replayed
through the rules. All 5 rows match on tier, ST, coverage, severity and status.
One field differs, deliberately reported rather than forced: DEV-002 parity is
`Unknown` here versus `N` in the sheet, because the fixtures hold no snapshot for
that plan's comparator.

### What the case agents do, and what stays in code (workflow 2)

| Agent (an `InvokeHarness` state) | Sees | Returns | Runs |
|---|---|---|---|
| Root-cause analyst | deviation facts + retrieved clauses | root cause, confidence, ambiguity assessment | once per deviation |
| Persona planner | one approved playbook action + facts + the analyst's output | that action adapted to this case | once per playbook row, in parallel (Map) |
| Verifier | facts, clauses, analyst output, proposed actions | pass / fail + issues | Critical cases only |

| Decided by code or the playbook | Written by an agent |
|---|---|
| Which personas act (playbook rows matching the classification) | Root cause, worded with a confidence level |
| Approval required, delivery channel, required evidence, do-not-do | Each action's wording for this case (product, plan, tiers, dates) |
| Clause citations (top retrieved clauses for the contract) | Commentary on each ambiguity; the verifier's verdict |
| Whether a human must approve (any row marked approval-required) | |

Guardrails in `case_logic.assemble` (unit tested, never raises on bad output):
text asserting a breach or proposing withholding, offsetting, terminating, or a
legal remedy is replaced by the approved template and the case flagged
`needsHumanEdit`. Unparseable output falls back the same way. A verifier `fail`
or unreadable verdict flags the case; it does not block it, because a person
reviews every case that needs approval anyway.

Proposals are matched to playbook rows by **(classification, persona)**, not
persona alone: Contracting Team acts on both a tier downgrade and a parity
deviation, and one must not overwrite the other.

---

## 4. Data model

**Keys.** Everything joins on `payerPlanProductKey = payerId#planId#productId`
(for example `PAY-001#PLN-1001#PRD-001`). Market rows and contract rows must agree
on those three ids; the contract PDF's Exhibit A supplies them, which is why the
extraction validator insists each id actually appears in the document.

| Table | Partition key | Holds |
|---|---|---|
| `FormularyAgreementSummaries` (contracts) | `documentId` = `contractId#payerId#planId#productId`; GSI `PayerPlanProductIndex` on `payerPlanProductKey` | Expected state per product: tier, status, PA/ST/QL, comparator, parity, dates, `graceDays`, clause reference |
| `FormularyMarketSnapshots` | `payerPlanProductKey` | **Latest** snapshot per key (a row replaces the stored one only if its date is the same or newer) |
| `FormularyDeviations` | `payerPlanProductKey` | The case: flags, classification, severity, routing, confidence, ambiguities, then `rootCause`, `recommendations[]`, `clauseCitations`, `verification`, `needsHumanEdit`, `validationIssues`, `approvalStatus`, decision fields |
| `TextractJobTokens` | `jobId` | Textract job to Step Functions token; also `dedupe#...` markers |

**Case row lifecycle** (attributes on `FormularyDeviations`)

| Attribute | Set by | Meaning |
|---|---|---|
| `signature` | comparison worker | Hash of the finding. A changed finding replaces the row and starts a fresh case |
| `reasoningStartedAt`, `caseExecutionId` | `LoadContext` | The case is claimed; links to the execution |
| `reasonedAt`, `approvalStatus` | `SaveResult` | `Pending approval` or `Not required` (from the playbook's flags) |
| `approvalToken`, `approvalRequestedAt` | `RequestApproval` | The token that resumes the paused workflow |
| `approvalStatus`, `decidedAt`, `decidedBy`, `decisionComment` | `RecordDecision` | `Approved`, `Rejected` or `Expired`; token removed |

**Vector index** (`formulary-knowledge`, 1024-dim cosine, Titan Text Embeddings v2).

| `docType` | Key | Filterable metadata | Returned text (non-filterable) |
|---|---|---|---|
| `playbook` | `playbook#<classification>#<persona>` | classification, persona, approvalRequired, deliveryChannel | nextBestAction, requiredEvidence, doNotDo, triggerCondition |
| `clause` | `clause#<contractId>#<section>` | contractId, section | clause text, title |

### Dedupe and idempotency

- `start_textract_job` skips a file whose `(bucket, key, eTag)` already succeeded,
  and the workflow's `SkipCheck` sends it straight to the end. The marker is written
  by the **last** step (`index_contract_clauses`), only after everything worked, so
  a failed run is retried instead of skipped forever. A test runs the whole loop:
  first upload does OCR, the marker appears only after success, the second upload
  does no OCR.
- Re-uploading a contract or market file overwrites the same keys.
- A recomputed deviation with the same finding only refreshes its as-of date, keeps
  its reasoning, and does **not** start another case. A changed finding replaces the
  row and starts a fresh case. A workflow still running for the old finding drops
  its result (the save is conditional on the signature).
- Parity needs the comparator's snapshot, which may not be written yet. The message
  is re-queued with a delay (up to 3 times) rather than producing a provisional row.

---

## 5. Cost and effort controls

Each of these is enforced in configuration or code, not by hoping the agents behave:

| Control | Where | Effect |
|---|---|---|
| Unchanged contract re-upload does nothing | `SkipCheck` + dedupe marker | No OCR, no parser agent |
| Compliant rows never start a workflow | pipe filter | Case cost tracks real deviations, not data volume |
| Data-quality cases skip agents entirely | `RouteByMode` | The playbook row is the action |
| Claim before reasoning | `load_case_context` | Duplicate deliveries can't multiply agent runs |
| Same finding seen again does not re-run | `signature` | A persistent deviation isn't re-reasoned each month |
| Verifier only for Critical | `NeedsVerification` | Scrutiny where stakes are highest |
| Hard caps per agent call | `MaxIterations` 3, `TimeoutSeconds` 90-300, `MaxTokens` | A runaway agent is bounded |
| No tools, no memory | harness `AllowedTools`, `Memory: Disabled` | No ~900-token tool definitions per call, no managed-memory charges, no shell |
| Model per role | `ContractParserModelId` (Nova Pro), `HarnessModelId` (Nova Lite) | Spend the stronger model where a weak reading corrupts everything; the cheap one elsewhere |
| Bounded retries and lifetime | state machine `Retry`, pipe `MaximumRetryAttempts`, execution caps | No unbounded loops |

**What it costs to reason about one deviation:** `1` analyst call + `N` planner calls
(one per matching playbook row; 2 to 3 is typical) + `1` verifier call if Critical.
**One contract:** `1` parser call, only when the file changed. Each `InvokeHarness`
call starts its own isolated session that AgentCore Runtime bills for CPU and memory
per second, plus model tokens. The earlier design made one plain model call per
contract and per deviation, so this is more expensive; that is the price of
separate, individually bounded and auditable agents. If cost matters more than
separation, collapse the planners into the analyst's call, or swap the harness
states for a plain Bedrock `Converse` Lambda. Unmeasured: no dollar figure is
claimed here.

With no tools configured, a harness adds session overhead over a plain model call.
Its value grows once agents get tools (for example clause and snapshot lookup
through an AgentCore Gateway), which this version deliberately does not do:
retrieval stays deterministic so an agent can't be steered into fetching or
skipping something.

---

## 6. Project structure

```
payer_formulary_agent/
├── template.yaml                    SAM template: every resource below
├── samconfig.toml                   saved sam deploy parameters
├── lambdas/
│   ├── start_textract_job.py        workflow 1: start OCR, dedupe check
│   ├── resume_workflow.py           workflow 1: OCR done, resume
│   ├── parse_extraction.py          workflow 1: deterministic validator (no AWS access)
│   ├── save_and_notify.py           workflow 1: write rows, email summary + validator notes
│   ├── index_contract_clauses.py    workflow 1: clauses to vector index, dedupe marker
│   ├── ingest_market_snapshot.py    market path: CSV/XLSX to Market_Snapshots
│   ├── ingest_playbook.py           playbook path: CSV/XLSX to vector index
│   ├── forward_stream_to_queue.py   stream to SQS forwarder
│   ├── compare_deviation.py         SQS worker: runs the rules, writes Deviation_Output
│   ├── load_case_context.py         workflow 2: claim + deterministic retrieval
│   ├── validate_proposal.py         workflow 2: deterministic validator (no AWS access)
│   ├── save_case_result.py          workflow 2: conditional write, sets approval status
│   ├── request_approval.py          workflow 2: token wait, emails approvers
│   ├── record_decision.py           workflow 2: records the outcome, sends nothing
│   ├── extraction_logic.py          PURE: contract-extraction validation (unit tested)
│   ├── deviation_rules.py           PURE: comparison rules (unit tested)
│   ├── case_logic.py                PURE: retrieval context, guardrails, assembly (unit tested)
│   ├── clause_chunker.py            PURE: clause splitter (unit tested)
│   ├── contract_items.py            shared: contract-table items and keys
│   ├── tabular.py                   shared: CSV/XLSX reader, snake_case to camelCase
│   ├── vector_store.py              shared: Titan embeddings + S3 Vectors put/query
│   └── requirements.txt             boto3 (needs the s3vectors client) + openpyxl
├── statemachine/
│   ├── pdf_summarizer.asl.json      workflow 1 (JSONata, ContractParser InvokeHarness state)
│   └── deviation_case.asl.json      workflow 2 (JSONata, InvokeHarness states)
├── iam/                             policy JSON for the hand-made roles (section 8)
├── sample_data/
│   ├── Synthetic_Payer_Formulary_Access_Agreement.pdf            contract CTR-1001
│   ├── Synthetic_Payer_Formulary_Access_Agreement_CTR-100{2,3,4}.pdf   the other three contracts (generated)
│   ├── MMIT_data1.xlsx                                   golden Deviations sheet
│   ├── contract_expectations.csv    CTR-1001..1004 as a table: a shortcut for tests, NOT the normal path
│   ├── market_snapshots.csv         SNP-001..008        (transcribed from screenshots)
│   ├── Persona_NBA_Playbook.xlsx    7 playbook rows: the file the business edits and uploads
│   └── persona_nba_playbook.csv     the same rows as CSV (a test fails if the two drift apart)
├── scripts/
│   ├── generate_sample_contracts.py    regenerate the CTR-1002..1004 PDFs (needs reportlab)
│   ├── load_contract_expectations.py   demo shortcut: load CSV contracts, skipping the PDF pipeline
│   └── decide_case.py                  list / approve / reject cases waiting for a person
└── tests/                           161 local tests, no AWS needed (section 9)
```

The three CSVs were transcribed by hand from screenshots of the source workbook,
because `MMIT_data1.xlsx` itself contains only the `Deviations` sheet. Check them
against the originals before relying on them.

---

## 7. AWS resources

### Created manually (outside CloudFormation, before first deploy)

| Resource | Name |
|---|---|
| S3 bucket | `payer-formulary-uploads-313` (EventBridge notifications enabled) |
| DynamoDB | `FormularyAgreementSummaries` (PK `documentId`), `TextractJobTokens` (PK `jobId`) |
| SNS | `textract-job-complete`, `document-summary-ready` |
| IAM roles | `lambda-execution-role`, `textract-sns-publish-role`, `eventbridge-sfn-role` (policy JSON in `iam/`) |

`sfn-execution-role`, which older versions of this project used for the PDF state
machine, is **no longer used**: the stack now generates that role. If it exists in
your account you can delete it.

### Created by `sam deploy` (stack `formulary-agent-stack`)

| Resource | Count / name | Purpose |
|---|---|---|
| Lambda functions | 14 | 8 on the shared hand-made role, **6 with their own least-privilege roles** (`parse_extraction`, and the five case-workflow functions) |
| Step Functions | `pdf-summarizer`, `deviation-case-workflow` | Both `STANDARD` with X-Ray tracing and generated roles. Workflow 2 needs `STANDARD` for the approval wait |
| **AgentCore harnesses** | `ContractParserAgent`, `DeviationCaseAgent` | The parser has its fixed prompt as the harness default; the case harness's states each override the prompt with their role's |
| EventBridge Pipe | `deviation-case-trigger` | Deviation stream to workflow 2, filtered, no Lambda |
| IAM roles | harness execution role, pipe role | Created in the template |
| DynamoDB | `FormularyMarketSnapshots`, `FormularyDeviations` | Streams enabled |
| SQS | comparison queue + DLQ, `...-reasoning-dlq` | Buffering; the second is the pipe's failure capture |
| SNS | approval topic (+ email subscription if `ApprovalEmail` is set) | Approval requests |
| EventBridge rules | `.pdf` uploads, `market-data/`, `playbook/` | Start the ingestion paths |
| S3 Vectors | bucket `payer-formulary-vectors-313`, index `formulary-knowledge` | Knowledge base |

---

## 8. Deploying

### Prerequisites

- AWS CLI configured; **AWS SAM CLI** installed (`sam --version`); Python 3.11.
- Region `us-east-1`. **AgentCore harness** must be available in your region (GA
  in the regions AWS lists) along with S3 Vectors.
- Bedrock access to the **parser model** (`amazon.nova-pro-v1:0`), the **case-agent
  model** (`amazon.nova-lite-v1:0`) and `amazon.titan-embed-text-v2:0`.
- Optional but recommended: enable **CloudWatch Transaction Search** (one time per
  account). Without it the harness's turn-by-turn traces don't appear.
- The manual resources in section 7.
- Lambda concurrency headroom: the template reserves 5 concurrent executions for
  the comparison worker. On a new account with a low limit, the deploy can fail
  with an "unreserved concurrency" error; remove that setting or request a quota
  increase.

### Manual changes to existing resources (once)

`FormularyAgreementSummaries` and the hand-made IAM roles aren't managed by the
stack. These touch a live account; review first.

**1. Enable streams on the contract table** and note the `StreamArn` in the output:

```powershell
aws dynamodb update-table --table-name FormularyAgreementSummaries `
  --stream-specification StreamEnabled=true,StreamViewType=NEW_IMAGE
```

**2. Add the lookup index** (takes a few minutes to backfill):

```powershell
aws dynamodb update-table --table-name FormularyAgreementSummaries `
  --attribute-definitions AttributeName=payerPlanProductKey,AttributeType=S `
  --global-secondary-index-updates "[{\"Create\":{\"IndexName\":\"PayerPlanProductIndex\",\"KeySchema\":[{\"AttributeName\":\"payerPlanProductKey\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}}]"
```

**3. Apply the updated policy to `lambda-execution-role`**, which covers the
Textract/index/ingestion/comparison functions. It no longer needs a chat-model
permission (that call moved into the parser agent), only embeddings:

```powershell
aws iam put-role-policy --role-name lambda-execution-role --policy-name lambda-permissions `
  --policy-document file://iam/lambda-permissions-policy.json
```

Both workflows' other roles are created by the stack, so no further manual IAM.

### Build and deploy

```powershell
sam build
sam deploy --guided   # pass the StreamArn from step 1 as ContractExpectationsStreamArn;
                      # set ApprovalEmail to the address that should receive approval requests
```

`lambdas/requirements.txt` makes `sam build` bundle a recent `boto3` (the Lambda
runtime's built-in one may predate the `s3vectors` client) and `openpyxl`. If you
set `ApprovalEmail`, confirm the subscription email AWS sends. The saved
`samconfig.toml` no longer passes `SfnExecutionRoleArn` or `BedrockModelId`, which
the template no longer declares.

---

## 9. Testing

### Locally (no AWS)

```powershell
python -m unittest discover -s tests -v
```

**138 tests** (18 of them skip themselves when an optional package is missing; see
below):

| Area | What is covered |
|---|---|
| Rules | Every golden row; stale source, grace period, outside term, parity, signature stability |
| Extraction validator | Invented and OCR-split ids, ISO date conversion, type coercion, junk in the wrong shape, every rejection case, and that a good extraction's keys **join to the market-data fixtures** |
| Playbook ingestion | The Excel playbook and its CSV copy give identical vector documents; every classification in the playbook is one the rules can emit, and every one the rules can emit has an action (a misspelling is otherwise silent: the row is simply never retrieved); the filterable/non-filterable metadata split fits the index limits |
| Workers | Ingestion ordering, comparison wait/requeue/write/refresh, run against in-memory fakes |
| Case logic | Guardrails, fallbacks, per-(classification, persona) matching, verifier verdicts, data-quality path |
| Case Lambdas | Exclusive claim, stale-finding drops, approval status from playbook flags, fail-safe decisions (only an explicit `approve` approves), full lifecycle from comparison to decision |
| Both workflow definitions | Every transition valid; every state reachable; **no path from an agent to a write that skips the validator**; decisions only after the approval gate; agents capped, caught and retried; substitutions match the template |
| Dedupe loop | First upload does OCR; the marker appears only after full success; the second upload does no OCR |
| Template | Pipe filter excludes compliant rows and carries the loop guard; both harnesses capped, tool-less, memory-less; the parser's prompt asks for every field the validator reads; state machine roles cannot run commands on a harness; `samconfig.toml` passes no parameter the template lacks |

Optional packages for the extra tests (`pip install jsonata-python pyyaml pypdf`):
with them, the real `{% ... %}` expressions in both state machines are rendered
against realistic data, and the rendered payloads are fed into the actual Lambda
handlers, so the contract between each workflow and each Lambda is exercised. Step
Functions rejects an expression that evaluates to *undefined*; the tests enforce
that too. Note this is a third-party JSONata engine, not Step Functions' own.

The tests were themselves checked by deliberately breaking things (the loop guard,
Decimal conversion, per-persona matching, the pipe filter, tool restrictions, id
grounding, ISO dates, the dedupe marker, the validator bypass, a stale parameter)
and confirming a test fails each time. One such check found a weak assertion, which
was strengthened.

`cfn-lint` (`pip install cfn-lint`) also passes on `template.yaml` and rejects
deliberately broken copies of the harness, pipe and reference definitions.

**None of this proves the deployed system works.** It cannot exercise IAM, event
filters, the real harnesses, real model output, S3 Vectors, or Pipes.

### End to end on AWS

Contracts and the playbook must exist before market data, so comparisons have both
sides.

```powershell
# 1. Playbook -> vector index (Excel or CSV both work; edit the .xlsx and re-upload to update)
aws s3 cp sample_data/Persona_NBA_Playbook.xlsx s3://payer-formulary-uploads-313/playbook/

# 2. Contract CTR-1001 (PDF) -> OCR, parser agent, validate, save, index clauses.
#    Confirm the SNS email first. The summary email lists anything the validator discarded.
aws s3 cp sample_data/Synthetic_Payer_Formulary_Access_Agreement.pdf s3://payer-formulary-uploads-313/

# 3. Contracts CTR-1002..1004: the same route, one PDF each. (Regenerate them with
#    python scripts/generate_sample_contracts.py. The CSV loader still exists as a shortcut, but
#    its rows have no clause text, so cases built on them cannot cite clauses.)
aws s3 cp sample_data/Synthetic_Payer_Formulary_Access_Agreement_CTR-1002.pdf s3://payer-formulary-uploads-313/
aws s3 cp sample_data/Synthetic_Payer_Formulary_Access_Agreement_CTR-1003.pdf s3://payer-formulary-uploads-313/
aws s3 cp sample_data/Synthetic_Payer_Formulary_Access_Agreement_CTR-1004.pdf s3://payer-formulary-uploads-313/

# 4. Market data -> comparison -> case workflows
aws s3 cp sample_data/market_snapshots.csv s3://payer-formulary-uploads-313/market-data/

# 5. Watch the cases, then decide the ones waiting for a person
aws dynamodb scan --table-name FormularyDeviations --region us-east-1
python scripts/decide_case.py --list
python scripts/decide_case.py --key "PAY-001#PLN-1001#PRD-001" --decision approve --comment "checked"
```

**Check the extraction before trusting the rest.** After step 2, scan
`FormularyAgreementSummaries` and confirm the CTR-1001 row has
`payerPlanProductKey = PAY-001#PLN-1001#PRD-001`, `expectedTier = 2`, ISO
`effectiveFrom`/`effectiveTo`, and `graceDays = 10`. Everything downstream joins on
that row.

Expected comparison results (`payerPlanProductKey`):

| Key | Status | Severity | Classification | After the workflow |
|---|---|---|---|---|
| `PAY-001#PLN-1001#PRD-001` | Potential deviation | Critical | Tier downgrade, Parity deviation | Agents + verifier; `Pending approval` |
| `PAY-002#PLN-2001#PRD-001` | Potential deviation | High | Restriction escalation (parity `Unknown`) | Agents; `Pending approval` |
| `PAY-003#PLN-3001#PRD-001` | Closed - compliant | None | none | No workflow starts |
| `PAY-004#PLN-4001#PRD-001` | Potential deviation | Critical | Coverage loss | Agents + verifier; `Pending approval` |
| `PAY-005#PLN-5001#PRD-001` | Route to data steward | Data quality | Data-quality exception | Template only, no agent; `Not required` |

Also worth checking in the Step Functions console: the agent states link to a
turn-by-turn CloudWatch view. **On the first run confirm the harnesses report no
tool use**; that is the one setting (`AllowedTools`) that relies on an unverified
behaviour (see section 10). Both DLQs should stay empty.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Contract execution stuck in `StartTextractJob` | `textract-sns-publish-role` trust/permissions, or `resume_workflow` not subscribed to `textract-job-complete` |
| Contract execution ends `ContractExtractionFailed` | The parser agent failed (harness/model access, region) **or** its output couldn't be validated into usable terms. Open the `ParseExtraction` state's output: `issues` says why (not JSON, no coverage terms, payer not identified). Nothing was saved and re-uploading retries |
| Summary email has "Extraction notes" | The validator discarded something: an id not found in the document, an unreadable date, a non-tier value. Check those fields against the PDF. A discarded id means comparisons for that product won't match market data |
| Very large agreement fails extraction | The parser's output is capped (`MaxTokens` 4096), so a contract with many products can be cut off mid-JSON, which fails validation. Raise the cap in `ContractParserHarness` |
| Contract execution fails at `IndexClauses` | Titan embeddings access or S3 Vectors permission on `lambda-execution-role` |
| Re-upload of a failed PDF does nothing | It should reprocess (the dedupe marker is only written on success). Check for a `dedupe#...` item in `TextractJobTokens` |
| No `FormularyDeviations` rows | Contract stream not enabled or GSI missing (manual steps 1-2), or the contract's `payerId/planId/productId` don't match the market file's |
| Rows exist but no `deviation-case-workflow` executions | The pipe: check `deviation-case-trigger` is running, its role, and `ReasoningDLQ` |
| Case executions fail at an agent state | Harness model access, harness region, or `HarnessModelId` needing an inference-profile id. The workflow catches this and falls back to templates, so the case should still complete with `needsHumanEdit = true` |
| Execution ends `CaseFailed` | A deterministic step failed after retries. The row stays claimed with no result. To retry: remove `reasoningStartedAt` from the row (that edit re-triggers the pipe) |
| Case sits at `Pending approval` | Working as intended; run `scripts/decide_case.py`. After 7 days it records `Expired` |
| `needsHumanEdit = true` | An agent's wording was rejected by the guardrail, output was unparseable, an agent step failed, the verifier flagged the proposal, or no playbook rows matched. See `validationIssues`. The approved template action is still present |
| `parityDeviation = Unknown` | No snapshot for the comparator on that plan (it may simply not be in the file) |

### Cleanup

```powershell
sam delete --stack-name formulary-agent-stack
```

The vector bucket must be empty before CloudFormation can delete it; empty the
index first. Manually created resources (bucket, tables, topics, roles) are removed
separately.

---

## 10. Design decisions and known limitations

| Decision / limitation | Detail |
|---|---|
| **Step Functions orchestrates, AgentCore executes** | Agents are `InvokeHarness` states, not Lambda calls to a model. Retries, parallel fan-out (Map), error routing and the human wait are the workflow's, per the pattern in AWS's Step Functions + AgentCore guidance. |
| **Extraction fails loudly** | This is a behaviour change. Before, an unparseable answer stored a placeholder row. Now nothing is saved and the execution fails, so a person notices and re-uploads. Preferable to a wrong key that quietly matches nothing. |
| **An OCR-degraded id is discarded, not repaired** | If OCR mangles an id enough that it isn't found in the text, it is dropped and the row falls back to a name-derived key that won't match market data. The email's "Extraction notes" says so. Fuzzy matching would risk grounding a wrong id. |
| **Retrieval is deterministic, not an agent tool** | `LoadContext` fetches clauses and playbook rows by metadata filter. Giving agents a Gateway tool to search would be more "agentic" but lets them decide what to look at. Reasonable next step once the deterministic version is trusted. |
| **One harness per model** | The parser needs a stronger model than the case agents, so it has its own harness. The case agents share one harness and each state overrides the prompt, matching AWS's own sample. |
| **Verifier flags, it doesn't block** | Its verdict is stored and raises `needsHumanEdit`. A person approves every case that needs action, so a hard block would add a failure mode without adding a safeguard. |
| **Approving records a decision only** | Nothing is sent to a payer. Contract Sec 5.2 requires approval before external communication; the release step that would act on an approved case is not built. |
| **Approval is a CLI script for now** | `decide_case.py` calls `SendTaskSuccess` with the stored token, recorded against your AWS identity. A dashboard button would make the same call. |
| **S3 Vectors, not pgvector or OpenSearch** | No idle cost (OpenSearch Serverless has a large minimum) and no VPC. pgvector would have meant putting every Lambda in a VPC plus an always-on instance. |
| **Latest snapshot only** | `Market_Snapshots` keeps one row per key. Raw files stay in S3; there is no trend view. |
| **Comparator arrival** | Delayed retries (3 x 60s) cover rows in the same file. A comparator arriving in a later file doesn't re-trigger the brand's comparison; a reverse index on comparator id would fix that. |
| **Exhibit D routing vs playbook personas differ** | Exhibit D routes a tier downgrade to "Contracting + Account Director"; the playbook has Contracting Team and FRM. Both are stored (`routing`, `recommendations`); neither is reconciled. Someone should decide which governs. |
| **A superseded case with a pending approval** | If the finding changes while a case waits for approval, the old execution isn't cancelled: it waits out its 7 days, does nothing (its writes are conditional on the old signature), and costs nothing. It is clutter, not a fault. |
| **PA criteria, QL limits** | Not judged deterministically (Y/N flags only); left to the analyst agent. |
| **Stale-source threshold** | The agreement gives no number; 30 days is an assumption (`StaleSourceDays`). |
| **Textract LINE output** | Tables lose structure. The parser still reads them acceptably (its output is validated), but `StartDocumentAnalysis` with TABLES would be more accurate for Exhibits A and B. Input is capped at 100,000 characters by `resume_workflow`. |
| **Playbook edits** | Re-uploading updates changed rows but does not delete rows removed from the file. |
| **Not built** | Amendment / contract-lineage resolution, a dashboard, the release step after approval, real MMIT and Model N integration. |

### Deployment status: what has and hasn't been proven on AWS

The stack `formulary-agent-stack` is deployed in `us-east-1`. Checked against the
real account:

| Verified | How |
|---|---|
| The template deploys: both harnesses, the pipe, S3 Vectors, 10 IAM roles, both state machines | Executed a reviewed changeset; `UPDATE_COMPLETE`, no failed resources |
| Both harnesses are `READY` with the intended configuration: no tools, memory disabled, both model ids accepted, the parser's prompt intact, caps as set | Read back with `get_harness` |
| **`AllowedTools: ["@none/no-tools"]` holds** | One call to the case harness used 50 input tokens (default tool definitions alone add about 900), made no tool call, and the model reported an empty tool list |
| A harness's default system prompt applies when a state doesn't override it (the parser relies on this) | The same call answered in the JSON format the default prompt demands. Tested on the case harness; the parser uses the same mechanism |
| The harness execution role, Nova Lite access and session startup work | The same call |
| The Excel playbook ingests: 7 rows, metadata intact | Uploaded to `playbook/`; 7 vectors listed within 14 seconds |
| The case workflow's real retrieval works against S3 Vectors: every classification the rules can emit returns the right rows, two classifications return the 3 expected, a misspelled one returns none | Ran `case_logic.query_playbook` against the live index |
| The vector index matches the template (1024-dim cosine, non-filterable text fields) | `get_index` |
| **Workflow 1 on a real contract PDF**: Textract, the parser agent, validation, save, clause indexing | Uploaded the sample agreement. `SUCCEEDED` in 24 s; the agent's output passed the validator with no issues (every id found in the real OCR text, ISO dates, grace days 10); the saved row's key equals the market-data key; 25 clause vectors indexed |
| **Comparison and the whole case workflow** | Uploaded the market data. All five expected results appeared; the Pipe started case executions; paths matched the design (Critical: analyst + planners + verifier; High: no verifier; data quality: no agents); results were saved and 3 cases reached `RequestApproval` with tokens stored. Queues and DLQs empty |
| The idempotent claim absorbs duplicate triggers | 11 of 15 executions ended `AlreadyHandled` (see below for why there were so many) |

**One thing a real changeset caught that no local test could:** setting an explicit
`Type: STANDARD` on the already-deployed `pdf-summarizer` made CloudFormation try
to replace it, which is impossible for a fixed name. The property is now left
unset (the default is identical), and a test pins that.

**Found by the first real run, and what was done about it**

| Finding | Status |
|---|---|
| **The dedupe never worked.** S3's EventBridge event carries the hash as lowercase `etag`; the code read `eTag`, so every file got the key `...#unknown-etag` and an edited re-upload under the same name would have been silently skipped. Tests missed it because they used the same wrong field name | **Fixed and deployed**, with tests that fail on the old behaviour. The stale `unknown-etag` marker was deleted |
| **11 of 15 case executions were wasted duplicates.** The comparison worker re-wrote an unchanged row on every re-evaluation, each write emitting a stream event that started a workflow which found the case already claimed | Two causes. The comparison worker re-wrote identical rows (fixed). And the Pipe filter never excluded already-claimed rows: DynamoDB stream attributes are typed objects (`{"N": "..."}`) and EventBridge's `exists: false` only works on a leaf, so the pattern on the object matched every record and each of the workflow's own writes started another run. Proved with `events:TestEventPattern`, fixed as `{"N": [{"exists": false}]}`. **Deployed.** Re-running two cases now starts exactly one execution each (it was 3 to 4). The test that pinned the old pattern is corrected |
| **The verifier cries wolf.** Both Critical cases got `fail`, on text that is the approved playbook wording ("prepare a payer inquiry", "determine escalation or cure path"). It cannot see the approved actions, and its prompt forbids "external steps" that the playbook itself prescribes | **Fixed and deployed.** The verifier now sees the approved actions and only fails a step that *performs* something external. All three cases passed on re-run |
| **A root cause that missed the point.** For PAY-002 (step therapy added where prohibited) the analyst, running on Nova Lite, wrote about a Co-preferred to Preferred status change, which is not a deviation, and the personalized actions inherited that framing. Nothing flagged it (High severity skips the verifier) | **Fixed and deployed.** The facts now carry `deviatingFields` and `notDeviations` computed by the rules, and the prompts anchor to them. The re-run of PAY-002 names step therapy and drops the wording change. High severity is verified too. Still on Nova Lite: a single-case check, not a measured improvement |
| **A clause chunker bug hid in the sample PDF.** A wrapped line beginning `Exhibit B. If the Payer...` was read as a second Exhibit B heading, so CTR-1002 failed at the vector write with a duplicate key. The other two PDFs passed only by luck of line breaks. The old test used a dict, which hid duplicates | **Fixed and deployed.** A heading needs a dash or colon, and a repeated label gets a suffix. New tests fail on the old behaviour |
| **Contracts came from a CSV, not PDFs.** Only CTR-1001 was a real PDF, so emails for PAY-002 to 004 read "the contract explicitly states" over a table row | **Done and deployed.** All four contracts now come from PDFs, and the extracted terms equal the CSV values. The facts carry `contractSource` (clause text present or not), the agents word terms-only contracts as "the contract terms on file", the verifier checks that, and the approval email has a `Contract evidence:` line |
| **Retrieval picks the wrong clauses.** PAY-002 (step therapy) cites Exhibit B, 2.1, 1.4 and Exhibit D but not 2.4, the utilization-management clause. PAY-004 (coverage loss) cites 2.2 but not 2.3. The clause search text is built from tier and status, so restriction and coverage clauses rank low | **Fixed and deployed.** The search text now names the clause topic of each deviating field. Checked on the real index: the old text missed the governing clause in all three cases, the new one retrieves it (2.4 and 2.3 rank first for PAY-002 and PAY-004, 2.2 for PAY-001) |
| **A wording check I added made the verifier worse.** Asked to police "contract terms on file" vs "the contract states", the small verifier model contradicted itself and failed PAY-002 and PAY-004, and it called "the product is required to be covered" a confirmed breach | **Fixed and deployed.** The verifier is back to four checks with a clearer breach rule; the wording rule moved into code (`OVERCLAIM` in `case_logic.py`), applied only when a contract has no clause text. Re-run: both cases pass with no issues |
| Clause citations were empty on PAY-002 and PAY-004 | They ran before their PDFs were indexed. Both were re-run after the PDFs were indexed and now cite clauses (see the retrieval finding above for their quality) |

**Still unproven**

- A contract whose OCR degrades an id (the sample's ids all grounded cleanly).
- A real payer's messier data, and larger contracts against the 4096-token output cap.
- Approval by an email reply. Today the email carries a command to run, and the round trip is proven that way:
  PAY-002 was approved with `scripts/decide_case.py`, `RecordDecision` recorded `Approved`, the IAM caller and the
  comment. PAY-001 and PAY-004 are still waiting.
