# DARTS

**D**eterministic-semantic · **A**tomic-agnostic · **R**unner-spec · **T**est-driven · **S**pec-driven.

A pipeline is a LangGraph graph of sections. Inside each section, the work is a DAG of **specs**: each
spec declares one output and the runners that produce, gate or shape it. The orchestrator plans the DAG,
runs it, and writes every output where the next reader finds it. This page is the law: follow it to the
letter when writing a spec, a runner or a pipeline. `e-graph darts check` enforces every rule below.

## Ontology

| Term | Is | Lives in |
|---|---|---|
| **pipeline** | one LangGraph graph: its wiring and one node per section | `pipelines/<pipeline>/` |
| **section** | one stage of a pipeline, from the closed `Section` taxonomy | `models/section.py` |
| **node** | the section's single LangGraph node: it runs the section's specs through the orchestrator | `pipelines/<pipeline>/nodes/<section>/node.py` |
| **spec** | one output a section produces: its schema, dependencies, fallback and plugged runners | `specs/<pipeline>/<section>/<NAME>.yaml` |
| **runner** | one async function in its own module, plugged into a spec's slot | `runners/owned/…` or `runners/agnostic/…` |
| **slot** | where a runner plugs into a spec: `runner`, `check`, `pre`, `post` | the spec's fields |
| **role** | what a runner function is: `run`, `check`, `pre_run`, `post_run` | the function's name |
| **scope** | who may plug a runner: `owned` (one pipeline's section) or `agnostic` (anyone) | the runner's path |
| **tool** | an agnostic runner, grouped by capability | `runners/agnostic/<capability>/<name>.py` |
| **wiki** | a glossary page a spec names, sent to the agent with its instructions | `specs/wiki/` or `specs/<pipeline>/wiki/` |
| **catalog** | a section judged coherent: specs with their resolved runners and validated args | built by `SpecDiscover` |
| **plan** | a section's steps: topological generations, semantic specs fused per tier | built by `DagPlan` |
| **context** | the run's data: every output at `state.context.<section>[<spec>]` | `RunState.context` |

## Taxonomy

### Sections and prefixes

Every spec name opens with its section's prefix, then lowercase words joined by hyphens: `EXT-net-income`.

| Section | Prefix | | Section | Prefix |
|---|---|---|---|---|
| ingest | `ING` | | inference | `INF` |
| normalize | `NOR` | | audit | `AUD` |
| classify | `CLS` | | transform | `TRF` |
| extract | `EXT` | | report | `REP` |
| validate | `VAL` | | custom | `CUS` |
| enrich | `ENR` | | | |

`ORDER` is the walking order; `custom` has no place in it, and the pipeline wires it where it belongs.

### Kinds, slots and roles

A spec is `deterministic` (code produces it) or `semantic` (the agent answers it). Its kind fixes its slots;
each slot takes exactly one role. Nothing else plugs anywhere.

| Kind | Slot | Role plugged | Required | The runner |
|---|---|---|---|---|
| deterministic | `runner` | `run` | yes | produces the output |
| deterministic · semantic | `check` | `check` | no | gates the state: `False` blocks the spec |
| semantic | `pre` | `pre_run` | no | prepares the material the prompt carries |
| semantic | `post` | `post_run` | no | reshapes the validated answer |

A `check` runner plugged into a `pre` slot, or a `run` into a `check`, is a `ROLE` breach. A `pre` field on a
deterministic spec, or a `runner` on a semantic one, fails decoding.

### Scopes

| Reference | Resolves to | Plugged by |
|---|---|---|
| `owned/<name>` | `runners/owned/<pipeline>/<section>/<name>.py` | specs of that pipeline and section only |
| `agnostic/<capability>/<name>` | `runners/agnostic/<capability>/<name>.py` | any spec of any pipeline |

Names, capabilities and pipelines are one lowercase word: `[a-z][a-z0-9]*`. An owned runner plugged by no
spec is an `ORPHAN` (an error: delete it). A tool plugged by no spec is `IDLE` (a warning: it may wait).

## Tree

```
src/e_graph/
  pipelines/<pipeline>/graph.py                 one <Pipeline>Graph(PipelineBuilder): the wiring
  pipelines/<pipeline>/nodes/<section>/node.py  one node per section: async def node_<section>(state: RunState)
  specs/<pipeline>/<section>/<PFX>-<words>.yaml one spec per file, the file named as the spec
  specs/<pipeline>/wiki/<term>.md               the pipeline's glossary (wins over the shared one)
  specs/wiki/<term>.md                          the shared glossary
  runners/owned/<pipeline>/<section>/<name>.py  a runner owned by one pipeline's section
  runners/agnostic/<capability>/<name>.py       a tool any spec may plug
```

A spec folder exists only for a section the pipeline's graph mounts (`UNMOUNTED` otherwise). Folders hold
nothing but what the tree admits (`TREE`): no stray files, no nesting, no second word.

## Write a spec

```yaml
kind: semantic                         # deterministic | semantic
name: EXT-income                       # <PFX>-<words>, the file's own name
description: The income statement's headline figures, in US dollars.
pre: agnostic/document/pages           # slots by kind: runner | check (deterministic) · pre | post | check (semantic)
post: agnostic/number/scale
check: agnostic/context/present
args:                                  # per slot: what that runner's `Args` decodes
  pre: {titles: [consolidated statements of operations], words: [net income], most: 3}
  post: {fields: [revenue, net_income]}
  check: {needs: [ingest/ING-document]}
instructions: >-                       # semantic only: what the agent reads and answers
  From the consolidated statement of operations, the latest fiscal year: revenue and net income, in
  millions of US dollars exactly as printed.
tier: medium                           # semantic only: high | medium | low — specs of one tier share a call
examples: []                           # semantic only: few-shot answers, each valid against `output`
wiki: [statement-units]                # terms explained in a wiki page
output:                                # JSON Schema of the output, object root; enforced on every answer
  type: object
  properties: {revenue: {type: number}, net_income: {type: number}}
  required: [revenue, net_income]
  additionalProperties: false
depends: []                            # specs of the same section whose outputs this one reads
fallback: null                         # a spec of the same section that answers when this one fails
bound: io                              # io | cpu — cpu runs on a worker thread's own loop
timeout: PT2M                          # ISO 8601 duration; DARTS_TIMEOUT otherwise
version: 1
```

Rules a spec keeps, checked while decoding: unknown fields are refused; `depends` and `fallback` name specs
of the same section, never itself; the fallback is no dependency; `args` name only plugged slots; examples
match `output`; `timeout` is positive. Rules only the section can tell: dependencies exist (`DEPENDS`), the
graph is acyclic (`CYCLE`), a fallback has no dependencies, no fallback of its own, and nobody depends on it
(`FALLBACK`), every wiki term has its page (`WIKI`).

Write `output` as tight as the data allows: `required`, `additionalProperties: false`, patterns, minimums.
The schema is the only thing standing between a wrong answer and the next section.

## Write a runner

A runner module holds **exactly one function**, named by its role, with the role's exact signature, and a
docstring that says what it does (it becomes the runner's description):

```python
async def run(state: RunState, call: Call) -> dict[str, Any]: ...
async def check(state: RunState, call: Call) -> bool: ...
async def pre_run(state: RunState, call: Call) -> str: ...
async def post_run(state: RunState, call: Call, output: dict[str, Any]) -> dict[str, Any]: ...
```

It may declare `Args`, the `CheckedStruct` its slot's `args` decode into — validated at discovery, never at
run time. A runner without `Args` takes none: giving it some is an `ARGS` breach.

```python
class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`tolerance`: the share of assets the gap may reach."""

    tolerance: Annotated[float, msgspec.Meta(ge=0, le=1)] = 0.05


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The gap between assets and liabilities plus equity, and whether it is tolerable."""
    sheet = state.context.extract["EXT-balance"]
    gap = sheet["total_assets"] - sheet["total_liabilities"] - sheet["equity"]
    return {"gap": gap, "holds": abs(gap) <= call.args.tolerance * sheet["total_assets"]}
```

`Call` is what the runner is handed beside the state: `pipeline`, `section`, `spec`, `slot`, `args` (the
validated `Args`, or `{}`), and `inputs` — the outputs of the spec's `depends`, by name. Read an earlier
section's output at its address, `state.context.<section>[<spec>]`; the `agnostic/context/present` tool
gates a spec on those addresses (`needs: [ingest/ING-document]`). A helper the function needs is a method of
`Args` or another module's job, never a second function: `SHAPE` refuses it.

Make a runner a tool (`agnostic/`) when it knows nothing of one pipeline: what it reads comes from `Args`
(an address, a field list). Keep it owned when it knows one pipeline's outputs by name.

## Write a node and a graph

```python
async def node_extract(state: RunState) -> dict[str, Any]:
    """Read the cover and the statements' headline figures."""
    return await state.infra.orchestrator.node(Section.EXTRACT, state)
```

`node(section, state)` runs the section and reports its summary and every spec's status. Strict by default:
a spec `failed` or `blocked` fails the node, each one named; `strict=False` lets the node pass on what was
delivered. The graph (`<Pipeline>Graph.compose`) wires the nodes; a pipeline's graph refuses another
pipeline's node (`PIPELINE`) and a second node for a section (`SECTION`).

## Run

```
inputs ──▶ check ──▶ produce ──────────────────────▶ validate ──▶ write context.<section>[<spec>]
  │          │       D: run(state, call)                 │
  │          │       S: pre_run ▶ fused call ▶ post_run  │
  ▼          ▼          ▼ (error · timeout)              ▼ (output breaks `output`)
skipped   blocked     fallback ──▶ rescued (written under the parent's name) · or failed
```

A spec's step is its depth in the `depends` DAG; a step runs everything in it at once (bounded by
`DARTS_CONCURRENCY`). Semantic specs of one step and tier are **fused**: one agent call answers them all,
each under its own name and schema, shared material sent once — split into more calls past
`DARTS_FUSION_TOKENS` or `DARTS_FUSION_SPECS`. Fallbacks never run on their own: they wait for their parent
to fail, then write under its name. Statuses: `succeeded`, `rescued`, `failed`, `blocked` (its check refused,
or an input was blocked), `skipped` (an input delivered nothing).

## Laws

| Rule | Scope | Breach | Fix |
|---|---|---|---|
| `TREE` | tree | a folder or file the tree does not admit | move it, rename it to one word, or delete it |
| `PIPELINE` | system | specs or owned runners of a pipeline no graph mounts | rename the folder, or delete it |
| `UNMOUNTED` | system | specs of a section the pipeline has no node for | add the node, or delete the folder |
| `DECODE` | spec | the YAML does not decode into its kind | read the detail: field, type, pattern |
| `MERGE` | spec | a YAML merge key (`<<`) | write the fields out; anchors and aliases are fine |
| `FILENAME` | section | file and spec named apart | rename one |
| `DEPENDS` | section | a dependency that does not exist | add the spec, or drop the name |
| `FALLBACK` | section | a fallback missing, chained, with dependencies, or depended on | keep fallbacks leaves |
| `CYCLE` | section | a dependency cycle, named edge by edge | break one edge |
| `RUNNER` | section | a plugged runner missing, or that fails to load | write it, fix the reference or its import |
| `SHAPE` | section | a runner module with no function, or more than one | one function per module |
| `ROLE` | section | a function whose role does not fit its slot | plug it in its slot, or rename it |
| `SIGNATURE` | section | a function off its role's signature | copy the signature above, exactly |
| `DOC` | section | a runner without a docstring | say what it does, in one line |
| `ARGS` | section | args the runner's `Args` refuse, or args for a runner that takes none | match the `Args` |
| `WIKI` | section | a wiki term without its page | write `specs/wiki/<term>.md` |
| `ORPHAN` | section | an owned runner no spec plugs | plug it, or delete it |
| `IDLE` | system | a tool no spec plugs — a **warning** | plug it, or let it wait |

A spec that fails to decode is reported once: its own breach never cascades into missing dependencies or
orphans. No runner executes while any law of its section is broken; a plugged runner executes once, at
discovery, to validate its args — an unplugged one never does.

## Check

```bash
e-graph darts check                      # every pipeline: exit 0 clean, 1 on any error; warnings never fail
e-graph darts check --pipeline filing    # one pipeline (the system's own laws are judged anyway)
e-graph darts check --json               # the Report, for a machine: ok, pipelines, sections, specs, breaches
e-graph darts plan filing extract        # the steps and fused calls a section would run, without running it
```

The check is deterministic: same tree, same report. DARTSOPS runs it after every change it makes and reads
the JSON; a test (`tests/unit/e_graph/test_taxonomy.py`) holds the real system to a clean report.

## Lab

The orchestrator seen from outside, at two levels — the pipeline (its LangGraph graph) and the spec-node
(one section's specs as the orchestrator runs them). One object, `SectionLab`, serves the API, the canvas
and the CLI:

| Need | API | CLI |
|---|---|---|
| every mounted section | `GET /api/specs/list` | `e-graph lab list` |
| a section placed for drawing | `GET /api/specs/topology/{pipeline}/{section}` | `e-graph lab graph <p> <section>` (tree) |
| the same section drawn | `GET /api/specs/svg/{pipeline}/{section}` | `--draw dot` · `--draw svg [--out f]` |
| a pipeline's own graph | `GET /api/pipelines/topology/{pipeline}` | `e-graph lab graph <p> --draw dot\|svg` |
| a rehearsal and its payloads | `POST /api/specs/simulate/{pipeline}/{section}` | `e-graph lab simulate <p> <section> --data k=v [--case f] [--live] [--out dir]` |

**The map** is built from the very catalog and plan the orchestrator runs by: a spec's rank is its step, its
lane its place in the step (deterministic specs, then each fused call's specs, then the fallbacks held for
that step); arcs for `depends` (solid) and `fallback` (dashed); one group per planned fused call, weighed
against `DARTS_FUSION_TOKENS`. The drawing is rustworkx's own `to_dot()`, rendered by Graphviz compiled to
WebAssembly on wasmtime (`wasi-graphviz`): no native binary.

**A rehearsal** runs the pipeline up to the section, the section included — every earlier section of the
graph once, in rank order — on a copy of the system. Runners run for real; the agent answers each spec from
its first `example`, or the least its `output` schema accepts (patterns matched by `rstr`, seeded): no model
is called and nothing is spent, yet every agent call is exactly what a live run sends. `--live` (the canvas's
*live model*) keeps the real agent. Every run records its calls as `AgentCall`s — instructions, prompt,
schema, tier, the weight of each spec — in `SectionRun.calls`, and on the `spec.call-<n>` span
(`input.value`, `spec.instructions`) for Phoenix to show.

**The canvas** switches level from its panel; a double click on a pipeline node opens that section's
spec-graph. Click a spec for its card (runners, schema, and after a rehearsal its status and what it wrote);
click a call for its payload (instructions · prompt · schema, its route, each spec's weight).

## Procedures

**Add a spec.** Pick its section and kind. Name it `<PFX>-<words>`; create
`specs/<pipeline>/<section>/<name>.yaml`. Write `description` and the tightest `output`. Plug the runners its
kind needs — a tool when one fits (`runners/agnostic/`), an owned runner otherwise — with each slot's `args`.
Name `depends` for every same-section output it reads; gate earlier sections' outputs with
`check: agnostic/context/present`. Run `e-graph darts check`, then `e-graph darts plan <pipeline> <section>`.

**Add a runner.** Owned: `runners/owned/<pipeline>/<section>/<name>.py`. Tool:
`runners/agnostic/<capability>/<name>.py`. One function, its role's signature, a docstring, `Args` if it
takes any. Plug it from a spec; test it in `tests/unit/e_graph/runners/…` mirroring its path.

**Add a section to a pipeline.** Write `pipelines/<pipeline>/nodes/<section>/node.py` with
`node_<section>` calling `orchestrator.node(Section.<SECTION>, state)`, wire it in the graph, then add its
specs. Specs first, node later, is an `UNMOUNTED` breach until the node lands.

**Add a pipeline.** `pipelines/<pipeline>/graph.py` with one `<Pipeline>Graph(PipelineBuilder)`; its nodes;
`specs/<pipeline>/`; `runners/owned/<pipeline>/`. The registry serves it on the next boot.

## The pipelines

| Pipeline | Sections | What it shows |
|---|---|---|
| `doc` | ingest → (normalize ∥ classify) → extract ⇄ validate → transform → report | every graph shape, deterministic specs, args, a check tool, a retry loop |
| `filing` | ingest → extract → audit → report | a 10-K read into XBRL facts: hybrid reading, three semantic specs fused into one call, `pre`/`post` tools, identity audits |
| `note` | ingest → extract → inference → audit → report | a 424B2 autocallable read into its term sheet: five shared tools (`document/read`, `text/match`, `table/rows`, `number/scale`, `standard/checksum`), a semantic spec rescuing a regex, 22 specs with `depends` re-organizing three steps, the plan fusing into five calls and the material re-splitting them into ten at the run |

`filing` over Apple's 2025 10-K reads every one of its 14 facts exactly (cover, income statement, balance
sheet; 2026-10-14, Gemma 4 26B-A4B on vLLM). Over Coca-Cola's, the income statement reads exactly; the
balance sheet's liabilities and equity do not — docling's table model splits that sheet's labels from its
figures. The balance audit catches an inconsistent read, but an identity is no oracle: figures that are wrong
yet sum right pass it.
