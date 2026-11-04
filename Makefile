# Campaign_AB_Test_Audit — Makefile
# NOTE: the project path contains a space ("Coding Projects"). Every path below is
# RELATIVE and QUOTED. Never embed an unquoted absolute path here.

PYTHON ?= python3.12
VENV := .venv
PY := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff

# Bake certifi's CA bundle into SSL for every target (env value only; safe before
# setup because it resolves to empty until the venv + certifi exist).
export SSL_CERT_FILE := $(shell [ -x "$(PY)" ] && "$(PY)" -m certifi 2>/dev/null)

.PHONY: setup download download-note profile validate analyze economics charts excel dashboard screenshot test lint format all clean

## setup: create the virtualenv and install pinned dependencies
setup:
	"$(PYTHON)" -m venv "$(VENV)"
	"$(PY)" -m pip install --upgrade pip
	"$(PY)" -m pip install -r requirements.txt
	@echo "setup complete. SSL_CERT_FILE -> $$("$(PY)" -m certifi)"

## download: fetch via Kaggle API if a token exists, else print manual steps (never fails hard)
download:
	"$(PY)" src/load.py --download

download-note:
	@echo "NOTE: the pipeline needs data/raw/marketing_AB.csv. Run 'make download' or place it manually."

## profile: profile the data and regenerate docs/data_sources.md + data_quality_report.md (M3)
profile:
	"$(PY)" src/profile_data.py

## validate: run test-validity checks (M4)
validate:
	"$(PY)" src/validate_test.py

## analyze: run effect / exposure / timing analysis (M5)
analyze:
	"$(PY)" src/analyze.py

## economics: run economics + recommendation (M6)
economics:
	"$(PY)" src/economics.py

## charts: render static matplotlib PNG charts into outputs/charts/ (not in `all`)
charts:
	"$(PY)" src/build_charts.py

## excel: build the live-formula Excel report (M8)
excel:
	"$(PY)" src/build_excel_report.py

## dashboard: build the self-contained HTML dashboard (M9)
dashboard:
	"$(PY)" src/build_dashboard.py

## screenshot: build the dashboard and render a PNG (best effort; not in `all`)
screenshot:
	"$(PY)" src/build_dashboard.py --screenshot

## test: run the pytest suite (M7)
test:
	"$(PY)" -m pytest -q

## lint: ruff lint + format check (no changes)
lint:
	"$(RUFF)" check src tests
	"$(RUFF)" format --check src tests

## format: auto-format the code with ruff
format:
	"$(RUFF)" format src tests
	"$(RUFF)" check --fix src tests

## all: full ordered pipeline (setup -> download note -> validate -> analyze -> economics -> excel -> dashboard)
all: setup download-note profile validate analyze economics excel dashboard
	@echo "Full pipeline complete."

## clean: remove caches + regenerable intermediates. PRESERVES .venv, data/raw, committed deliverables.
clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
	rm -f outputs/*.tmp
	@echo "clean done (preserved .venv, data/raw/, and committed outputs/*.xlsx/.html/.png)."
