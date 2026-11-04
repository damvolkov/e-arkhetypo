# tools/jsoncrack

[JSON Crack](https://github.com/AykutSarac/jsoncrack.com) (Apache-2.0): JSON, YAML, XML and CSV as an interactive
graph, with validation, formatting, querying and type generation. A static build served by nginx; everything runs in
the browser — no model, nothing leaves the host.

| Piece | What |
|---|---|
| `compose.yml` | built from a pinned upstream commit (no published image; the v5.0.0 tag's Docker build is broken) |
| `nginx.conf` | upstream's routes plus `/data/`, the drop folder, read-only |
| `jsoncrack` | CLI: `jsoncrack <file\|->` drops the document and prints (and opens) its editor URL |
| `jsoncrack.service` | the systemd user unit |

## Calling it

A document in the drop folder (`JSONCRACK_DATA`, by default `<vault>/workflow/jsoncrack`) is served at
`/data/<name>`; `/editor?json=<that URL>` loads it from the same origin. Anything that can write the folder can hand
out a link — `jsoncrack` on the host, Hermes from its container (it writes `workflow/`). Files are named by the
first 12 hex of their SHA-256, so the same content keeps its URL.

## Up

```bash
cp .env.example .env
docker compose build && docker compose up -d --wait           # http://127.0.0.1:45840/editor
install -m 755 jsoncrack ~/.local/bin/
install -m 644 jsoncrack.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now jsoncrack
```
