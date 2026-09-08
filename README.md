# Forward Deployed Engineer / AI Integration Engineer Assessment

This repository contains my implementation of the technical assessment focused on **MCP servers, MCP authorization gateways, streaming LLM security guardrails, and resilient LLM routing infrastructure**.

The solution is organized into four independent tasks:

1. **MCP Server** — standards-compliant MCP tools with strict validation
2. **MCP Authorization Gateway** — role-based tool authorization and JSON-RPC proxying
3. **Streaming LLM Guardrail** — real-time PII detection and redaction across streaming chunks
4. **Resilient LLM Gateway** — token-aware rate limiting, provider fallback, timeouts, and sanitized errors

The implementation uses Python, FastAPI, the official MCP Python SDK, Pydantic, HTTPX, SQLite, and asynchronous I/O.

---

## Repository Structure

```text
fde-assessment/
│
├── task1/
│   ├── __init__.py
│   ├── server.py
│   └── test_server.py
│
├── task2/
│   ├── __init__.py
│   ├── downstream_mock.py
│   ├── gateway.py
│   └── test_gateway.py
│
├── task3/
│   ├── __init__.py
│   ├── redactor.py
│   ├── mock_provider.py
│   ├── gateway.py
│   └── test_redactor.py
│
├── task4/
│   ├── __init__.py
│   ├── app.py
│   ├── providers.py
│   ├── rate_limiter.py
│   ├── router.py
│   └── test_router.py
│
├── .gitignore
├── requirements.txt
└── README.md
```

---

# Setup

## Prerequisites

- Python 3.10+
- pip
- Git

Create and activate a virtual environment.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run the complete test suite:

```powershell
python -m pytest -q
```

At the time of submission, the complete suite passes:

```text
61 passed
```

A dependency-level Starlette/AnyIO deprecation warning may appear during testing; it does not affect application behavior or test results.

---

# Task 1 — MCP Server

## Objective

Implement a runnable MCP server using the official MCP SDK and expose two tools:

- `get_customer_record`
- `trigger_refund`

The server uses **stdio transport** and maintains protocol isolation by reserving stdout for MCP/JSON-RPC traffic while sending application logging to stderr.

## Tools

### `get_customer_record`

Accepts:

```json
{
  "customer_id": "CUST-12345"
}
```

Customer IDs must match:

```text
CUST-XXXXX
```

where `XXXXX` contains exactly five digits.

### `trigger_refund`

Accepts:

```json
{
  "customer_id": "CUST-12345",
  "amount": 49.99,
  "reason": "Duplicate customer payment"
}
```

Validation includes:

- strict customer ID format
- positive refund amount
- finite numeric amount
- refund reason of at least 10 characters
- rejection of unexpected fields
- strict Pydantic type validation

Invalid tool arguments are mapped to the standard JSON-RPC/MCP invalid-parameters code:

```text
-32602
```

## Design

```text
MCP Client
    |
    | stdio / JSON-RPC
    v
MCP Server
    |
    +-- tools/list
    |
    +-- tools/call
           |
           +-- Pydantic validation
           |
           +-- get_customer_record
           |
           +-- trigger_refund
```

The low-level MCP server explicitly validates arguments before executing tool logic rather than relying on advertised JSON schemas alone.

## Run

From the repository root:

```powershell
python task1/server.py
```

The process waits for MCP messages over stdin. This is expected behavior for a stdio MCP server.

Do not manually type ordinary text into the process because stdin/stdout are reserved for protocol communication.

## Tests

```powershell
python -m pytest -q task1/test_server.py
```

The tests cover:

- tool discovery
- valid customer retrieval
- valid refunds
- malformed customer IDs
- invalid refund amounts
- short refund reasons
- unknown tools
- unexpected fields
- strict input types
- MCP error behavior

---

# Task 2 — MCP Authorization Gateway

## Objective

Implement a lightweight HTTP/JSON-RPC reverse proxy between an AI agent and a downstream MCP service.

