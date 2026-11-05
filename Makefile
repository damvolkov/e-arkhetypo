##### CONFIG #####
PROJECTS ?= projects/python/common projects/python/api projects/python/graph projects/python/cli projects/python/tui
ARGS      = $(filter-out $@,$(MAKECMDGOALS))
TAXIS    ?= ../e-taxis

RESET   := \033[0m
BOLD    := \033[1m
GREEN   := \033[0;32m
CYAN    := \033[0;36m
GRAY    := \033[0;90m

SHELL := bash
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

##### TARGETS #####
.PHONY: help install update stack-versions health test check clean taxis

help:
	@printf "$(BOLD)$(CYAN)e-arkhetypo$(RESET) $(GRAY)· project blueprints, stacks and CI sources$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-14s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

install: ## sync every project
	@for p in $(PROJECTS); do uv sync --project $$p; done
	@printf "$(GREEN)✓ all projects synced$(RESET)\n"

update: ## re-materialize projects/python/api from projects/python/common (its six sections + shared root files)
	@$(MAKE) -C projects/python/api common
	@$(MAKE) -C projects/python/api common-check

stack-versions: ## resolve every floating stack tag to its current digest (the ledger)
	@uv run --no-project python .github/tools/stack_resolve.py --output stack/stack.versions.yml

health: ## the three-area dependency health report: stack · projects · infra
	@uv run --no-project python .github/tools/repo_health.py --root . --output /tmp/repo-health.md --token "$$(gh auth token 2>/dev/null || true)"; \
		STATUS=$$?; cat /tmp/repo-health.md; [ $$STATUS -le 3 ] || exit $$STATUS

test: ## unit tests of the CI tools and the shared hooks (infra/files/tools, projects/python/common/prek.toml)
	@PYTHONPATH=infra/files/tools uv run --no-project --with pytest --with pytest-asyncio pytest -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function -q tests

check: test ## run the tool tests, then the fast gate of every project
	@for p in $(PROJECTS); do printf "$(BOLD)$(p)$(RESET)\n"; $(MAKE) -C $$p check || exit 1; done

clean: ## clean caches and artifacts everywhere
	@for p in $(PROJECTS); do $(MAKE) -C $$p clean; done
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:

taxis: ## put the taxis CLI on the PATH, editable from the e-taxis checkout (TAXIS=../e-taxis)
	@uv tool install --force --editable $(TAXIS)
	@taxis --version

