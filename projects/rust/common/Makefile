##### CONFIG #####
ARGS  = $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
LINTS = -D warnings -W clippy::pedantic -D clippy::unwrap_used -D clippy::expect_used -D clippy::dbg_macro -D clippy::print_stdout -F unsafe_code

RESET := \033[0m
BOLD  := \033[1m
GREEN := \033[0;32m
CYAN  := \033[0;36m
GRAY  := \033[0;90m

SHELL := bash
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

##### TARGETS #####
.PHONY: help install fmt lint test deny check build run install-bin fold release clean

help:
	@printf "$(BOLD)$(CYAN)$$(cargo pkgid 2>/dev/null | sed 's|.*/||; s|#.*||')$(RESET) $(GRAY)· cargo · rustfmt · clippy · cargo-deny · prek$(RESET)\n\n"
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]*:.*##/{printf "  $(GREEN)%-12s$(RESET) $(GRAY)%s$(RESET)\n",$$1,$$2}' $(MAKEFILE_LIST)

install: ## toolchain, cargo-deny and the git hooks
	@rustup show active-toolchain >/dev/null
	@command -v cargo-deny >/dev/null || cargo install --locked cargo-deny
	@prek install

fmt: ## format every file
	@cargo fmt --all

lint: ## rustfmt check and clippy with the house lints
	@cargo fmt --all -- --check
	@cargo clippy --all-targets --all-features --locked -- $(LINTS)

test: ## every test
	@cargo test --all-targets --all-features --locked $(ARGS)

deny: ## advisories, licenses, bans, sources
	@cargo deny check

check: lint test deny ## the full gate, as CI runs it

build: ## release build
	@cargo build --release --locked

run: ## run the binary: make run -- <args>
	@cargo run --release -- $(ARGS)

install-bin: ## install the binary into ~/.cargo/bin from this checkout
	@cargo install --locked --path .

fold: ## fold .changelog.d fragments into CHANGELOG.md under the Cargo.toml version (in the version-bump PR)
	@v=$$(cargo pkgid | sed 's/.*[#@]//'); frags=$$(ls .changelog.d/*.md | grep -v README.md); \
	[ -n "$$frags" ] || { echo "no fragments to fold" >&2; exit 1; }; \
	{ printf '# Changelog\n\n## [%s] - %s\n\n' "$$v" "$$(date +%F)"; cat $$frags; printf '\n'; \
	  [ -f CHANGELOG.md ] && sed '1{/^# Changelog$$/d}' CHANGELOG.md | sed '1{/^$$/d}'; } > CHANGELOG.md.new; \
	mv CHANGELOG.md.new CHANGELOG.md; git rm -q $$frags; git add CHANGELOG.md; \
	echo "folded into $$v: commit with CHANGELOG_FOLD=1"

release: ## tag v<Cargo.toml version> on a clean main equal to origin: CI builds the GitHub Release and publishes the crate
	@v=$$(cargo pkgid | sed 's/.*[#@]//'); \
	[ "$$(git branch --show-current)" = main ] || { echo "release from main" >&2; exit 1; }; \
	git diff --quiet HEAD && git fetch -q origin main && [ "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" ] || { echo "main must be clean and equal to origin/main" >&2; exit 1; }; \
	grep -q "^## \[$$v\]" CHANGELOG.md || { echo "CHANGELOG.md has no [$$v]: make fold in the bump PR" >&2; exit 1; }; \
	git tag -a "v$$v" -m "v$$v" && git push origin "v$$v"

clean: ## remove build artifacts
	@cargo clean

%:
	@:
