# llm/gliner

[gliner](https://github.com/damvolkov/gliner): zero-shot named entities over HTTP — a GLiNER bi-encoder on ONNX
Runtime, in Rust, CPU-only. Image `ghcr.io/damvolkov/gliner` (distroless, uid 65532), port `5800`.

| Route | |
|---|---|
| `POST /ner` | `{text, labels[], threshold?}` → `{entities: [{start, end, text, label, score}]}` (character offsets) |
| `POST /ner/batch` | NDJSON in, NDJSON out, streamed |
| `GET /health` | liveness; answers while the model loads |
| `GET /ready` | 200 once the model is loaded, 503 before |
| `GET /models` | the model served and its registry version |

## The model registry

The image holds no model and downloads nothing. It serves the registry mounted read-only at `/models`, one directory
per version and a `current` file naming the one served:

```
current              "1"
1/                   text.onnx, labels.onnx, tokenizer.json, labels.tokenizer.json, config.json, manifest.json
```

The registry lives in the named volume `gliner-models`. Fill it once, before the first `up`: export a registry, or
take one that exists, then copy it in.

**Export** — from a checkout of the gliner repository (PyTorch CPU in a uv project):

```bash
make export MODEL=knowledgator/gliner-bi-base-v2.0     # → data/models/gliner-bi-base-v2.0/{1/,current}
```

**Copy** — the exported registry, or any other one (another host's), into the volume:

```bash
docker volume create gliner-models
docker run --rm -v gliner-models:/models -v "$PWD/data/models/gliner-bi-base-v2.0":/registry:ro \
  busybox cp -a /registry/. /models/
```

Merged into one stack (`e_infra.ops.compose`), every named volume binds under `data/<service>/`: there the registry is
the directory `data/gliner/gliner-models/`, filled with a plain `cp -a`. The files must be readable by uid 65532: the
export writes them world-readable, and `cp -a` keeps that. At load every file is hashed against `manifest.json`; a
registry that does not match refuses to serve.

## Up

```bash
docker compose up -d
curl -s localhost:5800/ready
curl -s localhost:5800/ner -H 'content-type: application/json' \
  -d '{"text": "José Saramago vivió en Lanzarote.", "labels": ["person", "location"]}'
```

| Env | Default | |
|---|---|---|
| `GLINER_PORT` | `5800` | host port |
| `GLINER_THREADS` | `8` | ONNX Runtime threads — always explicit: its own default sizes to the host, not the container |
| `GLINER_CONCURRENCY` | `2` | predictions in flight across all requests |

Any other key of the service's configuration is `GLINER_<SECTION>__<KEY>` (its `gliner.example.toml`). No compose
healthcheck: a distroless image has no shell to probe with, so readiness is `GET /ready` from outside. Peak memory is
about 1 GB.
