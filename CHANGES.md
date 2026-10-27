# What was added on top of your code

Your 78 tests still pass (3 one-line assertions updated for the id prefix). 54 new tests, 132 in total.

| # | Change | Where |
|---|---|---|
| 1 | `transaction.id` is now `<bank>-<reference>` (Mulisa's id is unique across all banks) | `services/mapping.py`, `core/config.py` (`TRANSACTION_ID_PREFIX`) |
| 2 | Currency decimals + calling codes moved out of code into `config/reference-data.json`, validated at startup | `core/reference_data.py`, `services/money.py`, `services/mapping.py` |
| 3 | Type (`transfer`) and channel (`api`) are settings, not literals | `core/config.py`, `routers/deps.py` |
| 4 | Payments dated too far in the future are refused (`422 timestamp_in_future`), clock injectable for tests | `services/screening_service.py`, `MAX_FUTURE_SKEW_SECONDS` |
| 5 | `/docs`, `/redoc`, `/openapi.json` are off unless `ENABLE_API_DOCS=true` | `main.py` |
| 6 | Missing deliverables: `README.md`, `.env.example`, `requirements*.txt`, `.gitignore`, `scripts/demo.sh` | repo root |
| 7 | New tests: `tests/unit/test_boundaries.py`, `tests/api/test_additions.py` | `tests/` |

Tests changed (assertion only, because the id is now prefixed):
`tests/unit/test_mapping.py` (BANK dict + one assert), `tests/api/test_screening_api.py` (two asserts).

## Lint and type fixes (checked with ruff 0.7.1 and mypy 1.13, Python 3.10)

Rules E, W, F, I, B, UP, SIM, RUF at line length 120, and `mypy --strict app`: no findings.

| Finding | Fix |
|---|---|
| B008 `Depends(...)` in argument defaults (4 places) | `Annotated[T, Depends(...)]`, same behaviour: `core/security.py`, `routers/deps.py`, `routers/screening.py` |
| SIM105 try/except/pass in the mock | `contextlib.suppress(KeyboardInterrupt)` |
| E501 two over-long lines | wrapped (`mock_mulisa/server.py`, `tests/unit/test_config.py`) |
| mypy: two unused `# type: ignore` | removed (`services/mulisa_client.py`, `db/session.py`) |
| I001 import block in `services/mapping.py` | fixed (my earlier edit had split the block) |

Formatting is left to `ruff format .` with your own settings. Do not also run `black`: the two formatters
disagree and each run undoes the other.
