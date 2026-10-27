# Mulisa screening connector, Python edition (Track C)

A small service between greenbank's core banking system and Mulisa (jengacore's transaction-screening platform).
The core system sends a payment in **greenbank's own JSON format**; the connector validates it, maps it to Mulisa's
`POST /api/screen` contract, calls Mulisa with a timeout and at most one retry, and returns one normalised decision:
**`cleared`**, **`flagged`** or **`unavailable`**.

FastAPI + SQLAlchemy + SQLite, organised in layers. All data is synthetic.

## Set up (virtual environment + dependencies)

```bash
make setup                    # creates .venv, installs requirements-dev.txt, installs the git hook, copies .env.example to .env
```

Without `make` (for example on Windows):

```bash
python3 -m venv .venv    # if this says 'ensurepip is not available' and you have no sudo: python3 -m pip install --user virtualenv && python3 -m virtualenv .venv
source .venv/bin/activate              venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env
```

Then edit `.env`: set `SCREENING_UNAVAILABLE_POLICY` (`fail_open` or `fail_closed`) and replace the two `CHANGE_ME` keys
(the app refuses to start with placeholders). Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Use the same Mulisa key in `MULISA_API_KEY` and `MOCK_API_KEY`.

**First thing to run, once:** `make format` (ruff formats and fixes import order), so that CI's `ruff format --check` passes.

## Everyday commands

