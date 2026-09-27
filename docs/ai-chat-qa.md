# Chat QA and integration handoff

Implementation branch: `yehosuah/sprint8-ai-chat`, based on Tiffany's PR #31.
This branch has not been merged or deployed. The live Z.AI tool-call smoke test
remains blocked by account credit (429 / 1113); mocked success is not evidence of
live model quality or availability. All examples below use synthetic data.

## Recorded verification — September 26, 2026

- Full repository regression: **826 passed, 3 skipped, 5 subtests passed**.
- Disposable PostgreSQL 18.3 workflow run: **47 passed**, plus focused cursor and
  ownership/history checks after final hardening. Deployment uses PostgreSQL 16;
  no deployed database was touched.
- Final history/follow-up checks: **11 passed**. Earlier source dates and timestamps
  remain available to follow-ups within the bounded history context.
- Compose config, OpenAPI authentication, JSON examples and dependency compatibility
  validated. Existing AnyIO/passlib deprecation warnings remain.

## Local verification

Use Python 3.11 and the pinned requirements plus development requirements. In this
workspace the usable environment is `~/.cache/flowdesk-bck/sprint8-venv`.

```sh
python -m pytest tests/test_chat_contract.py tests/test_chat_provider.py \
  tests/test_chat_workflow.py -q
```

Workflow tests use SQLite by default. For PostgreSQL, explicitly provide a
**disposable** database named `flowdesk_chat_test`; tests create and drop their own
random tenant schemas and synthetic company/user rows. Never point this at the
application database. No `.env` database settings are used by the test fixture.

```sh
CHAT_TEST_DATABASE_URL='postgresql+psycopg2://USER@localhost:PORT/flowdesk_chat_test' \
  python -m pytest tests/test_chat_workflow.py -q
```

The PostgreSQL run additionally checks actual read-only enforcement and statement
timeouts, then verifies the connection can persist a conversation after rollback.
Both runs exercise the same route/workflow tests. The opt-in synthetic model test
is in `tests/test_chat_live.py`; leave it off until billing is fixed.

## Frontend integration (Ruth)

Use the existing bearer token. POST `/api/v1/ai/chat` with a message and optional
conversation ID. Disable duplicate sends while waiting for the complete response.
Render `answer` as untrusted text (or sanitized Markdown); show `sources` and
`limitations` from the response. The backend does not stream partial replies.

Load `/api/v1/ai/conversations` after login and after successful turns. Reopen a
conversation with `/api/v1/ai/conversations/{id}`. Detail pages contain their newest
messages in chronological order; use `next_cursor` to load and prepend older pages.
Continue with the same ID. On 404, remove the unavailable conversation from the UI;
on 409, reload it before allowing another send. DELETE uses the same detail path
and returns 204. The expanded persistent-history behavior replaces the original
session-only assumption in SCRUM-489.

A provider outage or missing key does not prevent listing, reading or deleting
existing history. Failed turns do not save the outgoing message or renew expiry.
After a transport error with uncertain outcome, reload rather than silently resend.

## Acceptance matrix (Tiffany / SCRUM-532)

| Scenario | Expected behavior |
|---|---|
| Manager/admin, own active company | Chat, list, reopen and delete succeed |
| Employee, superadmin, inactive/unassigned company | 403 before model calls |
| Other user or company's conversation | 404; never reveals title/messages |
| Inventory/sales/customer query | Approved tool only; actual period/source recorded |
| Customer purchase results | IDs and metrics only, no names/contact/address |
| Empty dataset | Zero aggregates/empty results, no invented records |
| Follow-up | Recent saved history supplied; expiry renewed on success |
| Long history | Bounded context and truncation limitation; full stored history remains pageable |
| Read history | Expiry unchanged |
| Expired conversation | Immediately inaccessible; hourly job cascades deletion |
| Concurrent turns | One revision wins; stale turn returns 409 without partial writes |
| Delete/expire while model runs | Cannot resurrect the conversation |
| Invalid model arguments | Safe correction opportunity within tool/round budget |
| Provider/network/database failure | Stable error, no partial saved turn |
| Excessive tools/output/time | Bounded failure; no partial saved turn |
| 45 concurrent chats from one user / multiple users | At most 1 / 8 generations per process; excess requests return 429 before any provider call; health and inventory respond while admitted chats remain pending |
| Failed or cancelled generation | Both user and global slots are released |
| Existing/new tenants | Repeatable upgrade / bootstrap creates chat tables |

Manual live acceptance after billing should cover: a simple sales question, a
comparison across two periods, a follow-up referring to the previous answer,
inventory shortages, purchase metrics for a customer ID, no matching data, an
unsupported write request, and a request for customer contact information. Check
figures against seeded database results, not only plausible wording.

## Deployment review

The API startup upgrades existing tenants. Review this schema addition with the
branch; it does not delete expired history at startup. Include the `chat_cleanup`
service when deploying Compose; it reuses the image built by `api`. Confirm its
startup and hourly cleanup logs; the API hides expired data even if cleanup fails.
No live database migrations, Jira transitions, teammate messages, merges or deploys
have been performed by this task. Provider keys stay in the ignored local `.env`
or the deployment's secret environment, never in these artifacts.
