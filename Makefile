# Usage: make setup | check | run | mock | test | lint | format | typecheck | audit | lock
# (On Windows without make, run the commands from the README instead.)
VENV   := .venv
BIN    := $(VENV)/bin
PYTHON ?= python3

.PHONY: setup lint format typecheck test check audit lock run mock

setup:                       ## create the virtual environment and install everything
	@$(PYTHON) -m venv $(VENV) 2>/dev/null || { \
	  echo "python3-venv is missing: using virtualenv instead (no sudo needed)"; rm -rf $(VENV); \
	  $(PYTHON) -m pip install --user --quiet virtualenv && $(PYTHON) -m virtualenv $(VENV); }
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	$(BIN)/pre-commit install || true
	@test -f .env || cp .env.example .env
	@echo "Done. Edit .env (set SCREENING_UNAVAILABLE_POLICY and keys), then: make check"

lint:                        ## style and bug checks (no changes)
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:                      ## fix style and format the code
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

typecheck:
	$(BIN)/mypy app

test:
	$(BIN)/pytest

check: lint typecheck test   ## everything CI runs

audit:                       ## scan dependencies for known vulnerabilities
	$(BIN)/pip-audit -r requirements.txt

lock:                        ## freeze exact versions
	$(BIN)/pip freeze --exclude-editable > requirements.lock

run:                         ## the connector on :8080
	$(BIN)/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8080

mock:                        ## the mock Mulisa on :9100
	$(BIN)/python -m mock_mulisa.server