| Command | What it does |
|---|---|
| `make check` | everything CI runs: lint, format check, types, tests |
| `make test` | pytest with coverage |
| `make lint` / `make format` | ruff check + format check / fix and format |
| `make typecheck` | mypy (strict) on `app/` |
| `make audit` | `pip-audit` on the runtime dependencies |
| `make mock` | local mock Mulisa on :9100 |
| `make run` | the connector on :8080 (docs at http://127.0.0.1:8080/docs) |
| `make lock` | freeze exact versions into `requirements.lock` |

Run both services in two terminals (`make mock`, then `make run`) and call it:

```bash
curl -s localhost:8080/payments/screen -H "X-Api-Key: $YOUR_CONNECTOR_KEY" -H "Content-Type: application/json" \
  -d '{"reference":"GB-PAY-20261014-0042","amount":"250000","currency":"RWF",
       "debtor":{"msisdn":"250788000111","name":"Aline Uwase","wallet":"GB-0001"},
       "creditor":{"msisdn":"250722000333","name":"Eric Mugisha","provider":"bluemobile"},
       "createdAt":"2026-10-14T16:40:00Z"}'
```

## Project layout (one job per layer)

```
app/
  main.py                   application factory: wiring, request-id + size-limit middleware
  core/
    config.py               Settings from env; the policy is REQUIRED, placeholders refused
    security.py             API-key authentication (constant time, deny by default)
    errors.py               one error envelope for every failure
    log.py                  JSON log lines, safe fields only
  db/session.py             engine, session factory, declarative Base
  models/screening.py       SQLAlchemy model: ScreeningRecord (unique by reference)
  schemas/
    payment.py              what the bank sends (Pydantic, strict, no coercion)
    screening.py            what we return, plus the error envelope
    mulisa.py               Mulisa's request and response (status is a Literal)
  repositories/
    screening_repository.py the ONLY code that talks to the database
  services/
    money.py                decimal string -> integer minor units (Decimal, never float)
    mapping.py              bank message -> Mulisa request
    mulisa_client.py        timeout on every call, at most one retry, never raises for upstream trouble
    screening_service.py    the flow: duplicate check -> map -> call -> normalise -> policy
  routers/
    screening.py, health.py HTTP only: parse, authenticate, delegate
    deps.py                 builds session -> repository -> service per request
mock_mulisa/server.py       local Mulisa from the public contract, with fault injection (stdlib)
tests/
  unit/                     money, schemas, mapping, config
  repositories/             database behaviour (including the unique constraint)
  api/                      end to end over the real app and the real mock
data/payments.json          synthetic sample payments
.github/workflows/ci.yml    CI
```

Request flow: `router` (auth, parse) -> `service` (rules) -> `repository` (database) and `mulisa_client` (network).
The service imports no FastAPI and the router contains no business logic, so each layer can be tested alone.

## API

`POST /payments/screen` (`X-Api-Key: <key>` or `Authorization: Bearer <key>`) and `GET /health`.

| decision | `recommended_action` | when |
|---|---|---|
| `cleared` | `release` | Mulisa answered `cleared` |
| `flagged` | `hold` | Mulisa answered `flagged` (advisory: the bank decides) |
| `unavailable` | `release` if `fail_open`, `hold` if `fail_closed` | Mulisa could not decide; also carries `policy_applied` and `reason` (`timeout`, `upstream_error`, `upstream_rejected`, `upstream_unreachable`, `upstream_bad_response`) |

Errors are always `{"error": {"code", "message", "request_id", "details"?}}`, never a stack trace and never an echoed value:
`400 invalid_json`, `401 unauthenticated`, `404`, `405`, `409 reference_conflict`, `413 payload_too_large`, `422 validation_failed`, `500 internal_error`.

## CI (GitHub Actions, `.github/workflows/ci.yml`)

Runs on every push to `main` and every pull request, with read-only permissions (`contents: read`):

1. **lint**: `ruff check`, `ruff format --check`, `mypy app`
2. **test**: pytest with coverage on Python 3.10, 3.11, 3.12 and 3.13
3. **audit**: `pip-audit` on the runtime requirements

Locally the same checks run with `make check`, and a pre-commit hook runs ruff and mypy before each commit.
Hardening still to do: pin the actions to commit SHAs instead of `@v4`.

## Design choices

- **`transaction.id` is the bank's payment reference**, and the request is serialised **once** and re-sent byte for byte on a retry.
  Mulisa treats `transaction.id` as an idempotency key, so a retry after a timeout cannot create a second screening.
- **Retry only when safe and useful:** on a timeout, or when Mulisa's error says `"retryable": true`. 4xx, non-retryable 5xx and
  connection refused are not retried. Never more than one retry.
- **A duplicate never reaches Mulisa.** Decisions are stored by reference (`UNIQUE` column). A repeat returns the stored result with
  `replayed: true`; the same reference with a different payment is `409`. A per-reference lock makes concurrent duplicates wait and then read the
  stored decision; the database unique constraint is the backstop across processes.
- **`unavailable` is not stored:** nothing was screened, so a re-submission gets a fresh attempt.
- **Fail safe:** a `200` whose `status` is not exactly `cleared` or `flagged`, or a non-JSON body, is `unavailable`, never `cleared`.
- **Money is never a float:** the amount must be a JSON string, parsed with `Decimal`; a fraction the currency cannot hold (`"10.5"` RWF) is rejected.
- **No personal data in logs, the database or error responses** (tested).

## Mapping assumptions

Everything the public Mulisa contract does not state is my assumption: `type="transfer"`, `channel="api"`; `sender.account` = the debtor wallet;
`receiver.account` = the creditor MSISDN; `sender.institution_id` = `BANK_INSTITUTION_ID`; `receiver.institution_id` = the creditor's provider;
`country_to` from the calling code (omitted if unknown); unknown currencies rejected; amounts in integer minor units (RWF 0 decimals, KES 2).
`kyc_level`, `risk_score`, `pep` and `metadata` are not sent: the bank message does not have them.

**Known gap:** the copy of the Mulisa OpenAPI that I could read was cut off before `components.schemas.ScreeningRequest`, so which fields are *required*
is unverified. Check the live schema and adjust `app/services/mapping.py` and `mock_mulisa/server.py` if it asks for more.

## Unavailable-screening policy (required, no default)

`SCREENING_UNAVAILABLE_POLICY` must be `fail_open` (release) or `fail_closed` (hold); the app exits at startup without it (tested).

- **fail_open:** customers are never blocked by a screening outage, but payments move **unscreened**, which on an instant network cannot be undone.
- **fail_closed:** nothing moves unscreened, but customers wait during an outage and the bank needs a queue to re-screen held payments.

**Recommendation for greenbank, a 250,000 RWF transfer at night with Mulisa down: `fail_closed`.** The amount is not trivial, nobody is awake to review,
an unscreened release is irreversible and a hold is only a delay. A refinement not built here: `fail_open` below a small limit, `fail_closed` above it.
**If a retry did not reuse the same `transaction.id`,** Mulisa would treat it as a new payment: a payment whose first call actually landed would be screened
twice (duplicate cases and alerts, double-counted statistics, duplicate webhooks, possibly two different answers).

## Security note

1. **An outage silently becomes "let it through".** Done: the policy is required, unknown answers are never `cleared`, both policies are tested. Would do: alert on the `unavailable` rate, tiered policy.
2. **Stolen API key.** Done: one key per caller, constant-time hash comparison, minimum length, placeholders refused, keys only in the environment, `.env` git-ignored, body size cap, Mulisa redirects refused. Would do: rate limiting, key rotation, mutual TLS.
3. **Personal data leaking.** Done: never logged (tested), never stored (the table holds decisions only), never echoed in errors; `MULISA_URL` must be https unless localhost. Would do: encrypt the database, retention period, run behind TLS.

Known limits: the per-reference lock works in one process (the unique constraint covers several); the client timeout is per socket operation, not for the whole call;
the size limit relies on `Content-Length`; a request with a bad key and a malformed body gets the body error first (FastAPI parses the body before dependencies run);
tables are created at startup, so a real deployment needs migrations (Alembic); SQLite is for the exercise, set `DATABASE_URL` to Postgres for more.

**Dependency audit:** `make audit` runs `pip-audit` (and CI does on every run). Note the result here once you have run it.

## What I did not finish

Live run against the real Mulisa sandbox and required-field check (see above); tiered policy and a durable hold queue with automatic re-screening;
ISO 20022 / batch screening; Docker Compose; metrics; rate limiting.
