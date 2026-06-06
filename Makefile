ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
else
PY := .venv/bin/python
endif

.PHONY: install lock fmt lint typecheck test check ingest extract api cli demo demo-web eval eval-judged clean

# Install core + dev dependencies into an existing .venv (Ragas is a separate extra)
install:
	$(PY) -m pip install -U pip wheel setuptools
	$(PY) -m pip install -e ".[dev]"

# Freeze exact resolved versions for reproducibility
lock:
	$(PY) -m pip freeze --exclude-editable > requirements.lock

# Auto-format and apply safe fixes
fmt:
	$(PY) -m ruff format src tests app
	$(PY) -m ruff check --fix src tests app

# Lint
lint:
	$(PY) -m ruff check src tests app

# Static type-check
typecheck:
	$(PY) -m mypy src app

# Run the test suite
test:
	$(PY) -m pytest

# Lint + types + tests (the local CI gate)
check: lint typecheck test

# Extract PDFs -> corpus -> build the retrieval index
ingest:
	$(PY) -m meridian.ingestion.build_index

# Compile booking-critical facts from the corpus -> data/extracted (needs key for a cold cache)
extract:
	$(PY) -m meridian.extraction.compile

# Run the mock Booking API
api:
	$(PY) -m uvicorn app.main:app --port 8000

# Interactive CLI assistant
cli:
	$(PY) -m meridian.cli

# Scripted CLI replay of the 20 seed messages
demo:
	$(PY) -m meridian.cli --demo

# Serve the minimal static web demo
demo-web:
	$(PY) -m uvicorn server.app:app --port 8800

# Deterministic eval tier (keyless, CI gate)
eval:
	$(PY) -m eval.harness.runner --tier deterministic

# Full eval incl. Sonnet judge + optional Ragas (needs key or committed cassettes)
eval-judged:
	$(PY) -m eval.harness.runner --tier judged
