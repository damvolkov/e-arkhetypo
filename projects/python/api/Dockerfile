##### BUILDER #####
FROM ghcr.io/astral-sh/uv:0.12.15-python3.14-trixie-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src /app/src
RUN uv sync --frozen --no-dev --no-editable

##### DEPLOY #####
FROM python:3.14-slim-trixie AS deploy
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --from=builder /app/.venv .venv
RUN mkdir -p /app/data && chown -R nobody /app/data
USER nobody
EXPOSE 8000
CMD ["granian", "--interface", "asgi", "--factory", "--host", "0.0.0.0", "--port", "8000", "e_api.main:create_app"]
