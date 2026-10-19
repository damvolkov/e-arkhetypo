#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# lazydocker setup — the host's container monitor, pinned on the desktop.
# A host install, not a container: the TUI needs the user's terminal, and the
# upstream image (lazyteam/lazydocker) stopped publishing in 2022.
#
# Installs, idempotently:
#   1. the latest lazydocker release into ~/.local/bin (sha256-verified)
#   2. config.yml from this folder into ~/.config/lazydocker/
#   3. a login autostart: a small gnome-terminal titled "lazydocker"
#   4. GNOME only: Smart Auto Move, restoring ONLY that window — monitor,
#      position, size and always-on-top. Wayland lets no app place itself.
#
# Requirements: Docker, curl, gnome-terminal; GNOME Shell for step 4.
#
# Usage:
#   chmod +x setup.sh && ./setup.sh
#   then log out and in once (Wayland loads new extensions only at login),
#   place the window, Alt+Space → Always on Top: it is restored from then on.
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

##### CONFIGURATION #####

REPO="jesseduffield/lazydocker"
BIN_DIR="${HOME}/.local/bin"
CONFIG_DIR="${HOME}/.config/lazydocker"
AUTOSTART="${HOME}/.config/autostart/lazydocker.desktop"
TITLE="lazydocker"
GEOMETRY="${LAZYDOCKER_GEOMETRY:-100x20}"
EXTENSION="smart-auto-move@khimaros.com"
EXTENSION_ID="4736"

##### MAIN #####

log() { echo "[lazydocker-setup] $1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1. binary: latest release, checksum-verified, skipped when already current
VERSION=$(basename "$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/${REPO}/releases/latest")")
CURRENT=$("${BIN_DIR}/lazydocker" --version 2>/dev/null | awk '/^Version:/{print $2}' || true)
if [ "$CURRENT" = "${VERSION#v}" ]; then
    log "lazydocker ${VERSION} already installed"
else
    ASSET="lazydocker_${VERSION#v}_Linux_$(uname -m | sed 's/aarch64/arm64/').tar.gz"
    log "installing lazydocker ${VERSION}..."
    curl -fsSL -o "${TMP}/${ASSET}" "https://github.com/${REPO}/releases/download/${VERSION}/${ASSET}"
    curl -fsSL -o "${TMP}/checksums.txt" "https://github.com/${REPO}/releases/download/${VERSION}/checksums.txt"
    (cd "$TMP" && grep " ${ASSET}\$" checksums.txt | sha256sum -c --quiet -)
    tar -xzf "${TMP}/${ASSET}" -C "$TMP" lazydocker
    install -Dm755 "${TMP}/lazydocker" "${BIN_DIR}/lazydocker"
fi

# 2. config: the panel layout tuned for a narrow pinned window
install -Dm644 "$(dirname "$0")/config.yml" "${CONFIG_DIR}/config.yml"

# 3. autostart: delayed so the docker units are up when it first draws
mkdir -p "$(dirname "$AUTOSTART")"
cat > "$AUTOSTART" << EOF
[Desktop Entry]
Type=Application
Name=Docker Monitor
Exec=gnome-terminal --title=${TITLE} --geometry=${GEOMETRY} -- ${BIN_DIR}/lazydocker
X-GNOME-Autostart-Delay=20
EOF

# 4. placement: Smart Auto Move in IGNORE mode, one RESTORE override for the titled terminal
command -v gnome-shell >/dev/null || { log "no GNOME Shell: placement skipped"; log "done"; exit 0; }
SHELL_MAJOR=$(gnome-shell --version | grep -oE '[0-9]+' | head -1)
URL=$(curl -fsSL "https://extensions.gnome.org/extension-info/?pk=${EXTENSION_ID}&shell_version=${SHELL_MAJOR}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["download_url"])')
curl -fsSL -o "${TMP}/ext.zip" "https://extensions.gnome.org${URL}"
gnome-extensions install --force "${TMP}/ext.zip"
SCHEMA=(--schemadir "${HOME}/.local/share/gnome-shell/extensions/${EXTENSION}/schemas")
gsettings "${SCHEMA[@]}" set org.gnome.shell.extensions.smart-auto-move sync-mode IGNORE
gsettings "${SCHEMA[@]}" set org.gnome.shell.extensions.smart-auto-move overrides \
    "{\"Gnome-terminal\":[{\"query\":{\"title\":\"${TITLE}\"},\"action\":1}]}"
gsettings set org.gnome.shell enabled-extensions "$(gsettings get org.gnome.shell enabled-extensions \
    | python3 -c "import ast,sys; e=ast.literal_eval(sys.stdin.read().replace('@as ', '')); print(sorted({*e, '${EXTENSION}'}))")"

log "done — log out and in once, place the window, Alt+Space → Always on Top"
