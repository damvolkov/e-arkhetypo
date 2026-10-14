##### BUILDER #####
FROM ghcr.io/astral-sh/uv:0.12.15-python3.14-trixie-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src /app/src
RUN uv sync --frozen --no-dev

##### DEPLOY #####
FROM python:3.14-slim-trixie AS deploy
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN mkdir -p /data && chown -R nobody /data
USER nobody
EXPOSE 45200
CMD ["granian", "--interface", "asgi", "--factory", "--host", "0.0.0.0", "--port", "45200", "e_mcp.main:assemble"]
