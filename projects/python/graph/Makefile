##### CONFIG #####
PROJECT  ?= e-graph
PACKAGE  ?= src/e_graph
MODULE   ?= e_graph
PORT     ?= 8000
COMPOSE  ?= compose.yml
COMMON_SRC ?= ../common/src/e_infra
UI       ?= src/e_graph/ui
TESTARGS  ?= -m "not ui and not integration"   ## visual goldens are runner-canonical (make snap-refresh owns them); the model's cassettes leave the gate: make integration
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
.PHONY: help install sync lock common common-check lint type arch validate harden hooks test integration cov record conversions dartsops dartsops-eval dartsops-gate stress docs docs-build bundle snap check ci serve up down build logs release ci-vars clean

help:
	@printf "$(BOLD)$(CYAN)$(PROJECT)$(RESET) $(GRAY)· uv · ruff · ty · tach · pytest · zensical · docker · pnpm — infra/ops/ports/providers/engines/processors materialized from $(COMMON_SRC)$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-12s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

# — env —
install: common ## full setup: materialize shared assets + sync deps + ui deps + chromium + git hooks
	@uv sync
	@pnpm -C $(UI) install --frozen-lockfile
	@uv run playwright install chromium
	@uv run prek install
	@printf "$(GREEN)✓ ready$(RESET)\n"

sync: ## sync all deps (main + dev)
	@uv sync

lock: common ## refresh uv lockfile (against the current materialized common)
	@uv lock

### a file target: made once when missing, never overwritten — the dev crypto secret, random per machine, gitignored.
.env:
	@uv run python -c "import sys; from ops.crypto import Crypto; sys.stdout.write(f'SECRET={Crypto.generate_keys().secret.get_secret_value()}\\n')" > $@
	@printf "$(GREEN)✓ .env$(RESET) $(GRAY)dev secret generated — see .env.example for every other knob$(RESET)\n"

# — common —
COMMON_ROOT ?= ../common

common: ## materialize the shared sections (engines, infra, ops, ports, processors, providers) from projects/python/common (source of truth) via a structural rewrite, and the shared root files into the project root
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
lint: ## ruff check + format, biome check + format on the ui
	@uv run ruff check --fix $(PACKAGE) src/infra src/ops src/ports src/providers src/engines src/processors scripts tests
	@uv run ruff format $(PACKAGE) src/infra src/ops src/ports src/providers src/engines src/processors scripts tests
	@pnpm -C $(UI) fix

type: ## ty type check, tsc on the ui
	@uv run ty check
	@pnpm -C $(UI) exec tsc -b

arch: ## enforce import architecture (tach)
	@uv run tach check

validate: ## validate pyproject.toml against schema
	@uv run validate-pyproject pyproject.toml

harden: ## zizmor audit of GitHub Actions workflows (templates assemble them at generation)
	@test -d .github/workflows && uv run zizmor --persona=regular .github/workflows || echo "no workflows assembled: e-taxis writes them"

hooks: ## run all prek hooks on every file (ruff, ty, tach, zizmor, gitleaks)
	@uv run prek run --all-files

# — tests —
test: bundle ## run tests, visual goldens and model cassettes out by default (the canvas is still built) [TESTARGS='-k expr']
	@uv run pytest tests $(TESTARGS) -n auto -q

integration: ## replay the agent's recorded cassettes (the tests that need a real model: make record re-records them)
	@uv run pytest tests -m integration -q

cov: bundle ## run tests with coverage gate (fail under 100%), goldens and cassettes out like test
	@uv run pytest tests $(TESTARGS) --cov --cov-report=term-missing

snap: bundle ## accept the canvas snapshots after a reviewed visual change (rewrites __snapshots__ PNGs)
	@uv run pytest tests/acceptance -m ui --snapshot-update -q

