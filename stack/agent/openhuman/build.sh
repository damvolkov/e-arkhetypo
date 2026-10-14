#!/usr/bin/env bash
# build.sh — the two images this stack runs, from an OpenHuman source tree (upstream, or a branch with patches):
#   openhuman-core:<tag>  upstream's Dockerfile, built with the desktop product's features (voice, web3, inference,
#                         runtime-node…; scripts/ci/product-features.txt) — the contributor default it builds alone
#                         lacks tools a desktop config declares, and every agent turn is then refused
#   openhuman-ui:<tag>    the app's own React UI built for the web (vite), served by nginx on loopback
# Usage: ./build.sh <source-tree> [tag]   (tag defaults to demian; the compose reads OPENHUMAN_TAG)
# The tree must allow `--build-arg CARGO_FEATURES` in its Dockerfile (an ARG used by both cargo builds).
set -euo pipefail
TREE="$(cd "${1:?usage: build.sh <openhuman source tree> [tag]}" && pwd)"
TAG="${2:-demian}"
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v node >/dev/null || { export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"; . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true; }

git -C "$TREE" submodule update -q --init --recursive
grep -q 'ARG CARGO_FEATURES' "$TREE/Dockerfile" || { echo "build.sh: $TREE/Dockerfile has no CARGO_FEATURES arg" >&2; exit 1; }
features=$("$TREE/scripts/ci/product-features.sh" | tr ',' '\n' | sed 's|^|openhuman-core/|' | paste -sd,)
docker build --build-arg CARGO_BUILD_JOBS="$(nproc)" --build-arg CARGO_FEATURES="$features" -t "openhuman-core:$TAG" "$TREE"

(cd "$TREE/app" && pnpm install -s --frozen-lockfile --ignore-scripts \
    && VITE_OPENHUMAN_CORE_RPC_URL="http://127.0.0.1:${OPENHUMAN_CORE_PORT:-7788}/rpc" pnpm exec vite build)
printf '*\n!dist\n' > "$TREE/app/.dockerignore"
docker build -f "$HERE/ui/Dockerfile" --build-context ui="$HERE/ui" -t "openhuman-ui:$TAG" "$TREE/app"
echo "build.sh: openhuman-core:$TAG and openhuman-ui:$TAG ready — docker compose up -d --wait"
