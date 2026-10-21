##### CONFIG #####
PROJECT  ?= e-tui
PACKAGE  ?= src/e_tui
MODULE   ?= e_tui
CORE_SRC ?= ../core/src/e_core
TESTARGS  =
ARGS      = $(filter-out $@,$(MAKECMDGOALS))

RESET   := \033[0m
BOLD    := \033[1m
GREEN   := \033[0;32m
CYAN    := \033[0;36m
GRAY    := \033[0;90m
RED     := \033[0;31m

SHELL := bash
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory
export PYTHONPATH := $(CURDIR)/src

##### TARGETS #####
.PHONY: help install sync lock core common core-check common-check lint type arch validate harden hooks test cov check ci run release ci-vars clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · textual · ruff · ty · tach · pytest — core/ops/adapters materialized from $(CORE_SRC)$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-12s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

# — env —
install: core common ## full setup: materialize shared assets + sync deps + git hooks
	@uv sync
	@uv run prek install
	@printf "$(GREEN)✓ ready$(RESET)\n"

sync: ## sync all deps (main + dev)
	@uv sync

lock: core ## refresh uv lockfile (against the current materialized core)
	@uv lock

# — common —
COMMON_SRC ?= ../core/common

core: ## materialize shared core/ + ops/ + adapters/ from projects/python/core (source of truth) via a structural rewrite
	@uv run python scripts/materialize.py

core-check: ## fail if the materialized core/ops/adapters drifted from projects/python/core
	@uv run python scripts/materialize.py --check

common: ## materialize shared project files from projects/python/core/common into the project root
	@cp $(COMMON_SRC)/prek.toml prek.toml
	@cp $(COMMON_SRC)/gitattributes .gitattributes
	@cp $(COMMON_SRC)/python-version .python-version
	@cp $(COMMON_SRC)/dependabot.yml .github/dependabot.yml
	@cp $(COMMON_SRC)/CODEOWNERS .github/CODEOWNERS

common-check: ## fail if the materialized shared files drifted from projects/python/core/common
	@diff $(COMMON_SRC)/prek.toml prek.toml \
	 && diff $(COMMON_SRC)/gitattributes .gitattributes \
	 && diff $(COMMON_SRC)/python-version .python-version \
	 && diff $(COMMON_SRC)/dependabot.yml .github/dependabot.yml \
	 && diff $(COMMON_SRC)/CODEOWNERS .github/CODEOWNERS \
	 && printf "$(GREEN)✓ common in sync$(RESET)\n"

# — gates —
lint: ## ruff check + format
	@uv run ruff check --fix $(PACKAGE) src/core src/ops src/adapters src/processors scripts tests
	@uv run ruff format $(PACKAGE) src/core src/ops src/adapters src/processors scripts tests

type: ## ty type check
	@uv run ty check

arch: ## enforce import architecture (tach)
	@uv run tach check

validate: ## validate pyproject.toml against schema
	@uv run validate-pyproject pyproject.toml

harden: ## zizmor audit of GitHub Actions workflows (templates assemble them at generation)
	@test -d .github/workflows && uv run zizmor --persona=regular .github/workflows || echo "no workflows assembled: e-taxis writes them"

hooks: ## run all prek hooks on every file (ruff, ty, tach, zizmor, gitleaks)
	@uv run prek run --all-files

# — tests —
test: ## run tests [TESTARGS='-k expr']
	@uv run pytest tests $(TESTARGS) -n auto -q

cov: ## run tests with coverage gate (fail under 100%)
	@uv run pytest tests --cov --cov-report=term-missing

# — aggregate —
check: lint type arch validate core-check common-check test ## fast local gate: lint + type + arch + validate + drift + test
ci: lint type arch validate harden core-check common-check cov ## full pipeline: every gate CI runs, in one command

# — release —
release: ## cut a GitHub release via the release workflow [args: patch|minor|major]
	@gh workflow run release.yml -f bump=$(or $(ARGS),patch)
	@sleep 5
	@gh run watch --exit-status $$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')

ci-vars: ## list optional CI/CD gates (all inert by default) and their defaults
	@printf "$(BOLD)optional CI/CD gates$(RESET) $(GRAY)— enable: gh variable set NAME --body true · manifest: .github/ci.vars.example$(RESET)\n\n"
	@grep -E '^[A-Z][A-Z0-9_]*=' .github/ci.vars.example

# — run —
run: ## run the demo tui, `etui`
	@uv run etui $(ARGS)

clean: ## remove caches + build artifacts + materialized core
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache src/core src/ops src/adapters src/processors prek.toml .gitattributes .python-version
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