The gateway performs **fine-grained authorization before privileged tool calls reach the downstream server**.

## Authorization Model

Two example bearer tokens are configured:

```text
viewer-token -> viewer
admin-token  -> admin
```

Requests use:

```http
Authorization: Bearer <token>
```

## Routing Policy

`tools/list` requests are forwarded transparently.

For `tools/call`, the gateway inspects:

```text
params.name
```

Any tool whose name begins with:

```text
admin_
```

requires the `admin` role.

For example:

```text
get_profile
```

can be invoked by a viewer.

However:

```text
admin_reset_key
```

requires an administrator.

An unauthorized invocation returns:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32001,
    "message": "Unauthorized Tool Call"
  }
}
```

The request is rejected **before the downstream MCP service is called**.

## Architecture

```text
AI Agent
   |
   | Bearer token
   v
MCP Gateway :9000
   |
   +-- Parse JSON-RPC
   |
   +-- Extract role
   |
   +-- tools/list ----------------------+
   |                                    |
   +-- tools/call                       |
          |                             |
          +-- normal tool --------------+
          |                             |
          +-- admin_*                    |
                |                        |
                +-- admin -> ------------+
                |
                +-- viewer -> -32001
                                      |
                                      v
                             Downstream MCP :9001
```

## Run

### Terminal 1 — Downstream MCP mock

```powershell
python -m uvicorn task2.downstream_mock:app --host 127.0.0.1 --port 9001
```

### Terminal 2 — Authorization gateway

```powershell
python -m uvicorn task2.gateway:app --host 127.0.0.1 --port 9000
```

## Tests

```powershell
python -m pytest -q task2/test_gateway.py
```

Tests cover:

- bearer-token parsing
- role extraction
- transparent `tools/list` forwarding
- viewer access to normal tools
- administrator access to privileged tools
- rejection of viewer `admin_*` calls
- verification that unauthorized calls never reach downstream
- malformed JSON
- invalid JSON-RPC requests
- missing/invalid authorization
- sanitized downstream failures

---

# Task 3 — Streaming LLM PII Guardrail

## Objective

Implement an LLM proxy that inspects generated text **while it is being streamed**, redacting sensitive information without buffering the complete response.

Detected PII includes:

- email addresses
- U.S. Social Security Numbers
- credit card numbers

Sensitive values are replaced with:

```text
[REDACTED]
```

## Example

Raw provider output:

```text
Hello. Your registered email is john.smith@example.com.
Your SSN is 123-45-6789.
Your card is 4111 1111 1111 1111.
```

Gateway output:

```text
Hello. Your registered email is [REDACTED].
Your SSN is [REDACTED].
Your card is [REDACTED].
```

## Cross-Chunk Detection

A key challenge with streaming responses is that sensitive information may span multiple chunks.

For example, the provider might emit:

```text
Chunk 1: john.
Chunk 2: smith@example.
Chunk 3: com
```

Processing each chunk independently could expose the email.

The gateway therefore maintains a small bounded pending state across chunks.

```text
LLM Provider
     |
     | chunk
     v
Streaming Redactor
     |
     +-- safe prefix -> emit immediately
     |
     +-- possible partial PII -> retain temporarily
                                   |
                              next chunk
                                   |
                                   v
                          detect + redact
```

The implementation keeps pending state bounded rather than storing the complete model response.

This preserves streaming behavior while protecting PII that crosses chunk boundaries.

## Run

### Terminal 1 — Mock LLM provider

```powershell
python -m uvicorn task3.mock_provider:app --host 127.0.0.1 --port 9101
```

### Terminal 2 — Guardrail gateway

```powershell
python -m uvicorn task3.gateway:app --host 127.0.0.1 --port 9100
```

### Create test payload

```powershell
'{"prompt":"Show customer details"}' | Set-Content -Encoding utf8 payload.json
```

### Call provider directly

```powershell
curl.exe -N -X POST "http://127.0.0.1:9101/generate" `
  -H "Content-Type: application/json" `
  --data-binary "@payload.json"
