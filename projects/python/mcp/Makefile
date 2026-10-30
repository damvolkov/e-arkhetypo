##### CONFIG #####
PROJECT    ?= e-mcp
PACKAGE    ?= src/e_mcp
MODULE     ?= e_mcp
PORT       ?= 45200
COMPOSE    ?= compose.yml
COMMON_SRC  ?= ../common/src/e_infra
COMMON_ROOT ?= ../common
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
.PHONY: help install sync lock common common-check lint type arch validate harden hooks test cov check ci run up down build logs release ci-vars clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · ruff · ty · tach · pytest · docker — infra/ops/adapters materialized from $(COMMON_SRC)$(RESET)\n\n"
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

common: ## materialize shared infra/ + ops/ + adapters/ from projects/python/common (source of truth) via a structural rewrite, and the shared root files into the project root
	@uv run python scripts/materialize.py
	@cp $(COMMON_ROOT)/prek.toml prek.toml
	@cp $(COMMON_ROOT)/.gitattributes .gitattributes
	@cp $(COMMON_ROOT)/.python-version .python-version
	@cp $(COMMON_ROOT)/.github/dependabot.yml .github/dependabot.yml
	@cp $(COMMON_ROOT)/.github/CODEOWNERS .github/CODEOWNERS

common-check: ## fail if the materialized common/ops/adapters or the shared root files drifted from projects/python/common
	@uv run python scripts/materialize.py --check
	@diff $(COMMON_ROOT)/prek.toml prek.toml \
	 && diff $(COMMON_ROOT)/.gitattributes .gitattributes \
	 && diff $(COMMON_ROOT)/.python-version .python-version \
	 && diff $(COMMON_ROOT)/.github/dependabot.yml .github/dependabot.yml \
	 && diff $(COMMON_ROOT)/.github/CODEOWNERS .github/CODEOWNERS \
	 && printf "$(GREEN)✓ common in sync$(RESET)\n"

# — gates —
lint: ## ruff check + format
	@uv run ruff check --fix $(PACKAGE) src/infra src/ops src/adapters scripts tests
	@uv run ruff format $(PACKAGE) src/infra src/ops src/adapters scripts tests

type: ## ty type check
	@uv run ty check

arch: ## tach architecture check
	@uv run tach check

validate: ## validate pyproject
	@uv run validate-pyproject pyproject.toml

harden: ## zizmor audit of GitHub Actions workflows (templates assemble them at generation)
	@test -d .github/workflows && uv run zizmor --persona=regular .github/workflows || echo "no workflows assembled: e-taxis writes them"

hooks: ## run all pre-commit hooks on every file (ruff, ty, tach, zizmor, gitleaks)
	@uv run prek run --all-files

# — tests —
test: ## run tests [TESTARGS='-k expr']
	@uv run pytest tests $(TESTARGS) -n auto -q

cov: ## run tests with coverage gate (fail under 100%)
	@uv run pytest tests --cov --cov-report=term-missing

# — aggregate —
check: lint type arch validate common-check test ## fast local gate: lint + type + arch + validate + drift + test
ci: lint type arch validate harden common-check cov ## every CI gate in one command

# — run —
run: ## serve the MCP app on loopback (granian factory) [args: forwarded]
	@uv run python -m $(MODULE) $(ARGS)

up: common ## docker compose up (materializes common into the build context first) [args: services]
	@docker compose -f $(COMPOSE) up -d $(ARGS)
	@printf "$(GREEN)✓ up$(RESET) $(GRAY)http://localhost:$(PORT)/mcp$(RESET)\n"

down: ## docker compose down
	@docker compose -f $(COMPOSE) down

build: common ## docker image build [args: services]
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

clean: ## remove caches + build artifacts + materialized common
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache site src/infra src/ops src/adapters prek.toml .gitattributes .python-version
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
