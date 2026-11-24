FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONPATH=/app UV_LINK_MODE=copy
### docling is a hard dependency of docling-graph and drags torch; conversion runs on docling-serve, so the CPU wheel is enough.
RUN uv venv /opt/venv && uv pip install --index-strategy unsafe-best-match \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    docling-graph fastapi "uvicorn[standard]" python-multipart falkordb pydantic-settings
### a named volume seeds from the image: /data is the runtime user's from the first start.
RUN mkdir /data && chown 1000:1000 /data
WORKDIR /app
COPY *.py ./
COPY templates ./templates
USER 1000:1000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "45850"]
