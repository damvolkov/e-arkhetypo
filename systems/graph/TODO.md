# TODO — `note` pipeline: a structured note read into a large spec-graph

Goal: a third pipeline over a real, public document, with many specs across **extract · inference · audit**,
to *see* the orchestrator at scale in the specs canvas and the lab. It should show:
- steps reorganized from intra-section `depends`;
- many semantic specs in one step and tier, split into several fused calls that run in parallel;
- tiers kept apart;
- the merged JSON schema of each call;
- fallbacks, including a semantic one rescuing a deterministic one.

No new engine features are planned. Something gets built only if the map shows it is missing.

## 0 · Document

- [x] Source: **BofA Finance LLC, 424B2 pricing supplement, Trigger Autocallable Contingent Yield Notes linked to
  the S&P 500, due 2027-11-12**.
  - Link: https://www.sec.gov/Archives/edgar/data/70858/000191870425019416/form424b2.htm
  - Key terms, read 2026-10-14, to verify against the file:
    - identifiers: CUSIP 09711E688, ISIN US09711E6885;
    - dates: pricing 2025-11-06, issue 2025-11-12, 8 quarterly observations (table on PS-6), maturity 2027-11-12;
    - terms: coupon 9.60% p.a. paid quarterly ($0.24 per $10); coupon barrier and downside threshold 5,040.24
      (75% of initial); call threshold 6,720.32 (= initial value);
    - money: estimated value $9.938 per $10; aggregate $6,484,400; calculation agent BofAS.
  - Alternative to probe generality later: an RBC 424B2 on the S&P 500, same family, different layout.
- [x] Render the HTML to PDF with Chromium, as the 10-Ks were →
  `tests/resources/documents/notes/bofa-autocall-2027.pdf`.
  - [x] Add a `corpus.yaml` entry: sha256, source, license note (SEC EDGAR, free reuse).
  - [x] `truth:` curated **by hand from the document** (every value verified against the file 2026-10-14,
    plus the observation and payment dates, fees and underlier ticker).
