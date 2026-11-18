# rust/common

The shared spine of every e-stack Rust crate: copied verbatim into the project root, never written in place there.

| file | role |
|---|---|
| `rust-toolchain.toml` | the pinned toolchain, rustfmt and clippy |
| `rustfmt.toml` | formatting |
| `Makefile` | `install fmt lint test deny check build run install-bin fold release clean`; the house lints live in `LINTS`; `fold` + `release` are the PyPI-like flow: fragments → CHANGELOG in the bump PR, then a `v*` tag CI turns into a GitHub Release and a crates.io publish |
| `deny.toml` | advisories, license allow-list, bans, sources |
| `prek.toml` | branch guard, fmt, clippy, test, deny, changelog, gitleaks |
| `.github/workflows/ci.yml` | `make check` on push and PR |
| `.github/dependabot.yml` · `.github/CODEOWNERS` | upkeep and ownership |
| `.changelog.d/README.md` · `.gitattributes` · `.gitignore` | the record and the repo hygiene |

The house lints: warnings denied, clippy pedantic, no `unwrap`/`expect`/`dbg!`/`println!`, `unsafe` forbidden.
A crate adds only what is its own: `Cargo.toml`, `src/`, `tests/`, its release workflow.
