##### CONFIG #####
PROJECT    ?= e-management
PACKAGE    ?= src/e_management
CORE_SRC ?= ../systems/core/src/e_core
OPS_AREA  = $(CORE_SRC)/ops
TUI_SRC   ?= ../systems/tui/src/e_tui
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
.PHONY: help install sync lock ops ops-check ui ui-check lint type arch validate test cov check plan gen drift graph graph-check infra-check map stack stack-check clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · ruff · ty · tach · pytest — internal tool: boilerplate engine over systems/$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-9s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

# — env —
install: ops ui ## materialize ops + the tui flow + sync deps
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

ui: ## materialize the tui flow framework (app, flow, interact, layout, models, templates) from systems/tui
	@rm -rf src/e_tui
	@cp -r $(TUI_SRC) src/e_tui
	@rm -rf src/e_tui/demo.py src/e_tui/__main__.py src/e_tui/pages src/e_tui/__pycache__
	@find src/e_tui -name __pycache__ -type d -exec rm -rf {} +
	@sed -i 's/^from core\./from e_core.core./' src/e_tui/flow/state.py src/e_tui/flow/pages.py src/e_tui/layout/render.py

ui-check: ## fail if the vendored tui drifted from systems/tui
	@for f in app.py flow/*.py interact/*.py layout/*.py models/*.py templates/*.py; do \
		bn=$$(basename $$f); srcdir=$$(dirname $$f); \
		case "$$srcdir" in app.py|"") src=$(TUI_SRC)/$$bn ;; *) src=$(TUI_SRC)/$$srcdir/$$bn ;; esac; \
		[ -f "$$src" ] || continue; \
		sed 's/^from core\./from e_core.core./' $$src | diff -q - src/e_tui/$$srcdir/$$bn >/dev/null || { echo "✗ e_tui/$$srcdir/$$bn drifted"; exit 1; }; \
	done; printf "$(GREEN)✓ e_tui in sync$(RESET)\n"

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
check: lint type arch validate ops-check ui-check graph-check stack-check infra-check test ## fast local gate: lint · type · arch · validate · drift · ui · graph · stack · infra · test

# — tool —
plan: ## show the generation plan: make plan T=api N=myapp [OFF=websockets]
	@uv run python -m e_management plan $(T) $(N) --off $(OFF) --ci-off $(CIOFF)

gen: ## generate a project: make gen T=api N=myapp DEST=../myapp [OFF=websockets]
	@uv run python -m e_management gen $(T) $(N) --dest $(DEST) --off $(OFF) --ci-off $(CIOFF)

drift: ## report materialized drift for every system
	@uv run python -m e_management drift

graph: ## (re)generate every system's dependency lock from its sources
	@uv run python -m e_management graph

graph-check: ## fail if any committed dependency lock drifted from its sources
	@uv run python -m e_management graph-check

infra-check: ## fail if a system's CI reference no longer assembles against infra/
	@uv run python -m e_management infra-check

map: ## render the dependency map of every system to a temp HTML and open the browser
	@uv run python -m e_management map

clean: ## remove caches + build artifacts
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache src/ops src/e_tui
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
