# agent/hermes

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT) as the assistant's runtime: Discord gateway with
voice (notes and voice channels), MCP client, cron, skills, and its web dashboard. Replaced `agent/openhuman`.

| Piece | What | Where |
|---|---|---|
| `hermes` | gateway + dashboard, supervised by s6 inside one container | dashboard `127.0.0.1:9119` (host network) |
| `Dockerfile` | house layer: `libopus0` (the image ships none; voice-channel playback needs it) | `hermes-agent:house` |
| `hermes.service` | the systemd user unit (`~/.config/systemd/user/`) | `systemctl --user enable --now hermes` |

## The vault

| Folder | Hermes |
|---|---|
| `hermes/` | its state at `/opt/data`: `config.yaml`, `.env` (its secrets), sessions, skills, plugins, `bin/` |
| `inbox/` · `workflow/` | writes (the `intake` plugin leaves its notes in `inbox/docs`) |
| `persona/` · `wiki/` · `brain/` | reads (`:ro`) |

Every folder is mounted at its host path, so a path in a note or a tool call is the same inside and out.

## Pin

The one exception to the stack's `:latest` rule: Hermes releases almost daily and the house layer would never be
rebuilt by `update.sh`. `HERMES_IMAGE` is pinned by digest in `compose.yml`; moving it is a hand step — bump,
`docker compose build`, `systemctl --user reload hermes`.

## Up

```bash
cp .env.example .env
docker compose build && docker compose up -d --wait
install -m 644 hermes.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable hermes
docker exec hermes hermes config set model.provider <provider>   # then its secrets in <vault>/hermes/.env
```

The configuration the house runs (models, voice, MCP, plugins) is not a form: it lives in e-nous,
`core/nomos/config/hermes/`.
