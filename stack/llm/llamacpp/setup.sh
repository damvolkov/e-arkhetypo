#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# llamacpp setup — Downloads model, pulls image, deploys service.
# Run once on a fresh machine to bootstrap from zero.
#
# Requirements:
#   - Docker with NVIDIA Container Toolkit (nvidia-docker)
#   - docker network "e-core" (docker network create e-core)
#   - systemd --user enabled (loginctl enable-linger $USER)
#   - wget, curl
#
# Hardware target:
#   - GPU: NVIDIA with ≥16 GB VRAM (tested: RTX 4090 24 GB)
#   - RAM: ≥64 GB (tested: 192 GB — model uses ~50 GB total)
#   - CPU: ≥16 threads (tested: i9-14900K 32 threads)
#   - Disk: ≥60 GB free for model + image
#
# Usage:
#   chmod +x setup.sh && ./setup.sh
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

##### CONFIGURATION #####

COMPOSE_BASE="${HOME}/.config/compose"
SERVICE_NAME="llamacpp"
SERVICE_DIR="${COMPOSE_BASE}/${SERVICE_NAME}"
DATA_DIR="${COMPOSE_BASE}/data/${SERVICE_NAME}"
MODELS_DIR="${DATA_DIR}/models"
CACHE_DIR="${DATA_DIR}/cache"
SYSTEMD_DIR="${HOME}/.config/systemd/user"

MODEL_REPO="unsloth/Qwen3-Coder-Next-GGUF"
MODEL_FILE="Qwen3-Coder-Next-UD-Q4_K_XL.gguf"
MODEL_URL="https://huggingface.co/${MODEL_REPO}/resolve/main/${MODEL_FILE}"
MODEL_SIZE_BYTES=49608478720

DOCKER_IMAGE="ghcr.io/ggml-org/llama.cpp:server-cuda"
HEALTH_URL="http://localhost:45150/health"
MAX_RETRIES=60
RETRY_INTERVAL=5

##### HELPERS #####

log() { echo "[llamacpp-setup] $1"; }
err() { echo "[llamacpp-setup] ERROR: $1" >&2; exit 1; }

check_prerequisites() {
    log "checking prerequisites..."

    command -v docker >/dev/null 2>&1 || err "docker not found"
    command -v wget >/dev/null 2>&1   || err "wget not found"
    command -v curl >/dev/null 2>&1   || err "curl not found"

    docker info >/dev/null 2>&1 || err "docker daemon not running"

    if ! docker network ls --format '{{.Name}}' | grep -q '^e-core$'; then
        log "creating docker network e-core..."
        docker network create e-core
    fi

    if ! nvidia-smi >/dev/null 2>&1; then
        err "nvidia-smi not found — NVIDIA driver required"
    fi

    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
    RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
    THREADS=$(nproc)

    log "hardware: GPU ${VRAM_MB} MiB VRAM, ${RAM_GB} GB RAM, ${THREADS} threads"

    if [ "$VRAM_MB" -lt 16000 ]; then
        log "WARNING: <16 GB VRAM — model will offload heavily to CPU (slower)"
    fi
    if [ "$RAM_GB" -lt 64 ]; then
        err "insufficient RAM: need ≥64 GB, found ${RAM_GB} GB"
    fi

    DISK_FREE_GB=$(df --output=avail "${COMPOSE_BASE}" 2>/dev/null | tail -1 | awk '{printf "%d", $1/1024/1024}')
    if [ "$DISK_FREE_GB" -lt 60 ]; then
        err "insufficient disk: need ≥60 GB free, found ${DISK_FREE_GB} GB"
    fi

    log "prerequisites OK"
}

create_directories() {
    log "creating directories..."

    for dir in "$SERVICE_DIR" "$MODELS_DIR" "$CACHE_DIR"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir" 2>/dev/null || {
                log "need sudo for ${dir}"
                sudo mkdir -p "$dir"
                sudo chown -R "$(id -u):$(id -g)" "$dir"
            }
        fi
    done

    log "directories ready"
}

download_model() {
    local model_path="${MODELS_DIR}/${MODEL_FILE}"

    if [ -f "$model_path" ]; then
        local actual_size
        actual_size=$(stat --printf="%s" "$model_path")
        if [ "$actual_size" -eq "$MODEL_SIZE_BYTES" ]; then
            log "model already downloaded and verified (${MODEL_FILE})"
            return 0
        fi
        log "model file incomplete (${actual_size}/${MODEL_SIZE_BYTES}), resuming..."
    fi

    log "downloading model: ${MODEL_REPO} → ${MODEL_FILE} (46.2 GB)..."
    log "this will take several minutes depending on connection speed"

    wget -c --progress=bar:force:noscroll \
        "${MODEL_URL}" \
        -O "$model_path"

    local final_size
    final_size=$(stat --printf="%s" "$model_path")
    if [ "$final_size" -ne "$MODEL_SIZE_BYTES" ]; then
        err "download verification failed: expected ${MODEL_SIZE_BYTES}, got ${final_size}"
    fi

    log "model downloaded and verified"
}

