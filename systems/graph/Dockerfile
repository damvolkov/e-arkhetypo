##### UI #####
FROM node:24-slim AS ui
WORKDIR /app/src/e_graph/ui
RUN corepack enable
COPY src/e_graph/ui/package.json src/e_graph/ui/pnpm-lock.yaml src/e_graph/ui/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY src/e_graph/ui ./
### vite writes dist/ beside its sources; only that bundle travels into the builder below.
RUN pnpm build

##### BUILDER #####
FROM ghcr.io/astral-sh/uv:0.12.15-python3.14-trixie-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src /app/src
COPY --from=ui /app/src/e_graph/ui/dist /app/src/e_graph/ui/dist
RUN uv sync --frozen --no-dev --no-editable

##### DEPLOY #####
FROM python:3.14-slim-trixie AS deploy
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --from=builder /app/.venv .venv
RUN mkdir -p /app/data && chown -R nobody /app/data
USER nobody
EXPOSE 8000
CMD ["granian", "--interface", "asgi", "--factory", "--host", "0.0.0.0", "--port", "8000", "e_graph.main:create_app"]
