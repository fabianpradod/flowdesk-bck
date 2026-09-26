# Chat API contract

**Status:** provider, tools, chat/history routes, access controls, storage and
retention are implemented on `yehosuah/sprint8-ai-chat`. Live model verification
is pending Z.AI billing (HTTP 429 / code 1113). The existing `/ai/analysis` endpoint
retains its current behavior. See [QA and deployment notes](ai-chat-qa.md).

## Authentication and ownership

All routes require JWT authentication, manager/admin access, and an active
company. Only the exact `manager` and `admin` roles are admitted; `superadmin`
does not bypass this guard. The backend resolves company and user identity from the JWT. Conversations
belong to their creator within that company. IDs belonging to someone else, expired
IDs, and deleted IDs return the same 404 response.

## Routes

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/v1/ai/chat` | `ChatRequest` | `ChatResponse` |
| GET | `/api/v1/ai/conversations` | optional `cursor`, `limit` | `ConversationList` |
| GET | `/api/v1/ai/conversations/{id}` | optional `cursor`, `limit` | `ConversationDetail` |
| DELETE | `/api/v1/ai/conversations/{id}` | none | 204 |

Schemas live in `app/schemas/chat.py`. `message` is trimmed, nonempty, and at most
4,000 characters. Omit `conversation_id` (or send null) to start a conversation;
send the returned ID for follow-ups. Additional request fields are rejected,
including client-provided history, tools, system prompts, user IDs, and tenant IDs.

```json
{
  "message": "¿Cómo cambiaron las ventas este mes?",
  "conversation_id": null
}
```

Example response shape (illustrative data):

```json
{
  "conversation_id": "f20429cf-7b9d-4489-8f18-d3f54e918b78",
  "message_id": "cc65276d-4445-4f43-b010-77ad7114e2b2",
  "answer": "Las ventas netas del periodo fueron 100.00.",
  "created_at": "2026-09-26T12:00:00Z",
  "expires_at": "2026-10-11T12:00:00Z",
  "sources": [{
    "tool": "sales_metrics",
    "domain": "sales",
    "start_date": "2026-09-01",
    "end_date": "2026-09-26",
    "as_of": "2026-09-26T12:00:00Z",
    "filters": {"start_date": "2026-09-01", "end_date": "2026-09-26"}
  }],
  "limitations": ["No se incluyen ventas en borrador."]
}
```

Source metadata comes from executed backend tools, never from model-authored
citations. `as_of` indicates when data was read; dates describe the actual queried
range. Both dates are null for a current snapshot. `filters` contains only approved
query parameters, excluding customer names/contact details. Multiple tools or
comparison periods can produce multiple sources. Unsupported questions can have
an empty source list and an explicit limitation.

Conversation lists return `items` and an opaque `next_cursor` (null at the end).
Summaries contain `id`, `title`, `created_at`, `last_message_at`, and `expires_at`.
Detail responses contain `conversation`, `messages`, and `next_cursor`. Public
messages contain `id`, `role` (`user` or `assistant`), `content`, `created_at`,
`sources`, and `limitations`; system messages, internal reasoning, and raw tool
transcripts are not part of this contract. All timestamps include a timezone.

Lists sort by most recent message, then ID descending (default limit 20, max 100).
Detail returns the latest page (default 50 messages, max 100), with messages in
chronological order within that page. Its `next_cursor` loads **older** messages;
prepend those to the UI. Cursors are opaque and tied to their endpoint. A list can
change while paginating if a conversation receives a new message; refresh the first
page after posting. Invalid cursors return 422. Reading either endpoint never
extends expiry.

The backend supplies up to 20 recent messages and 16,000 history characters,
starting with a complete user turn. Prior source periods and timestamps are
included as historical metadata within that same budget, so follow-ups can refer
to the earlier period without treating old figures as fresh. Truncation is
reported in `limitations`.
The model is instructed to query tools for fresh business facts on each turn. Conversation expiry is 15 days after the most recent message, not
after the most recent read. Reading history does not extend retention.

## Provider boundary and configuration

`ChatProvider.complete()` performs one asynchronous provider call. It returns
either answer text or validated tool-call envelopes, without executing any tool.
The service validates each tool's arguments before execution, using the authenticated company context.
The returned internal assistant message preserves tool IDs and provider reasoning
for the next tool round; it must never be returned in the public history or logged.

`get_chat_provider` is a FastAPI-compatible dependency that tests can override.
Missing credentials do not cause a network request. Configuration:

| Variable | Default | Meaning |
|---|---|---|
| `ZAI_API_KEY` | none | Server-side credential, kept in environment only |
| `ZAI_MODEL` | `glm-5.3-flash` | Model ID |
| `ZAI_BASE_URL` | `https://api.z.ai/api/paas/v4` | HTTPS base URL without embedded credentials/query/fragment |
| `ZAI_TIMEOUT_SECONDS` | `30` | Per-call wall-clock ceiling; chat validates `(0, 120]` |
| `ZAI_CHAT_MAX_TOKENS` | `4096` | Output budget including reasoning; range `[512, 8192]` |