pull_image() {
    log "pulling docker image: ${DOCKER_IMAGE}..."
    docker pull "$DOCKER_IMAGE"
    log "image ready"
}

deploy_compose() {
    local template_dir
    template_dir="$(cd "$(dirname "$0")/../.." && pwd)"
    local template_file="${template_dir}/compose.llamacpp.yml"

    if [ -f "$template_file" ]; then
        log "deploying compose from template: ${template_file}"
        cp "$template_file" "${SERVICE_DIR}/compose.yml"
    else
        log "template not found at ${template_file}, using deployed compose"
        if [ ! -f "${SERVICE_DIR}/compose.yml" ]; then
            err "no compose.yml found — run from e-core repo or copy template manually"
        fi
    fi

    log "compose deployed to ${SERVICE_DIR}/compose.yml"
}

install_systemd() {
    log "installing systemd unit..."

    mkdir -p "$SYSTEMD_DIR"

    cat > "${SYSTEMD_DIR}/${SERVICE_NAME}.service" << EOF
[Unit]
Description=${SERVICE_NAME} via Docker Compose

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${SERVICE_DIR}
ExecStart=/usr/bin/docker compose up -d --wait --remove-orphans
ExecStop=/usr/bin/docker compose stop
ExecReload=/usr/bin/docker compose up -d --wait --remove-orphans
Restart=on-failure
RestartSec=30s
TimeoutStartSec=300
TimeoutStopSec=30

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    log "systemd unit installed: ${SERVICE_NAME}.service"
}

start_service() {
    log "starting service..."
    systemctl --user enable --now "${SERVICE_NAME}.service"

    log "waiting for health check (model loading takes 30-60s)..."
    for i in $(seq 1 "$MAX_RETRIES"); do
        if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
            log "service is healthy!"
            return 0
        fi
        sleep "$RETRY_INTERVAL"
    done

    log "WARNING: service not healthy after $((MAX_RETRIES * RETRY_INTERVAL))s"
    log "check logs: docker logs ${SERVICE_NAME}"
    return 1
}

verify_service() {
    log "running verification..."

    local response
    response=$(curl -sf http://localhost:45150/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "qwen3-coder-next",
            "messages": [{"role": "user", "content": "Say hello in one sentence."}],
            "max_tokens": 32,
            "temperature": 0.1
        }' 2>/dev/null)

    if echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])" 2>/dev/null; then
        log "verification PASSED — model responding correctly"
    else
        log "WARNING: verification failed — check docker logs ${SERVICE_NAME}"
        return 1
    fi

    local timings
    timings=$(echo "$response" | python3 -c "
import sys, json
d = json.load(sys.stdin)
t = d.get('timings', {})
u = d.get('usage', {})
print(f'  prompt: {t.get(\"prompt_per_second\",0):.1f} tok/s')
print(f'  generation: {t.get(\"predicted_per_second\",0):.1f} tok/s')
print(f'  tokens: {u.get(\"total_tokens\",\"?\")}')
" 2>/dev/null)

    log "performance:"
    echo "$timings"
}

print_summary() {
    local vram_used vram_free ram_used
    vram_used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
    vram_free=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    ram_used=$(free -h | awk '/Mem:/ {print $3}')

    log "═══════════════════════════════════════════"
    log "  llamacpp setup complete"
    log "═══════════════════════════════════════════"
    log "  Model:    Qwen3-Coder-Next 80B MoE (Q4_K_XL)"
    log "  Endpoint: http://localhost:45150"
    log "  API:      OpenAI-compatible (/v1/chat/completions)"
    log "  VRAM:     ${vram_used} MiB used / ${vram_free} MiB free"
    log "  RAM:      ${ram_used} used"
    log ""
    log "  Manage:"
    log "    systemctl --user status  ${SERVICE_NAME}"
    log "    systemctl --user stop    ${SERVICE_NAME}"
    log "    systemctl --user restart ${SERVICE_NAME}"
    log "    docker logs -f ${SERVICE_NAME}"
    log ""
    log "  Test:"
    log "    curl http://localhost:45150/health"
    log "    curl http://localhost:45150/v1/chat/completions \\"
    log "      -H 'Content-Type: application/json' \\"
    log "      -d '{\"model\":\"qwen3-coder-next\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'"
    log "═══════════════════════════════════════════"
}

##### MAIN #####

main() {
    log "starting llamacpp setup..."
    check_prerequisites
    create_directories
    pull_image &
    download_model
    wait
    deploy_compose
    install_systemd
    start_service
    verify_service
    print_summary
}

main "$@"
