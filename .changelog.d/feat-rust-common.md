- `frozen-templates` follows the widened doctrine (e-nous #166): in `projects/` only `projects/<language>/common`
  changes; `infra/`, `stack/`, the registry and a language's README are open. Tests: 5 new cases (rust common allowed,
  rust template blocked, registry, language README, infra); `make test` 31 passed.
- `projects/rust/common`: the first Rust spine — pinned toolchain 1.94.0, rustfmt, house lints in the Makefile
  (`-D warnings`, clippy pedantic, no unwrap/expect/dbg/print, `unsafe` forbidden), cargo-deny, prek (branch guard,
  fmt, clippy, test, deny, changelog, gitleaks), CI `make check`, dependabot (cargo + actions), CODEOWNERS,
  `.changelog.d`. Proven by materializing it into edamlabs/e-procs: `make check` green there.
