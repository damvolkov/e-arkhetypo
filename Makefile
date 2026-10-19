##### CONFIG #####
SYSTEMS  ?= systems/core systems/api systems/graph systems/mcp systems/cli systems/tui
TOOL     ?= management
ARGS      = $(filter-out $@,$(MAKECMDGOALS))

RESET   := \033[0m
BOLD    := \033[1m
GREEN   := \033[0;32m
CYAN    := \033[0;36m
GRAY    := \033[0;90m

SHELL := bash
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

##### TARGETS #####
.PHONY: help install update drift manage maintain maintain-check stack-versions health check clean

help:
	@printf "$(BOLD)$(CYAN)e-templates$(RESET) $(GRAY)· systems of boilerplates + management tool$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-14s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

install: ## sync every project (systems + tool)
	@for p in $(SYSTEMS) $(TOOL); do uv sync --project $$p; done
	@printf "$(GREEN)✓ all projects synced$(RESET)\n"

update: ## re-materialize systems/api from its sources (core/ops + common)
	@$(MAKE) -C systems/api core common
	@$(MAKE) -C systems/api core-check common-check

drift: ## report materialized drift across the whole ecosystem
	@uv run --project $(TOOL) python -m e_management drift

manage: ## open the Textual boilerplate wizard
	@uv run --project $(TOOL) python -m e_management

maintain: ## assemble every .github from infra/ — the systems' and the repo's own
	@uv run --project $(TOOL) python -m e_management infra
	@uv run --project $(TOOL) python -m e_management repo-infra

maintain-check: ## fail if any assembled CI drifted from infra/ or its reference
	@uv run --project $(TOOL) python -m e_management infra-check
	@uv run --project $(TOOL) python -m e_management repo-infra-check

stack-versions: ## resolve every floating stack tag to its current digest (the ledger)
	@uv run --no-project python tools/stack_resolve.py --output stack/stack.versions.yml

health: ## the three-area dependency health report: stack · systems · infra
	@uv run --no-project python tools/repo_health.py --root . --output /tmp/repo-health.md --token "$$(gh auth token 2>/dev/null || true)"; \
		STATUS=$$?; cat /tmp/repo-health.md; [ $$STATUS -le 3 ] || exit $$STATUS

check: ## run the fast gate of every project
	@for p in $(SYSTEMS) $(TOOL); do printf "$(BOLD)$(p)$(RESET)\n"; $(MAKE) -C $$p check || exit 1; done

clean: ## clean caches and artifacts everywhere
	@for p in $(SYSTEMS) $(TOOL); do $(MAKE) -C $$p clean; done
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
