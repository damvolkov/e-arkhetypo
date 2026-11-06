### stack

- Secrets leave the stacks' working folders for `~/.config/secrets/<owner>/` (mode 700/600). `agent/hermes` mounts
  `HERMES_SECRETS_DIR` read-only as Hermes' managed layer (`/etc/hermes/.env`, pinned over the vault's `.env`, which
  keeps only the non-secret settings the e-nous render writes — Hermes rewrites its `.env` by atomic rename, so a file
  mount would break it). `tools/organon` mounts `ORGANON_PKI_DIR` read-only at `/run/secrets/pki` for `doc/sign`. The
  `.env.example` files of organon, egnosis and hermes point at the new paths. Live on the host: Discord connected,
  model and organon calls authenticated from the managed layer.
