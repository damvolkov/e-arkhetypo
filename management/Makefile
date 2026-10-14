##### CONFIG #####
PROJECT    ?= e-management
PACKAGE    ?= src/e_management
CORE_SRC ?= ../systems/core/src/e_core
OPS_AREA  = $(CORE_SRC)/ops
ARGS     = $(filter-out $@,$(MAKECMDGOALS))

RESET   := \033[0m
BOLD    := \033[1m
GREEN   := \033[0;32m
CYAN    := \033[0;36m
GRAY    := \033[0;90m

SHELL := bash
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

##### TARGETS #####
.PHONY: help install sync lock ops ops-check lint type arch validate test cov check plan gen drift graph graph-check map stack stack-check clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · ruff · ty · tach · pytest — internal tool: boilerplate engine over systems/$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-9s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

# — env —
install: ops ## materialize ops/tui + sync deps
	@uv sync
	@printf "$(GREEN)✓ ready$(RESET)\n"

sync: ## sync all deps (main + dev)
	@uv sync

lock: ## refresh uv lockfile
	@uv lock

# — common —
ops: ## materialize the whole common ops area (file parser + tui) from systems/core
	@rm -rf src/ops
	@mkdir -p src/ops
	@cp $(OPS_AREA)/*.py src/ops/
	@sed -i -e 's/e_core\.ops\b/ops/g' -e 's/e_core\.core\b/core/g' src/ops/*.py

ops-check: ## fail if any materialized ops file drifted from its source
	@for f in $(OPS_AREA)/*.py; do \
		bn=$$(basename $$f); \
		sed -e 's/e_core\.ops\b/ops/g' -e 's/e_core\.core\b/core/g' $$f | diff -q - src/ops/$$bn >/dev/null || { echo "✗ ops/$$bn drifted"; exit 1; }; \
	done; printf "$(GREEN)✓ ops in sync$(RESET)\n"

# — gates —
lint: ## ruff check + format
	@uv run ruff check --fix $(PACKAGE) tests
	@uv run ruff format $(PACKAGE) tests

type: ## ty type check
	@uv run ty check

arch: ## enforce import architecture (tach)
	@uv run tach check

validate: ## validate pyproject.toml against schema
	@uv run validate-pyproject pyproject.toml

# — tests —
test: ## run tests [TESTARGS='-k expr']
	@uv run pytest tests $(TESTARGS) -n auto -q

cov: ## run tests with coverage gate (fail under 90%)
	@uv run pytest tests --cov --cov-report=term-missing

# — aggregate —
check: lint type arch validate ops-check graph-check stack-check test ## fast local gate: lint · type · arch · validate · drift · graph · stack · test

# — tool —
plan: ## show the generation plan: make plan T=api N=myapp [OFF=websockets]
	@uv run python -m e_management plan $(T) $(N) --off $(OFF)

gen: ## generate a project: make gen T=api N=myapp DEST=../myapp [OFF=websockets]
	@uv run python -m e_management gen $(T) $(N) --dest $(DEST) --off $(OFF)

drift: ## report materialized drift for every system
	@uv run python -m e_management drift

graph: ## (re)generate every system's dependency lock from its sources
	@uv run python -m e_management graph

graph-check: ## fail if any committed dependency lock drifted from its sources
	@uv run python -m e_management graph-check

map: ## render the dependency map of every system to a temp HTML and open the browser
	@uv run python -m e_management map

clean: ## remove caches + build artifacts
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache src/ops
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
