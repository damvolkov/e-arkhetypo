# mem/egnosis

[e-gnosis](https://github.com/damvolkov/e-gnosis): the house's long-term memory — collections, hybrid retrieval
(BM25 + vectors on ParadeDB), ingestion of folders and drives, over REST and MCP at `/mcp`.

| Piece | What |
|---|---|
| `compose.yml` | the public image, host network, :45200 |
| `egnosis.service` | the systemd user unit; orders the services it needs |
| `.env.example` | host side: `HOST_HOME`, `EGNOSIS_ENV_FILE` |

## Needs

`rdb/paradedb` (:45011) · `llm/embed` (:45110) · `llm/reranker` · `llm/gliner` · `rag/docling` (:45800) · the LLM slot `llm/vllm` (:45100).

## Up

```bash
cp .env.example .env && mkdir -p ../data/egnosis ../config/egnosis
docker compose up -d --wait
install -m 644 egnosis.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable egnosis
```
