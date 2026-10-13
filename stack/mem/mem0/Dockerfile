# syntax=docker/dockerfile:1
# Mem0 OSS REST server built from upstream `server/` (context `upstream`), plus what the
# published image lacks: the v3 hybrid retrieval extras (fastembed BM25, spaCy entities)
# baked in, and `launch.py` so the config comes from a mounted file, not from env defaults.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed

WORKDIR /app

COPY --from=upstream requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt "mem0ai[nlp]" fastembed \
 && python -m spacy download en_core_web_sm \
 && python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('Qdrant/bm25')"

COPY --from=upstream . .
COPY launch.py .

EXPOSE 8000

CMD ["python", "launch.py"]
