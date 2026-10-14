# agent/openhuman

OpenHuman (the polymath assistant) as a compose: its core, its own UI, and its memory (`mem/cortexdb`, included).
No desktop binary: the UI is the app's React build served on loopback, opened as an app window by `openhuman-ui`.

| Service | What | Where |
|---|---|---|
| `openhuman` | the core, built from source with the desktop product's features | `127.0.0.1:7788` (host network) |
| `openhuman-ui` | the app's UI, seeded with the core's connection | `127.0.0.1:1420` |
| `cortexdb` · `cortexdb-mirror` | memory engine, and its graph mirrored into the vault | `mem/cortexdb` |

## The vault: one shared volume

| Folder | Written by | The core |
|---|---|---|
| `wiki/` | you, by hand | reads (`:ro`) |
| `persona/` | your config tooling | reads (`:ro`) |
| `brain/` | `cortexdb-mirror` | reads (`:ro`); never a memory source |
| `inbox/` | you; `vault-ingest` converts drops into `inbox/docs/` | writes |
| `workflow/` | the flows | writes |

Every host path is mounted at the same path inside (parity), so `config.toml`, symlinks and venvs need no
rewriting, and the core runs as the vault's user — nothing is ever chowned.

## Up

```bash
cp .env.example .env && chmod 600 .env        # fill HOST_USER, HOST_HOME, tokens
./build.sh ~/src/openhuman                     # openhuman-core + openhuman-ui
docker compose up -d --wait
install -m 755 openhuman-ui ~/.local/bin/ && cp openhuman.desktop ~/.local/share/applications/
```

`vault-ingest/` is the inbox converter (Docling): script to `~/.local/bin`, units to `~/.config/systemd/user`.

## Gotchas (each cost a debugging session)

- Build the core with the product features: the contributor default lacks `voice`, `web3`, `runtime-node`… and a
  desktop-made config then declares tools the binary does not have — every agent turn is refused.
- The base image pins `OPENHUMAN_WORKSPACE`; the house layer unsets it, or the core skips `active_user.toml` and
  boots signed out on an empty config.
- Run as the host user (`user:`): as root the entrypoint chowns the bind-mounted state to its own uid.
- The keyring is the file backend (`dev-keychain.json`) the desktop already wrote: no secret migration.
- Never run the desktop app beside it: both serve `127.0.0.1:7788` and share the workspace.
