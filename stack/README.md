# stack — servicios self-hosted

Biblioteca de stacks de terceros (y propios) para prototipar o montar el stack
propio. Un servicio por carpeta, autocontenido y levatable solo.

## Formato

`stack/<categoria>/<servicio>/` — como mínimo un `compose.yml`. Las configs,
entrypoints y assets del servicio viven **en su misma carpeta** y se montan
desde `./`.

Convenciones:

- **Red compartida `stack`.** Cada compose la declara `name: stack`, así que un
  servicio arranca solo pero, si están a la vez, se ven por `hostname`
  (`redis`, `qdrant`, `vllm`…). Crearla una vez: `docker network create stack`
  (o arrancar cualquier compose: se autocrea).
- **Puertos = default upstream**, expuestos igual en el host y `explicitados`.
  Override con `${X_PORT:-default}` cuando dos choquen (p. ej. `8080`, `80`).
- **Datos** en volúmenes nombrados (no en el repo). Configs montadas `:ro`.
- `container_name = hostname = short_name` (minúsculas, sin guiones bajos).
- Labels `stack.category` y `stack.port`.
- **Versiones = `:latest`** por defecto, para asegurar siempre la final. Se
  tolera un pin sólo cuando el tag `latest` no existe o el número fija formato
  (p. ej. `pgvector:pg17`, major de Postgres; `llama.cpp:server-cuda` y
  TEI `cpu-latest` son ya tags flotantes).
- **Pares indivisibles.** Un servicio que solo existe para otro vive en su propia carpeta
  pero no se levanta solo: el principal lo `include`a y lo exige con `depends_on`
  (`required: true`, `service_healthy`). Un `compose up` levanta ambos; un `down`, ambos.
  Hoy: `rag/searxng` ⊃ `rag/yacy`.
- `stack/_template/compose.yml` es la **plantilla absoluta** con todos los campos
  de Compose y valores fake: cópiala y poda para dar de alta un servicio.

## Categorías

Databases, por modelo de datos:

| Cat | Modelo | Servicios aquí |
|---|---|---|
| `rdb` | relacional | postgres (pgvector) |
| `cdb` | cache / KV | redis |
| `vdb` | vector | qdrant |
| `gdb` | grafo | — vacío |
| `ddb` | documento | — vacío |
| `tdb` | serie temporal | — vacío |

Infra y aplicaciones:

| Cat | Alcance | Servicios aquí |
|---|---|---|
| `queue` | brokers, event bus | — vacío |
| `proxy` | reverse proxy, gateway, túneles | — vacío |
| `auth` | identidad, secretos | — vacío |
| `watch` | métricas, logs, trazas | otel-collector, jaeger, prometheus, loki, grafana |
| `storage` | objetos/archivos, datalakes | minio |
| `llm` | serving de modelos y embeddings | strata, vllm, llamacpp, ellm, embed |
| `speech` | STT / TTS | evoice, speaches, fwhisper, wlive, kokoro |
| `rag` | retrieval: búsqueda, loaders, extracción, pipelines | searxng (+ yacy), docling, playwright, pipelines |
| `mem` | memoria de agentes | cortexdb |
| `agent` | harnesses de agentes como servicio | openhuman (+ cortexdb) |
| `front` | UIs y dashboards | openwebui |
| `media` | WebRTC / tiempo real | livekit, sip |

## Inventario

Puerto = default en host (`:container`). GPU = necesita `nvidia` runtime.

| Cat/Servicio | Imagen | Puerto(s) | GPU | Adjuntos |
|---|---|---|---|---|
| rdb/postgres | pgvector/pgvector:pg17 | 5432 | | |
| cdb/redis | redis:latest | 6379 | | `redis.conf` |
| vdb/qdrant | qdrant/qdrant:latest | 6333 / 6334 | | `config.yaml` |
| storage/minio | minio/minio:latest | 9000 / 9001 | | |
| llm/strata | build `strata:<tag>` (engine en local) | 8000 | ✓ | `setup.sh`; toma el hostname `vllm`: uno de {strata, vllm} en la tarjeta, nunca los dos |
| llm/vllm | vllm/vllm-openai:latest | 8000 | ✓ | profesor de jev (reader de logprobs); sirve el alias `demian-model` |
| llm/llamacpp | ggml-org/llama.cpp:server-cuda | 8080 | ✓ | `setup.sh` |
| llm/ellm | damvolkov/e-llm:latest | 80 | ✓ | `config.yaml` |
| llm/embed | hf/text-embeddings-inference:cpu-latest | 80 | | |
| speech/evoice | damvolkov/e-voice:latest | 80 | ✓ | `config.yaml` |
| speech/speaches | speaches-ai/speaches:latest-cuda | 8000 | ✓ | `entrypoint.sh` |
| speech/fwhisper | fedirz/faster-whisper-server:latest-cuda | 8000 | ✓ | |
| speech/wlive | collabora/whisperlive-gpu:latest | 9090 | ✓ | |
| speech/kokoro | remsky/kokoro-fastapi-gpu:latest | 8880 | ✓ | |
| rag/searxng | searxng/searxng:latest | 8080 | | `settings.yml`, `limiter.toml`; incluye `rag/yacy` |
| rag/yacy | yacy/yacy_search_server:latest | 8090 (loopback) | | índice propio P2P de searxng; no se levanta solo |
| rag/docling | docling-project/docling-serve:latest | 5001 | | |
| rag/playwright | playwright:latest | 3000 | | |
| rag/pipelines | open-webui/pipelines:latest | 9099 | | |
| mem/cortexdb | cortexdb/cortexdb:v0.10.4 (pin: formato de datos) + `cortexdb-mirror` (python:3-alpine) | 3141 (loopback) | | `cortex.toml`, `mirror.py` (grafo → markdown de Obsidian en `CORTEXDB_MIRROR_DIR`); usa `llm/embed` (lotes de hasta 512) y `llm/vllm` |
| front/openwebui | open-webui/open-webui:latest | 8080 | | `static/` |
| media/livekit | livekit/livekit-server:latest | 7880 | | `livekit.yaml` |
| media/sip | livekit/sip:latest | 5060 | | red `host` |
| watch/otel-collector | otel/opentelemetry-collector-contrib:latest | 4317 / 4318 / 8889 | | `otel-collector-config.yaml` |
| watch/jaeger | jaegertracing/all-in-one:latest | 16686 | | |
| watch/prometheus | prom/prometheus:latest | 9090 | | `prometheus.yml` |
| watch/loki | grafana/loki:latest | 3100 | | |
| watch/grafana | grafana/grafana:latest | 3000 | | `provisioning/` |

## URLs entre servicios (red `stack`)

```
redis:6379        postgres:5432     qdrant:6333      minio:9000
strata|vllm:8000/v1  llamacpp:8080     ellm:80          embed:80/v1
kokoro:8880/v1    fwhisper:8000     evoice:80        speaches:8000
searxng:8080      yacy:8090         docling:5001      playwright:3000  pipelines:9099
otel-collector:4317   jaeger:16686   prometheus:9090   loki:3100   grafana:3000
livekit:7880
```

## Uso

```bash
docker network create stack                 # una vez
cd stack/cdb/redis && docker compose up -d   # un servicio
cd stack/front/openwebui && docker compose up -d  # necesita llm+vdb+rag ya arriba
```

`openwebui` referencia por hostname a `vllm` (el slot: alias de `strata` o de `vllm`), `embed`, `qdrant`, `searxng`,
`playwright`, `docling`, `redis` y `kokoro`: levántalos antes o ajustá los env.
