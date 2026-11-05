"""tests/support/root: what the composition root hands down, built from the clusters' own defaults — the keyword
arguments of the agent, the DARTS budgets, the document reader and the telemetry driver, overrides on top."""

from typing import Any

import msgspec

from e_graph.logic.models import Darts
from infra.config.agent import AgentSettings
from infra.config.darts import DartsSettings
from infra.config.processors import ProcessorSettings
from infra.config.providers import ProviderSettings

### the agent's own knobs, named as the tests name them; any other key is a provider variable, upper-cased.
AGENT_KNOBS = frozenset({"timeout", "retries", "high", "medium", "low"})


def agent_args(**values: Any) -> dict[str, Any]:
    """The agent's keyword arguments from explicit values only (`retries=1`, `high={...}`, `openai_api_key=...`)."""
    conf = AgentSettings(
        _env_file=None,
        **{(f"AGENT_{key}" if key in AGENT_KNOBS else key).upper(): value for key, value in values.items()},
    )
    return {
        "credentials": conf.agent_credentials(),
        "tiers": conf.agent_tiers(),
        "timeout": conf.AGENT_TIMEOUT,
        "retries": conf.AGENT_RETRIES,
    }


def darts(**over: Any) -> Darts:
    """The DARTS budgets at their defaults, overrides on top."""
    conf = DartsSettings(_env_file=None)
    defaults = Darts(
        concurrency=conf.DARTS_CONCURRENCY,
        calls=conf.DARTS_CALLS,
        fusion_specs=conf.DARTS_FUSION_SPECS,
        fusion_tokens=conf.DARTS_FUSION_TOKENS,
        timeout=conf.DARTS_TIMEOUT,
    )
    return msgspec.structs.replace(defaults, **over)


def doc_args(**over: Any) -> dict[str, Any]:
    """The document reader's keyword arguments at their measured defaults, overrides on top."""
    conf = ProcessorSettings(_env_file=None)
    return {
        "concurrency": conf.DOC_CONCURRENCY,
        "span": conf.DOC_SPAN,
        "gap": conf.DOC_GAP,
        "mode": conf.DOC_MODE,
        "route": conf.DOC_ROUTE,
        "tables": conf.DOC_TABLES,
        "max_input_bytes": conf.DOC_MAX_INPUT_BYTES,
    } | over


def otel_args(**over: Any) -> dict[str, Any]:
    """The telemetry driver's keyword arguments at their defaults (no endpoint: nothing exported), overrides on top."""
    conf = ProviderSettings(_env_file=None)
    return {
        "endpoint": conf.OTEL_ENDPOINT,
        "protocol": conf.OTEL_PROTOCOL,
        "headers": conf.OTEL_HEADERS,
        "timeout": conf.OTEL_TIMEOUT,
        "flush": conf.OTEL_FLUSH,
        "service": conf.OTEL_SERVICE,
        "attributes": conf.OTEL_ATTRIBUTES,
        "sample": conf.OTEL_SAMPLE,
    } | over


def liteparse_args(**over: Any) -> dict[str, Any]:
    """The fast page reader's keyword arguments at their defaults, overrides on top."""
    conf = ProviderSettings(_env_file=None)
    return {
        "workers": conf.DOC_WORKERS,
        "ocr": conf.DOC_OCR,
        "tessdata": conf.DOC_TESSDATA,
        "ocr_language": conf.DOC_OCR_LANGUAGE,
    } | over


def anytomd_args(**over: Any) -> dict[str, Any]:
    """The any-format reader's keyword arguments at their defaults, overrides on top."""
    conf = ProviderSettings(_env_file=None)
    return {
        "vision_base_url": conf.MD_VISION_BASE_URL,
        "vision_api_key": conf.MD_VISION_API_KEY,
        "vision_model": conf.MD_VISION_MODEL,
        "vision_prompt": conf.MD_VISION_PROMPT,
        "image_describe": conf.MD_IMAGE_DESCRIBE,
        "max_input_bytes": conf.MD_MAX_INPUT_BYTES,
        "pdf_workers": conf.MD_PDF_WORKERS,
        "pdf_ocr": conf.MD_PDF_OCR,
        "pdf_language": conf.MD_PDF_LANGUAGE,
        "strict": conf.MD_STRICT,
        "extract_comments": conf.MD_EXTRACT_COMMENTS,
    } | over
