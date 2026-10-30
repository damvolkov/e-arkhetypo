# e-mcp

**The MCP service template of the e-stack.** An in-process `MCPServer` (official Python SDK v2) served over
Streamable HTTP by granian, behind an optional bearer gate. It is the shape an e-metaxy-class bridge starts
from: composition root, ports and logic, a thin typed tool surface, loopback by default.

```
caller ──MCP (Streamable HTTP)──▶ e-mcp ──▶ your logic
    ▲                               │
    └──── results as plain JSON ────┘
```

## Tools

| tool | does |
|---|---|
| `ping()` | alive check: `{"alive": true, "port": …}` |
| `greet(name?)` | echoes a greeting through `logic` — replace with your domain |

## Layout

```
src/e_mcp/config/mcp.py   # MCP_* settings (host, port, token)
src/e_mcp/logic/echo.py   # pure logic — no I/O, no framework
src/e_mcp/models/echo.py  # frozen msgspec values
src/e_mcp/mcp/guard.py    # bearer gate: loopback is the wall, the token the door
src/e_mcp/mcp/tools.py    # the MCP surface — thin, typed, plain JSON answers
src/e_mcp/main.py         # composition root: granian's factory, explicit tool registration
src/e_mcp/__main__.py     # python -m e_mcp — granian on loopback
```

`src/infra`, `src/ops`, `src/adapters` are materialized from `../common` (`make common`); edit them only at source.

## Run

```bash
make install        # materialize infra/ops/adapters + shared root files, sync, hooks
make check          # lint · ty · tach · validate · drift · tests (100 % coverage gate)
make run            # serve on 127.0.0.1:45200
make up             # docker compose up
make release        # tag + ghcr image via the release workflow (gates inert: .github/ci.vars.example)
```

Configuration is `MCP_*` (see `.env.example`). Without `MCP_TOKEN` the boundary is loopback plus the
Host check; with it, every HTTP request needs `Authorization: Bearer <token>`.

## Point it at a client

```python
from mcp import Client

async with Client("http://127.0.0.1:45200/mcp") as client:
    await client.call_tool("greet", {"name": "world"})
```
