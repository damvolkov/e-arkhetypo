# tools/organon

[e-organon](https://github.com/damvolkov/e-organon): the house's canonical deterministic tools — `POST /<section>/<word>`,
streamed (`Accept: text/event-stream`) or batched, and the same tools over MCP at `/mcp` — plus the `tekton/` bridge
the Discord #tekton channel drives Claude Code through. No model inside: the engines do the work.

| Piece | What |
|---|---|
| `compose.yml` | the public image, host network, :45190 |
| `organon.service` | the systemd user unit |
| `profiles.yaml` | the tekton bridge's permission book (mounted read-only; restart to reread) |

## State

| Where | What |
|---|---|
| `/data` ← `../data/eorganon` | its own data, one subtree per section (`doc/`, `image/`, `tekton/` …): models, caches, the ledger — downloaded once by each section's startup |
| `<vault>/workflow/organon` | the outbox: every file a tool writes, named by its content, inside an allowed root so it is the next tool's input |
| `~/.claude`, the workspaces, the toolchains | what the bridge needs to run Claude Code as the owner, at their host paths |

Secrets (`CRYPTO__SECRET`, `AUTH_SECRET`, `POSTGRES_DSN`, `GH_TOKEN`) live in `ORGANON_ENV_FILE`, outside the form.
Keys for callers: `docker exec eorganon python -m e_organon admin` (the admin's), then `POST /auth/accounts/{name}/token`.

## Up

```bash
cp .env.example .env && mkdir -p ../data/eorganon
docker compose up -d --wait
install -m 644 organon.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable organon
```
