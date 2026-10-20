##### CONFIG #####
PROJECT ?= e-core
PACKAGE ?= src/e_core
PORT    ?= 8000
ARGS     = $(filter-out $@,$(MAKECMDGOALS))

RESET   := \033[0m
BOLD    := \033[1m
GREEN   := \033[0;32m
CYAN    := \033[0;36m
GRAY    := \033[0;90m

SHELL := bash

TESTARGS  ?= -m "not slow"   ## wall-clock benchmarks leave the gate; run them with make test TESTARGS="-m slow"
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory
export PYTHONPATH := $(CURDIR)/src

##### TARGETS #####
.PHONY: help install sync lock common common-check lint type arch validate harden hooks test cov docs docs-build check ci release ci-vars clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · ruff · ty · tach · pytest · properdocs · common core + shared files of every e-stack system$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-12s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

# — env —
install: common ## full setup: materialize shared files + sync deps + git hooks
	@uv sync
	@uv run prek install
	@printf "$(GREEN)✓ ready$(RESET)\n"

sync: ## sync all deps (main + dev)
	@uv sync

lock: ## refresh uv lockfile
	@uv lock

# — common —
common: ## materialize shared project files from common/ into the project root
	@cp common/prek.toml prek.toml
	@cp common/gitattributes .gitattributes
	@cp common/python-version .python-version
	@cp common/dependabot.yml .github/dependabot.yml
	@cp common/CODEOWNERS .github/CODEOWNERS

common-check: ## fail if the materialized shared files drifted from common/
	@diff common/prek.toml prek.toml \
	 && diff common/gitattributes .gitattributes \
	 && diff common/python-version .python-version \
	 && diff common/dependabot.yml .github/dependabot.yml \
	 && diff common/CODEOWNERS .github/CODEOWNERS \
	 && printf "$(GREEN)✓ common in sync$(RESET)\n"

# — gates —
lint: ## ruff check + format
	@uv run ruff check --fix $(PACKAGE) tests scripts
	@uv run ruff format $(PACKAGE) tests scripts

type: ## ty type check
	@uv run ty check

arch: ## enforce import architecture (tach)
	@uv run tach check

validate: ## validate pyproject.toml against schema
	@uv run validate-pyproject pyproject.toml

harden: ## zizmor audit of GitHub Actions workflows (templates assemble them at generation)
	@test -d .github/workflows && uv run zizmor --persona=regular .github/workflows || echo "no workflows assembled: make infra / management gen writes them"

hooks: ## run all prek hooks on every file (ruff, ty, tach, zizmor, gitleaks)
	@uv run prek run --all-files

# — tests —
test: ## run tests, benchmarks out by default [TESTARGS='-k expr']
	@uv run pytest tests $(TESTARGS) -n auto -q

cov: ## run tests with coverage gate (fail under 90%), benchmarks out like the CI matrix
	@uv run pytest tests $(TESTARGS) --cov --cov-report=term-missing

# — docs —
docs: ## serve docs site live at :8000
	@uv run properdocs serve

docs-build: ## strict docs build to site/
	@uv run properdocs build --strict

# — aggregate —
check: lint type arch validate common-check test ## fast local gate: lint + type + arch + validate + drift + test
ci: lint type arch validate harden common-check docs-build cov ## full pipeline: every gate CI runs, in one command

# — release —
release: ## cut a GitHub release via the release workflow [args: patch|minor|major]
	@gh workflow run release.yml -f bump=$(or $(ARGS),patch)
	@sleep 5
	@gh run watch --exit-status $$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')

ci-vars: ## list optional CI/CD gates (all inert by default) and their defaults
	@printf "$(BOLD)optional CI/CD gates$(RESET) $(GRAY)— enable: gh variable set NAME --body true · manifest: .github/ci.vars.example$(RESET)\n\n"
	@grep -E '^[A-Z][A-Z0-9_]*=' .github/ci.vars.example

clean: ## remove caches + build artifacts + materialized shared files
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache site prek.toml .gitattributes .python-version
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