Chat uses non-streaming function calls and low reasoning effort. At most eight
tool-call envelopes are accepted in one completion; each JSON argument string is
capped at 16,000 characters. The workflow permits at most four model calls and six tool calls per turn.
The last model call has tools disabled. The adapter permits callers to pass a smaller remaining time budget,
disallows redirects, and does not retry automatically.

`httpx` is a runtime dependency as both AI integrations import it. It was formerly
present only in the development requirements.

## Error vocabulary

Errors use the existing envelope: `{"message": "...", "code": "...", "errors": []}`.
Provider bodies, keys, and internal reasoning are not forwarded to callers.

| HTTP | Code | Meaning |
|---|---|---|
| 502 | `invalid_ai_response` | Malformed response, unadvertised tool, invalid tool-call envelope |
| 502 | `ai_response_truncated` | Output budget exhausted; partial answer is not treated as success |
| 502 | `ai_response_filtered` | Provider could not answer the request |
| 502 | `ai_provider_error` | Other upstream error, including redirects |
| 503 | `ai_provider_unavailable` | Missing key, network failure, or provider unavailable |
| 503 | `ai_provider_misconfigured` | Invalid endpoint or resource limits |
| 503 | `ai_provider_auth_error` | Provider rejected the configured credential |
| 503 | `ai_provider_rate_limited` | Provider returned 429 without the missing-credit code |
| 503 | `ai_provider_quota_exhausted` | Z.AI code 1113: insufficient API balance or no resource package |
| 504 | `ai_provider_timeout` | Call deadline exceeded or upstream timeout |

Route-level errors use existing 401/403/422 handling plus:

| HTTP | Code | Meaning |
|---|---|---|
| 404 | `conversation_not_found` | Missing, other owner/company, expired or deleted conversation |
| 409 | `conversation_conflict` | Another successful turn changed this conversation; reload before retrying |
| 422 | `invalid_cursor` | Invalid pagination cursor |
| 502 | `ai_tool_limit` | Tool count, round or cumulative data context budget exhausted |
| 502 | `ai_tool_result_too_large` | A tool result exceeded its output bound |
| 503 | `ai_data_unavailable` | Query/storage failure or database statement timeout |
| 504 | `ai_timeout` | Overall model/tool orchestration deadline exceeded |

A successful turn atomically saves the user message and complete assistant answer.
Failures save neither, create no new conversation, and do not extend retention.
Concurrent follow-ups use an optimistic revision check; losing requests return 409
without overwriting messages. Deletion/expiry during generation returns 404 and
cannot recreate the conversation. Do not automatically retry chat POST requests:
reload after uncertain network errors to check whether the turn was saved.