```

This intentionally returns raw PII.

### Call through guardrail

```powershell
curl.exe -N -X POST "http://127.0.0.1:9100/v1/generate" `
  -H "Content-Type: application/json" `
  --data-binary "@payload.json"
```

The same sensitive values are replaced with `[REDACTED]`.

## Tests

```powershell
python -m pytest -q task3/test_redactor.py
```

Tests include:

- complete email detection
- complete SSN detection
- complete credit card detection
- email split across chunks
- SSN split across chunks
- credit card split across chunks
- multiple PII types in one stream
- preservation of normal text
- bounded pending state
- safe output before stream completion

---

# Task 4 — Resilient LLM Gateway

## Objective

Implement a resilient completion gateway providing:

- token-aware rate limiting
- per-tenant isolation
- a sliding 60-second usage window
- primary/secondary LLM routing
- timeout-based fallback
- HTTP 429 fallback
- sanitized gateway errors
- SQLite persistence

## Architecture

```text
Client
  |
  | x-api-key
  v
LLM Gateway :9200
  |
  +-- Token estimation
  |
  +-- SQLite sliding-window limiter
  |       |
  |       +-- reserve estimated usage
  |
  v
Primary Provider :9201
  |
  +-- Success --------------------------> Response
  |
  +-- HTTP 429 ----+
  |                |
  +-- >3000ms -----+
                   |
                   v
          Secondary Provider :9202
                   |
                   v
                Response
```

## Token Rate Limiting

Each tenant is limited to:

```text
50,000 tokens / 60 seconds
```

The API key supplied through:

```http
x-api-key: tenant-a
```

acts as the tenant identifier.

Usage is stored in an on-disk SQLite database.

Unlike a fixed minute counter, the limiter implements a **sliding window**. Only token usage occurring during the previous 60 seconds contributes to the current limit.

### Reservation Model

Before an LLM request is issued, the gateway reserves:

```text
estimated input tokens + max_tokens
```

This prevents concurrent requests from independently observing available capacity and collectively exceeding the limit.

SQLite uses an immediate transaction around the check-and-reserve operation.

After a successful completion, the reservation is reconciled against the provider's actual token usage.

If no provider completes successfully, the reservation is released.

## Provider Fallback

The gateway always attempts the primary provider first.

Fallback occurs specifically when the primary:

1. returns HTTP `429`, or
2. exceeds the `3000 ms` timeout.

```text
Primary success
      |
      +-----------------> return primary

Primary 429
      |
      +-----------------> secondary

Primary timeout > 3 sec
      |
      +-----------------> secondary

Primary generic failure
      |
      +-----------------> sanitized gateway failure
```

Fallback is intentionally not triggered for every possible exception.

## Sanitized Errors

Internal provider or infrastructure details are not returned to clients.

For example, a failed upstream request may produce:

```json
{
  "error": {
    "code": "UPSTREAM_UNAVAILABLE",
    "message": "Completion service temporarily unavailable",
    "request_id": "..."
  }
}
```

Raw provider stack traces and internal exception details remain server-side.

---

## Run Task 4

Three services are used.

### Terminal 1 — Primary provider

```powershell
$env:MOCK_PROVIDER_NAME="primary"

python -m uvicorn task4.providers:mock_app `
  --host 127.0.0.1 `
  --port 9201
```

### Terminal 2 — Secondary provider

```powershell
$env:MOCK_PROVIDER_NAME="secondary"

python -m uvicorn task4.providers:mock_app `
  --host 127.0.0.1 `
  --port 9202
```

### Terminal 3 — LLM gateway

```powershell
python -m uvicorn task4.app:app `
  --host 127.0.0.1 `
  --port 9200
```

---

## Test Primary Routing

Create:

```powershell
'{"prompt":"hello gateway","max_tokens":100}' |
  Set-Content -Encoding utf8 task4_payload.json