- [x] `make conversions` → its docling spans recorded (GoldenPort): 2 spans, 25 s, 88 KB.
- [x] Check page selection: 25 pages, deep 1–24 (docling reads the whole offering table-of-lay). Key terms
  and identifiers land on page 1 (the cover's `first: 1` material answers eight medium specs); the dates
  table on page 6 (`table/rows` finds its unique header); the payoff on page 4 (`summary` title).

## 1 · Tools to share (agnostic, reused across pipelines)

- [x] `agnostic/document/read` (run): moved; `owned/filing/ingest/document` deleted; filing's ING-document re-plugged.
  `filing` and `note` both plug it; `owned/filing/ingest/document` is deleted (ORPHAN proves it).
- [x] `agnostic/text/match` (run): named groups required at discovery; `many` gathers per-group lists.
  - Args: `source`, `pattern`, `pages`, `many`.
  - Deterministic extraction of identifiers, amounts, the registration number.
- [x] `agnostic/table/rows` (run): first table whose header holds all `header` words; cells named by `columns`.
  - Args: `source`, `header`, `columns`.
  - For the observation and payment dates.
- [x] `agnostic/standard/checksum` (run): isin/cusip/lei verified against the note's own US09711E6885 · 09711E688.
  - Args: `scheme` (`isin` ISO 6166 · `cusip` · `lei` ISO 17442 mod 97-10), `value` (an address + field).
- [x] Unit tests for each tool, mirroring its path (4 files, 17 tests).

## 2 · Specs (~35, target shape)

Prefixes: ING · EXT · INF · AUD · REP.

**ingest** (1): `ING-document` → `agnostic/document/read`.

**extract** (~18) — the wide section.

| Step | Deterministic | Semantic (fused) |
|---|---|---|
| 0 | `EXT-identifiers` (match: CUSIP, ISIN) · `EXT-amounts` (match: aggregate, denomination, price) · `EXT-registration` (match) · `EXT-schedule-table` (rows: observation / payment dates) · `EXT-fees` (match) | **medium**: `EXT-issuer` · `EXT-underlier` · `EXT-coupon` · `EXT-autocall` · `EXT-barrier` · `EXT-dates` · `EXT-estimated-value` · `EXT-agents` — **low**: `EXT-listing` · `EXT-tax` · `EXT-risks` — **high**: `EXT-payoff` (payment at maturity, structured) |
| 1 | `EXT-schedule` (normalize the table's dates to ISO, depends schedule-table + dates) | low: `EXT-coupon-schedule` (depends `EXT-coupon`, `EXT-schedule-table`) |
| 2 | `EXT-terms` (assemble the term sheet, depends on most of the above) | — |

- Fallback: `EXT-identifiers` → `EXT-identifiers-read`, a semantic spec that rescues the deterministic one when
  the regex misses.
- `pre`: `agnostic/document/pages` with each spec's own titles and words. `post`: `agnostic/number/scale` where
  amounts are in thousands.
- Expect 8+ medium specs in step 0 → with `DARTS_FUSION_SPECS=8` (or a budget squeeze) **≥ 2 parallel medium
  calls**, besides the low and high calls.

**inference** (~9).

| Step | Deterministic (owned) | Semantic |
|---|---|---|
| 0 | `INF-tenor` (ACT/365 and 30/360) · `INF-coupon-amount` · `INF-fee-drag` ((price − estimated value) / price) · `INF-call-ladder` (per call date: payout if called) | medium: `INF-product-type` (EUSIPA code + name) · `INF-cfi` (ISO 10962 CFI code) · high: `INF-risk-class` (1–7, with reasons) |
| 1 | `INF-max-return` (depends coupon-amount, tenor) · `INF-scenarios` (payoff at −60…+40 %, depends max-return, call-ladder) | low: `INF-summary` (plain-language, depends scenarios) |

**audit** (~10).

| Step | Deterministic | Semantic |
|---|---|---|
| 0 | `AUD-isin` (checksum) · `AUD-cusip` (checksum) · `AUD-isin-cusip` (ISIN = US + CUSIP + check) · `AUD-currency` (ISO 4217) · `AUD-dates` (pricing ≤ issue < observations < maturity) · `AUD-schedule` (8 quarterly, monotonic, payment after observation) · `AUD-thresholds` (downside ≤ coupon barrier ≤ call ≤ initial) · `AUD-value` (estimated < price) · `AUD-cfi` (6 letters, category D, attributes coherent) · `AUD-eusipa` (code in the map) | — |
| 1 | `AUD-verdict` (depends all) | high: `AUD-coherence` (does the payoff text agree with the extracted terms?) |

**report** (1): `REP-termsheet` (deterministic: the record, every audit verdict).

Gates: `check: agnostic/context/present` on every spec that reads another section. Wiki pages:
`contingent-coupon`, `autocall`, `downside-threshold`, `estimated-value`, `eusipa`, `cfi`, `day-count`.

## 3 · Pipeline

- [x] `pipelines/note/graph.py` (`NoteGraph`): ingest → extract → inference → audit → report; 5 nodes; 22 specs in extract, 10 in inference, 12 in audit, 1 in report — `darts check`: clean, 16 sections, 60 specs.
  - One node per section, strict.
  - `extract` and `report` summarize in words for the canvas.
- [x] `e-graph darts check` clean; `IDLE` none (all four tools plugged by the note; `number/scale` waits, un-plugged — it went unneeded: no figures in thousands).

## 4 · Tests

- [x] Unit (scripted agent answering from `truth`, GoldenPort): 11 tests in `pipelines/note/test_graph.py` —
  - every deterministic spec against truth; ✓ (match, rows, schedule, terms all real)
  - the plan pinned: steps per section, fused calls per tier, the split into ≥ 2 medium calls; ✓ + lab map/plan/lane pins;
  - a broken identifier rescued by `EXT-identifiers-read`; ✓ (rescued, written under the parent's name)
  - audits failing on a corrupted answer. ✓ (AUD-thresholds, AUD-value named in the verdict)
- [x] Lab: `SectionMap` of `note/extract` pinned (ranks 3, lanes 19, five planned calls, dashed fallback arc); DOT content pinned.
- [x] Integration: the whole pipeline against vLLM, cassette recorded, held to `truth`. Recorded 2026-10-14 after
  vLLM returned (Gemma AWQ): 14 LLM calls frozen, replay green offline in 0.6 s. The agent's and filing
  orchestrator's older cassettes re-recorded too: they carried `qwen3.6-27b` under URI-only matching — the
  body matcher (added with the note's nine concurrent identical POSTs) refused to replay them.
  - Record what reads wrong, as for KO, instead of hiding it.
- [x] Acceptance: `note/extract` spec-graph PNG generated (`make snap`, 17/17 green) — awaiting human review;
  a medium call card shows the merged `"title": "fused"` schema.

## 5 · What to look at (the point of it)

- [x] **Map.** Step 0 of extract is 19 lanes (5 det + 13 fused + fallback): the PNG clips the ninth spec of
  the medium call at the right edge of a 1440px fit — **judged acceptable by Damien (2026-10-14)**: the width
  stays, no lane-wrapping built.
- [ ] **Fusion.**
  - Do the medium calls split as `pack` predicts? YES at plan level (9 medium specs → 8+1 by the specs cap);
    the run re-splits by real material weight into 4 medium calls of 2–3 specs (cover ≈ 2.5k tokens/spec).
  - Does the real material re-split at run time (`AgentCall.weights` vs the plan's)? YES: 5 planned calls → 9 issued
    at first, 10 after the `EXT-agents` retarget added the Summary page (lab simulate, deterministic replay); call
    indices shuffle — creation order is concurrent under `DARTS_CALLS=4`.
- Do calls of one step run concurrently (`DARTS_CALLS`)? 10 calls ≤ 4 in flight; the extract section runs in
    ~35 s live on the shared GPU.
- [x] **Schema.** Every merged call sent was answered structurally valid (14 recorded calls, 0 schema retries
  needed after the fix below). **The finding: xgrammar accepts the schemas but the model starves them** —
  Gemma AWQ falls into a whitespace-repetition loop at grammar positions where whitespace is still legal
  (after the colon of a long string, after `[]`), burning the whole 32k window (`finish=length`,
  `reasoning_tokens=0`) until `TruncatedError`. Cured at the schema: `maxLength` on every semantic string,
  `maxItems` on every semantic array, and the two rambling specs (`EXT-payoff`, `AUD-coherence`,
  `INF-summary`) re-shaped to short bounded fields. Recording is thus flaky (3 attempts to a clean pass);
  replay is deterministic by construction.
  - Latency per call vs per spec: the extract section's ten fused calls ran the section in ~35 s live;
    seventeen per-spec calls over the same material would serialize the same GPU three times deeper — not
    re-measured; the fusion is kept on principle and on this evidence.
- [x] **Tiers.** `AGENT_HIGH__*` and `AGENT_LOW__*` set in `.env` to the same local vLLM as MEDIUM; the canvas
  routes every tier and the grouping is visible with one model.
- [x] **Context.** After trimming `EXT-payoff` to the cover's Investment Description and `EXT-agents` to the
    Summary row, the longest recorded prompt is 6,504 input tokens (~1/5 of the 32k window) — the p4 mega-table
    (43,878 chars) was avoided by choice, not by necessity; it fits but every sibling call waits behind it.

## Open

- Which tier layout is worth keeping once measured: is a high tier for `EXT-payoff` / `AUD-coherence` justified,
  or does medium read them as well? — still open: locally one model answers every tier, so the 2026-10-14 run
  only proves the *grouping* works, not that high buys quality.
- Does the EUSIPA / CFI classification earn its keep as a semantic spec, or should it be a deterministic map
  from the extracted features? **Partial verdict from the live run (2026-10-14):** EUSIPA earned it — the model
  named `yield enhancement` and `capital at risk` correctly under every recorded attempt and the coherence
  checks held. CFI nearly did not: the first answers used `X` where the standard's debt alphabet names a
  letter and dropped the `I` the index demands; it reads today only because the audit was widened to the
  standard's X-convention and the instructions point at it. If a second live pass shows the code still coin-flipped,
  make it the deterministic map (`D` + `X` + `I` for index notes) and keep the semantic for the *shape* phrase
  alone.