Protocol references:
[Z.AI function calling](https://docs.z.ai/guides/capabilities/function-calling),
[chat completion API](https://docs.z.ai/api-reference/llm/chat-completion).

## Local live smoke test

Put `ZAI_API_KEY` in the gitignored `.env` (standard Z.AI API account with API
credit). Then run this explicitly to make two bounded model calls with synthetic
sales data. The test verifies tool selection and that the final answer consumes
the tool result. It does not query the database. Route/workflow behavior is covered by the
integration suite described in the QA notes.

```sh
RUN_ZAI_INTEGRATION_TEST=1 ~/.cache/flowdesk-bck/sprint8-venv/bin/python \
  -m pytest -q -s tests/test_chat_live.py
```

Normal test runs skip this test. GitHub Actions secrets do not populate the local
`.env`; the current deployment also reads a separate `.env` on EC2.


## Approved business tools and limits

| Tool | Data and filters |
|---|---|
| `inventory_metrics` | Current active product counts, stockouts, below-minimum counts and retail stock value |
| `inventory_products` | Active product ID/name/SKU, stock/minimum/unit/sale price; optional exact SKU, `stock_status=all\|low\|out_of_stock`, `limit` |
| `inventory_trend` | Movement-derived units in/out and net change, including adjustments and inactive products |
| `sales_metrics` | Finalized sale count, gross subtotal, discounts, tax, net sales and average ticket |
| `sales_trend` | Finalized sale count and net sales by day or month |
| `top_products` | Finalized sale-line revenue and quantities ranked by revenue; optional `limit` |
| `customer_purchases` | Customer UUID, purchase count, net sales, average ticket and last purchase date; optional `customer_id` and `limit` |

Date-based tools accept paired `start_date` / `end_date`, inclusive UTC dates,
maximum 366 days and no future dates. When omitted, the actual range is the last
30 calendar days including today. Trends use daily buckets up to 60 days, monthly
buckets thereafter; periods without activity are omitted and boundary months can
be partial. Ranked tools default to 20 entries (maximum 50), explicitly report
truncation, and use stable tie-break ordering. Unknown/extra arguments are rejected.
Invalid tool arguments are returned to the model for correction within the same
bounded loop; database failures abort the turn rather than masquerading as no data.

Final sale states match existing analytics: `completada`, `confirmada`, `finalizada`,
`pagada`. Net sales include tax and sale-level discounts. Product line revenue
excludes those sale-level adjustments. Current stock value uses **selling price**,
not cost/profit. Below-minimum stock is a current shortage indicator, not a demand
forecast. Movement units may be incompatible across products; do not sum unlike
units. Customer summaries exclude anonymous sales. No currency conversion occurs.

Queries use fixed SQLAlchemy projections and aggregates inside the authenticated
tenant schema; PostgreSQL enforces read-only transactions for tools. Customer
projections never join customer identifying columns. The model has no SQL tool,
write tool or tenant-selection argument. Product names/SKUs and tool data are
untrusted context. User-entered messages are sent to Z.AI and stored as entered;
this is not an automatic PII scrubber for text a user chooses to type.

Limits: 60-second model/tool orchestration budget; provider calls also respect
`ZAI_TIMEOUT_SECONDS`; PostgreSQL statement/lock waits are capped at five seconds
(and reduced to the remaining budget during generation). Final persistence uses
bounded statements after checking the remaining deadline. Provider output is
capped by tokens; answers by 16,000 characters; one tool result by 24,000 characters;
all tool context by 48,000 characters. No provider retries run automatically.

## Retention and schema lifecycle

New tenant bootstrap creates `chat_conversation` and `chat_message`. API startup
idempotently creates these tables for existing registered tenants and removes
expired history. Existing business tables are not recreated. Conversations are
inaccessible at `expires_at` even before cleanup runs. Reads never refresh expiry;
a successful new turn sets it to 15 days after that turn. Manual deletion removes
messages through the database foreign-key cascade.

`docker-compose.yml` includes an hourly `chat_cleanup` process. It uses the same
application image/database and deletes expired conversations (including inactive
companies) with cascading message deletion. Configure an equivalent recurring
job if deploying without Compose:

```sh
python -m app.services.chat_maintenance --once
# For an explicit pre-start existing-tenant upgrade:
python -m app.services.chat_maintenance --once --upgrade
```

The job logs counts or a sanitized failure message, never conversation content.
Without a running cleanup process, expired rows remain physically stored although
the API denies access. Backup retention is governed separately by deployment policy.