```

Send:

```powershell
curl.exe -X POST "http://127.0.0.1:9200/v1/completions" `
  -H "Content-Type: application/json" `
  -H "x-api-key: tenant-a" `
  --data-binary "@task4_payload.json"
```

The response should contain:

```json
{
  "provider": "primary"
}
```

---

## Test 429 Fallback

```powershell
'{"prompt":"force_429","max_tokens":100}' |
  Set-Content -Encoding utf8 task4_payload.json
```

Send the request again.

The response should contain:

```json
{
  "provider": "secondary"
}
```

This demonstrates:

```text
Primary -> HTTP 429 -> Secondary
```

---

## Test Timeout Fallback

```powershell
'{"prompt":"force_timeout","max_tokens":100}' |
  Set-Content -Encoding utf8 task4_payload.json
```

Send the request through the gateway.

The primary mock deliberately waits for approximately four seconds. The gateway stops waiting after approximately three seconds and routes the request to the secondary provider.

Expected provider:

```json
{
  "provider": "secondary"
}
```

---

## Test Missing API Key

A request without:

```http
x-api-key
```

returns HTTP `401` with a sanitized response:

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Missing API key",
    "request_id": "..."
  }
}
```

---

# Testing

Run every assessment test from the repository root:

```powershell
python -m pytest -q
```

Current complete test-suite result:

```text
61 passed
```

Individual suites can also be executed:

```powershell
python -m pytest -q task1/test_server.py
python -m pytest -q task2/test_gateway.py
python -m pytest -q task3/test_redactor.py
python -m pytest -q task4/test_router.py
```

---

# Key Engineering Decisions

### Strict validation at trust boundaries

MCP tool inputs are explicitly validated using Pydantic rather than assuming that clients will respect advertised schemas.

### Authorization before forwarding

Privileged MCP calls are rejected at the gateway before reaching downstream infrastructure, preventing unauthorized side effects.

### Stateful streaming inspection

PII detection maintains bounded state across stream chunks so sensitive values cannot bypass the guardrail simply by being divided across network chunks.

### Reservation-based rate limiting

Token capacity is reserved before provider execution, preventing concurrent requests from oversubscribing the same tenant's budget.

### Precise fallback conditions

Provider fallback is restricted to the specified failure modes: HTTP 429 and a 3000 ms primary timeout.

### Error sanitization

External clients receive stable gateway-level errors and request IDs rather than raw provider exceptions or infrastructure stack traces.

### Provider abstraction

Routing is separated from provider implementation, allowing upstream LLM providers to be replaced without changing gateway policy.

---

# Security Considerations

The implementation applies security controls at multiple layers:

| Layer | Control |
|---|---|
| MCP tools | Strict schema and argument validation |
| MCP gateway | Bearer-token role authorization |
| Privileged tools | Pre-forwarding `admin_*` authorization |
| LLM streaming | Real-time PII redaction |
| Tenant gateway | Per-key token quotas |
| Provider routing | Explicit fallback policy |
| Error handling | Sanitized client-facing responses |
| Persistence | SQLite-backed sliding-window accounting |

The mock credentials and providers included in this repository exist only to demonstrate assessment behavior. Production deployments should use a proper identity provider, secret management, TLS, production-grade provider credentials, distributed rate-limiting infrastructure where required, and centralized observability.

---

# Technology Stack

- **Python**
- **MCP Python SDK**
- **FastAPI**
- **Pydantic**
- **HTTPX**
- **SQLite**
- **tiktoken**
- **regex**
- **pytest**
- **Uvicorn**
- **asyncio**

---

# Summary

This assessment demonstrates four complementary integration patterns used when deploying AI systems into production environments:

```text
MCP Tooling
    +
Authorization Gateway
    +
Streaming Security Guardrails
    +
Resilient LLM Routing
```

Together, the tasks cover protocol integration, validation, authorization, streaming safety, asynchronous provider communication, tenant-aware rate limiting, fallback behavior, persistence, and secure error handling.
