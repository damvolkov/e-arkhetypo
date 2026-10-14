##### CONFIG #####
PROJECT    ?= e-mcp
PACKAGE    ?= src/e_mcp
MODULE     ?= e_mcp
PORT       ?= 45200
COMPOSE    ?= compose.yml
CORE_SRC   ?= ../core/src/e_core
COMMON_SRC ?= ../core/common
TESTARGS    =
ARGS        = $(filter-out $@,$(MAKECMDGOALS))

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
.PHONY: help install sync lock core common core-check common-check lint type arch validate harden hooks test cov check ci run up down build logs release ci-vars clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · ruff · ty · tach · pytest · docker — core/ops/adapters materialized from $(CORE_SRC)$(RESET)\n\n"
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

core: ## materialize shared core/ + ops/ + adapters/ from systems/core (source of truth) via a structural rewrite
	@uv run python scripts/materialize.py

core-check: ## fail if the materialized core/ops/adapters drifted from systems/core
	@uv run python scripts/materialize.py --check

common: ## materialize shared project files from systems/core/common into the project root
	@cp $(COMMON_SRC)/pre-commit-config.yaml .pre-commit-config.yaml
	@cp $(COMMON_SRC)/gitattributes .gitattributes
	@cp $(COMMON_SRC)/python-version .python-version
	@cp $(COMMON_SRC)/dependabot.yml .github/dependabot.yml
	@cp $(COMMON_SRC)/CODEOWNERS .github/CODEOWNERS

common-check: ## fail if the materialized shared files drifted from systems/core/common
	@diff $(COMMON_SRC)/pre-commit-config.yaml .pre-commit-config.yaml \
	 && diff $(COMMON_SRC)/gitattributes .gitattributes \
	 && diff $(COMMON_SRC)/python-version .python-version \
	 && diff $(COMMON_SRC)/dependabot.yml .github/dependabot.yml \
	 && diff $(COMMON_SRC)/CODEOWNERS .github/CODEOWNERS \
	 && printf "$(GREEN)✓ common in sync$(RESET)\n"

# — gates —
lint: ## ruff check + format
	@uv run ruff check --fix $(PACKAGE) src/core src/ops src/adapters scripts tests
	@uv run ruff format $(PACKAGE) src/core src/ops src/adapters scripts tests

type: ## ty type check
	@uv run ty check

arch: ## tach architecture check
	@uv run tach check

validate: ## validate pyproject
	@uv run validate-pyproject pyproject.toml

harden: ## zizmor audit of GitHub Actions workflows
	@uv run zizmor --persona=regular .github/workflows

hooks: ## run all pre-commit hooks on every file (ruff, ty, tach, zizmor, gitleaks)
	@uv run prek run --all-files

# — tests —
test: ## run tests [TESTARGS='-k expr']
	@uv run pytest tests $(TESTARGS) -n auto -q

cov: ## run tests with coverage gate (fail under 100%)
	@uv run pytest tests --cov --cov-report=term-missing

# — aggregate —
check: lint type arch validate core-check common-check test ## fast local gate: lint + type + arch + validate + drift + test
ci: lint type arch validate harden core-check common-check cov ## every CI gate in one command

# — run —
run: ## serve the MCP app on loopback (granian factory) [args: forwarded]
	@uv run python -m $(MODULE) $(ARGS)

up: core ## docker compose up (materializes core into the build context first) [args: services]
	@docker compose -f $(COMPOSE) up -d $(ARGS)
	@printf "$(GREEN)✓ up$(RESET) $(GRAY)http://localhost:$(PORT)/mcp$(RESET)\n"

down: ## docker compose down
	@docker compose -f $(COMPOSE) down

build: core ## docker image build [args: services]
	@docker compose -f $(COMPOSE) build $(ARGS)

logs: ## tail docker logs [args: service]
	@docker compose -f $(COMPOSE) logs -f $(ARGS)

# — release —
release: ## cut a GitHub release via the release workflow [args: patch|minor|major]
	@gh workflow run release.yml -f bump=$(or $(ARGS),patch)
	@sleep 5
	@gh run watch --exit-status $$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')

ci-vars: ## list optional CI/CD gates (all inert by default) and their defaults
	@printf "$(BOLD)optional CI/CD gates$(RESET) $(GRAY)— enable: gh variable set NAME --body true · manifest: .github/ci.vars.example$(RESET)\n\n"
	@grep -E '^[A-Z][A-Z0-9_]*=' .github/ci.vars.example

clean: ## remove caches + build artifacts + materialized core
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache site src/core src/ops src/adapters .pre-commit-config.yaml .gitattributes .python-version
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
