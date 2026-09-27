# Sprint 8: conversational business assistant

Agreed with Yehosua on September 26, 2026. Sprint ends September 28.

## Delivery agreement

Implement the agreed chunks autonomously. The user subsequently authorized
finishing all remaining chunks together while leaving live-model billing pending. Ask about new product/scope decisions as they
arise. Branch: `yehosuah/sprint8-ai-chat`, based on `origin/tiffany/sprint8` at
`e2893ecf99c75085496546cab3861196f0e8ede4` (dependency PR #31).

Do not merge or deploy as part of a chunk review. Main deploys to EC2 on push.

## Agreed behavior

- Flexible questions and follow-ups across inventory, sales, and customers through
  approved, read-only backend tools. No model-generated SQL or write tools.
- Provider/model: Z.AI `glm-5.3-flash`, reusing the project's provider configuration.
- Managers and admins, restricted to their own company.
- One complete answer with backend-recorded data sources, date ranges, and limitations.
- Conversations saved on the backend, private to their original user. Reopening
  requires continued access to the assistant and the same company.
- Expire after **15 days since the most recent message**, with manual deletion too.
  Expired history is inaccessible; periodic cleanup removes expired stored data.
- Business context sent to Z.AI may contain customer IDs and purchase metrics, but
  excludes customer names, emails, phone numbers, and addresses.

## Chunks and Jira mapping

| Chunk | Tickets | Result |
|---|---|---|
| 1. Provider and contract | SCRUM-475, 476, 482 | Reproducible test environment; tool-calling provider boundary; public request/history/reply schemas; error vocabulary. |
| 2. Business tools | SCRUM-477, 478, 479, 480 | Validated inventory, sales, and customer tools with tenant/role enforcement and bounded output. |
| 3. Conversation workflow | SCRUM-474, 481 | Chat endpoint and bounded tool loop; history/list/delete endpoints; tenant tables, existing-tenant upgrade, expiry and cleanup. |
| 4. Failure handling and handoff | SCRUM-483, 484 | End-to-end failure coverage, final documentation/examples, frontend and QA handoff. |

Tests accompany each chunk. Provider and contract tests in Chunk 1 do not complete
the chatbot endpoint or the end-to-end error-handling ticket.

## Query-tool scope

- Inventory metrics, stock risk, and movement trends.
- Sales totals, time trends, and top-selling products.
- Customer purchase summaries using customer IDs.
- Existing analytics semantics and supported date ranges, with limitations made explicit.
- Backend computes numeric summaries. The model explains evidence; unsupported
  questions and unavailable data must not produce invented results.

## Acceptance and integration

Cover tenant and conversation-owner isolation, manager/admin access and employee
rejection, follow-ups, deletion/expiry, bounded tool execution, invalid arguments,
missing data, and provider errors/timeouts. Bound the whole chat request as well
as each provider call in Chunk 3.

Ruth owns the frontend (SCRUM-485–493). Persistent reopening expands the original
session-only UI ticket SCRUM-489; its API contract is documented for integration.
Tiffany owns chatbot QA (SCRUM-532); new backend tests accompany implementation.
No Jira assignments or statuses have been changed and no teammate messages sent.

## Environment and verification

The old `.venv` contains cloud-storage placeholders and dependency versions that
do not match `requirements.txt`. Preserve it and use a separate environment:

```sh
uv venv --python 3.11 ~/.cache/flowdesk-bck/sprint8-venv
uv pip install --python ~/.cache/flowdesk-bck/sprint8-venv/bin/python \
  -r requirements.txt -r requirements-dev.txt
RUN_ZAI_INTEGRATION_TEST=0 ~/.cache/flowdesk-bck/sprint8-venv/bin/python -m pytest -q
```

Network provider tests stay opt-in. Mock-provider success is not evidence of live
model availability or production answer quality.

### Chunk 1 validation — September 26

- Inherited branch baseline: 725 passed, 1 opt-in live test skipped, 5 subtests passed.
- Chat contract/provider plus existing AI tests: 74 passed, 1 opt-in live test skipped.
- Documented request and response examples validate against the schemas.
- Live tool-call test attempted with the configured local key. Z.AI returned HTTP
  429 / code 1113. A minimal diagnostic request confirmed missing API credit or a
  resource package. Live model behavior remains unverified until billing is funded.
- Updated the chat adapter to distinguish this account condition from throttling.


### Remaining chunks implemented — September 26

- Chunk 2: seven approved read-only tools, bounded SQL aggregates and validated
  filters; customer context contains IDs and purchase metrics only.
- Chunk 3: authenticated chat/list/detail/delete routes; private persistent history,
  atomic turns, optimistic concurrency, 15-day inactivity expiry, tenant table
  bootstrap/upgrade and hourly physical cleanup.
- Chunk 4: bounded orchestration and database waits, safe errors, rollback and
  authorization coverage, plus frontend/QA and deployment documentation.
- PostgreSQL 18.3 disposable local database: 47 workflow tests passed, including
  actual read-only enforcement, statement timeout/recovery, schema upgrade and
  cascade deletion. Final cursor and history-ownership hardening also passed
  focused PostgreSQL checks (6 cursor cases and 4 ownership/history cases).
- SQLite workflow plus tenant/startup regressions: 64 passed before the final
  hardening. Full repository regression: **826 passed, 3 skipped, 5 subtests
  passed**, in 12m23s. Skips: two opt-in live-model tests and the PostgreSQL-only
  transaction test (which passed in the separate PostgreSQL run).
- Final history/cursor changes were verified with focused reruns: 6 PostgreSQL
  cursor cases, 4 PostgreSQL ownership/history cases, and 11 SQLite
  history/follow-up cases, including preserved prior source dates.
- OpenAPI bearer security and documented JSON examples validated. Compose config
  validated; all 41 installed environment packages are compatible.
- No live model retry was made, per the user's instruction to defer billing.

The backend implementation covers SCRUM-474 through SCRUM-484, pending code review
and the deferred live-model acceptance. Frontend SCRUM-485–493 and Tiffany's QA
SCRUM-532 remain with their owners. Jira states were not changed.