record: ## re-record the agent's integration cassettes against the live model (AGENT_MEDIUM, else the local vLLM; its key from VLLM_API_KEY)
	@uv run pytest tests/integration -q -p no:randomly -p no:xdist --record-mode=rewrite

conversions: ## re-record the corpus spans through the live docling-serve into tests/resources/conversions (golden, gzipped)
	@uv run python scripts/conversions.py

stress: ## soak stress-marked tests for ARGS seconds (pytest-stress)
	@uv run pytest tests -m stress -q -p no:randomly --seconds $(or $(ARGS),30)

# — docs —
docs: ## serve the project docs site live at :8001 (the app owns :8000)
	@uv run zensical serve --dev-addr 127.0.0.1:8001

docs-build: ## strict docs build to site/
	@uv run zensical build --strict

# — ui —
bundle: ## build the canvas into src/e_graph/ui/dist — the static page the app serves at /
	@pnpm -C $(UI) build

# — dartsops —
dartsops: ## Show the maintenance workflow: its contract, the laws, and the gates a run must pass
	@uv run e-graph darts contract --out src/e_graph/.coder/workflows/dartsops/contract.json
	@printf "$(BOLD)$(CYAN)dartsops$(RESET) $(GRAY)· workflow in src/e_graph/.coder/workflows/dartsops/ · contract refreshed · probe tiers next$(RESET)\n"
	@uv run e-graph darts probe

dartsops-eval: ## Run a pipeline's readout over its seed: make dartsops-eval PIPELINE=note EXPECTS="…" DATA="source=…"
	@uv run e-graph darts evaluate $(PIPELINE) --data $(DATA) $(addprefix --expect ,$(EXPECTS)) --out signal.json

dartsops-gate: ## The deterministic wall a craft must pass: laws, plan pins, taxonomy, the pipeline's unit tests
	@uv run e-graph darts check
	@uv run pytest tests/unit/e_graph/pipelines/$(or $(PIPELINE),note) tests/unit/e_graph/test_taxonomy.py tests/unit/e_graph/logic/orchestrator/test_plan.py -q -p no:randomly

# — aggregate —
check: lint type arch validate common-check test ## fast local gate: lint + type + arch + validate + drift + test (ui included)
ci: lint type arch validate harden common-check bundle docs-build cov ## full pipeline: every gate CI runs, in one command

# — release —
release: ## cut a GitHub release via the release workflow [args: patch|minor|major]
	@gh workflow run release.yml -f bump=$(or $(ARGS),patch)
	@sleep 5
	@gh run watch --exit-status $$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')

ci-vars: ## list optional CI/CD gates (all inert by default) and their defaults
	@printf "$(BOLD)optional CI/CD gates$(RESET) $(GRAY)— enable: gh variable set NAME --body true · manifest: .github/ci.vars.example$(RESET)\n\n"
	@grep -E '^[A-Z][A-Z0-9_]*=' .github/ci.vars.example

# — run —
serve: bundle .env ## the whole piece: build the canvas, start the server — api + canvas at :8000 [args: forwarded]
	@uv run python -m $(MODULE) $(ARGS)

up: common ## docker compose up (materializes common into the build context first) [args: services]
	@docker compose -f $(COMPOSE) up -d $(ARGS)
	@printf "$(GREEN)✓ up$(RESET) $(GRAY)http://localhost:$(PORT)$(RESET)\n"

down: ## docker compose down
	@docker compose -f $(COMPOSE) down

build: common ## docker image build [args: services]
	@docker compose -f $(COMPOSE) build $(ARGS)

logs: ## tail docker logs [args: service]
	@docker compose -f $(COMPOSE) logs -f $(ARGS)

clean: ## remove caches + build artifacts + materialized common
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist build *.egg-info .coverage .coverage.* .ty_cache site $(UI)/dist $(UI)/node_modules src/infra src/ops src/ports src/providers src/engines src/processors prek.toml .gitattributes .python-version
	@printf "$(GREEN)✓ clean$(RESET)\n"

%:
	@:
