#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# strata setup — builds the engine image, serves the model, pins the slot alias.
# Run once on a fresh machine; the model itself (~68 GB for IQ2_XS) downloads
# inside the container on first start and lives in the strata-data volume.
#
# Requirements:
#   - Docker with the NVIDIA Container Toolkit, driver >= 580
#   - ~3 min of build (nvcc + 32 cores) and a clean python-free host: nothing
#     is installed on the host, everything is inside the image.
#
# Hardware target (measured 2026-10-14, RTX 4090 / i9-14900K / 188 GB):
#   - GPU: NVIDIA 12-24 GB (sm_75..sm_120); RAM >= 48 GB (IQ2_XS) or >= 88 GB
#     (UD-Q4_K_XL via STRATA_FAMILY=unsloth STRATA_MODEL=UD-Q4_K_XL in .env)
#   - Disk: >= 120 GB free for the volume; NVMe strongly preferred
#
# Usage:
#   chmod +x setup.sh && ./setup.sh
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

##### CONFIGURATION #####

COMPOSE_BASE="${HOME}/.config/compose"
SERVICE_NAME="strata"
SERVICE_DIR="${COMPOSE_BASE}/${SERVICE_NAME}"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
STRATA_TAG="v0.1.44.1"
STRATA_REPO="https://github.com/Niko1221/Strata"
MODEL="${STRATA_MODEL:-IQ2_XS}"
FAMILY="${STRATA_FAMILY:-qwen}"
API_KEY="${LLM_API_KEY:-local-dev}"
ALIAS="demian-model"
HEALTH_URL="http://localhost:8000/health"

##### MAIN #####

log() { echo "[strata-setup] $1"; }

# 1. build the image on this PC (native CPU code, CUDA arch from the card)
ARCH=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '.')
log "building strata:${STRATA_TAG#v} for sm_${ARCH}..."
SRC="$(mktemp -d)"
trap 'rm -rf "$SRC"' EXIT
git clone -q --depth 1 --branch "$STRATA_TAG" "$STRATA_REPO" "$SRC"
docker build -q -t "strata:${STRATA_TAG#v}" --build-arg "CUDA_ARCHITECTURES=${ARCH}" "$SRC"

# 2. deploy the service dir + unit (compose from this folder, .env pins the pack).
#    No ExecStartPre pull: the image is built here, it is not on a registry.
mkdir -p "$SERVICE_DIR" "$SYSTEMD_DIR"
cp "$(dirname "$0")/compose.yml" "${SERVICE_DIR}/compose.yml"
grep -q '^STRATA_FAMILY=' "${SERVICE_DIR}/.env" 2>/dev/null || \
    printf 'STRATA_FAMILY=%s\nSTRATA_MODEL=%s\n' "$FAMILY" "$MODEL" >> "${SERVICE_DIR}/.env"
cat > "${SYSTEMD_DIR}/${SERVICE_NAME}.service" << EOF
[Unit]
Description=${SERVICE_NAME} via Docker Compose

[Service]
Type=simple
WorkingDirectory=${SERVICE_DIR}
ExecStart=/usr/bin/docker compose up --remove-orphans
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose up -d --remove-orphans
Restart=on-failure
RestartSec=10s
TimeoutStartSec=900
TimeoutStopSec=90

[Install]
WantedBy=default.target
EOF

# 3. first start: setup downloads ~68 GB into the volume, packs, then serves.
#    The unit's healthcheck (image HEALTHCHECK, start_period 600 s) stays red
#    while it downloads — normal, do not restart.
systemctl --user daemon-reload && systemctl --user enable --now "${SERVICE_NAME}.service"

log "waiting for the model to load (download + pack can take ~1 h)..."
until curl -sf "$HEALTH_URL" >/dev/null 2>&1; do sleep 30; done

# 4. pin the slot alias: /data/config/strata-<model>.json gains `"aliases": ["demian-model"]`
#    (REINSTALL=1 rewrites the config — re-run this step after it).
log "adding alias ${ALIAS}..."
docker exec "$SERVICE_NAME" python3 - "$MODEL" "$ALIAS" <<'EOF'
import json, sys
cfg = f"/data/config/strata-{sys.argv[1].lower()}.json"
d = json.load(open(cfg)); d["aliases"] = [sys.argv[2]]
json.dump(d, open(cfg, "w"), indent=1)
EOF
docker restart "$SERVICE_NAME"
until curl -sf "$HEALTH_URL" >/dev/null 2>&1; do sleep 5; done

# 5. verify the slot answers under its stable name
curl -sf http://localhost:8000/v1/chat/completions -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${ALIAS}\",\"messages\":[{\"role\":\"user\",\"content\":\"responde solo: listo\"}],\"max_tokens\":16,\"reasoning_effort\":\"off\"}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('[strata-setup] OK:', d['model'], '->', d['choices'][0]['message']['content'].strip()[:40])"
