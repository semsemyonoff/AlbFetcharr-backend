# AlbFetcharr backend — application dev tasks only.
#
# Docker images and compose/deploy wiring live outside this repo (in the DWE
# services layer); this Makefile only covers local development against the
# source. The same tasks are exposed as `dwe cmd backend.*` for the containerized
# workflow — this is the bare-venv equivalent.

PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF   ?= .venv/bin/ruff

.PHONY: install test lint fmt coverage run

# Install runtime + dev dependencies (declared in pyproject.toml) into the venv
install:
	$(PIP) install -e ".[dev]"

# Run test suite
test:
	$(PYTEST)

# Run linter
lint:
	$(RUFF) check .

# Format code
fmt:
	$(RUFF) format .

# Run tests with coverage report
coverage:
	$(PYTEST) --cov=albfetcharr --cov-report=term-missing

# Run the Flask dev server on :5000
run:
	$(PYTHON) -m flask --app albfetcharr.web.app run --port 5000 --debug
