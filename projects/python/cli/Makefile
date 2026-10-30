##### CONFIG #####
PROJECT  ?= e-cli
PACKAGE  ?= src/e_cli
MODULE   ?= e_cli
COMMON_SRC ?= ../common/src/e_infra
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
.PHONY: help install sync lock common common-check lint type arch validate harden hooks test cov check ci run release ci-vars clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · cyclopts · ruff · ty · tach · pytest — infra/ops/ports/providers/engines/processors materialized from $(COMMON_SRC)$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-12s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

# — env —
install: common ## full setup: materialize shared assets + sync deps + git hooks
	@uv sync
	@uv run prek install
	@printf "$(GREEN)✓ ready$(RESET)\n"

sync: ## sync all deps (main + dev)
	@uv sync

lock: common ## refresh uv lockfile (against the current materialized common)
	@uv lock

# — common —
COMMON_ROOT ?= ../common

common: ## materialize shared infra/ ops/ ports/ providers/ engines/ processors/ from projects/python/common (source of truth) via a structural rewrite, and the shared root files into the project root
	@uv run python scripts/materialize.py
	@cp $(COMMON_ROOT)/prek.toml prek.toml
	@cp $(COMMON_ROOT)/.gitattributes .gitattributes
	@cp $(COMMON_ROOT)/.python-version .python-version
	@cp $(COMMON_ROOT)/.github/dependabot.yml .github/dependabot.yml
	@cp $(COMMON_ROOT)/.github/CODEOWNERS .github/CODEOWNERS

common-check: ## fail if the materialized sections or the shared root files drifted from projects/python/common
	@uv run python scripts/materialize.py --check
	@diff $(COMMON_ROOT)/prek.toml prek.toml \
	 && diff $(COMMON_ROOT)/.gitattributes .gitattributes \
	 && diff $(COMMON_ROOT)/.python-version .python-version \
	 && diff $(COMMON_ROOT)/.github/dependabot.yml .github/dependabot.yml \
	 && diff $(COMMON_ROOT)/.github/CODEOWNERS .github/CODEOWNERS \
	 && printf "$(GREEN)✓ common in sync$(RESET)\n"

# — gates —
lint: ## ruff check + format
	@uv run ruff check --fix $(PACKAGE) src/infra src/ops src/ports src/providers src/engines src/processors scripts tests
	@uv run ruff format $(PACKAGE) src/infra src/ops src/ports src/providers src/engines src/processors scripts tests

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
check: lint type arch validate common-check test ## fast local gate: lint + type + arch + validate + drift + test
ci: lint type arch validate harden common-check cov ## full pipeline: every gate CI runs, in one command

# — release —
release: ## cut a GitHub release via the release workflow [args: patch|minor|major]
	@gh workflow run release.yml -f bump=$(or $(ARGS),patch)
	@sleep 5
	@gh run watch --exit-status $$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')

ci-vars: ## list optional CI/CD gates (all inert by default) and their defaults
	@printf "$(BOLD)optional CI/CD gates$(RESET) $(GRAY)— enable: gh variable set NAME --body true · manifest: .github/ci.vars.example$(RESET)\n\n"
	@grep -E '^[A-Z][A-Z0-9_]*=' .github/ci.vars.example

# — run —
run: ## run the cli, `ecli` [args: forwarded, e.g. make run project list]
	@uv run ecli $(ARGS)

clean: ## remove caches + build artifacts + materialized common
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache src/infra src/ops src/ports src/providers src/engines src/processors prek.toml .gitattributes .python-version
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
