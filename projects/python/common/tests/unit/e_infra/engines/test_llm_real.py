"""tests/unit/e_infra/engines/llm_real: the model agent against real models — the contract held whoever answers.

The same typed request goes to every vendor that answers here: the local vLLM (Gemma), and Gemini when GEMINI_API_KEY
is one Google accepts — a key it refuses skips with Google's reason, never passes. Embeddings go to the local TEI."""

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Annotated

import msgspec
import pytest
from google.genai import Client, errors
from pydantic import SecretStr as Secret

from e_infra.engines.llm import LLMEngine, Purpose
from e_infra.infra.config.engines import Tier
from e_infra.infra.errors import ProviderError
from e_infra.infra.settings import settings as st
from e_infra.providers.drivers.embed.tei import TEIEmbedDriver
from e_infra.providers.drivers.http.wreq import WreqDriver
from e_infra.providers.drivers.llm.google import GoogleLLMDriver
from e_infra.providers.drivers.llm.openai import OpenaiDriver
from support.cache import model_cache
from unit.e_infra.conftest import embed_args, google_llm_args, openai_args, wreq_args

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from e_infra.ports.llm import LLMPort

pytestmark = pytest.mark.integration


class Cover(msgspec.Struct, frozen=True):
    code: Annotated[str, msgspec.Meta(pattern="^[a-z-]+$")]
    limits: frozenset[int]


class Answer(msgspec.Struct, frozen=True):
    product: str
    covers: list[Cover]


INSTRUCTIONS = (
    "You extract exactly what the text says, as the schema asks. Codes are lowercase words joined by hyphens."
)
PROMPT = "Product: auto-plus. It covers glass-breakage with limits 300 and 600, and theft with limit 1000."


async def gemini_refusal(key: str) -> str | None:
    """Why Google refuses the key, or None when it accepts it."""
    client = Client(api_key=key)
    try:
        await client.aio.models.get(model="gemini-3.8-flash")
    except errors.APIError as error:
        return f"Gemini refuses GEMINI_API_KEY: {error.message}"
    finally:
        await client.aio.aclose()
    return None


@pytest.fixture(params=["openai", "gemini"])
async def model(request: pytest.FixtureRequest) -> AsyncIterator[LLMPort]:
    async with WreqDriver(**wreq_args()) as http:
        match request.param:
            case "openai":
                driver: LLMPort = OpenaiDriver(http, **openai_args(key=Secret("local-dev"), model="gemma4-26b-a4b"))
                try:
                    await driver.health()
                except ProviderError as error:
                    pytest.skip(f"no local vLLM: {error}")
            case _:
                key = st.GEMINI_API_KEY or st.GENAI_API_KEY
                reason = "no GEMINI_API_KEY" if key is None else await gemini_refusal(key.get_secret_value())
                _ = reason and pytest.skip(reason)
                driver = GoogleLLMDriver(**google_llm_args(api_key=key, model="gemini-3.8-flash"))
        async with driver:
            yield driver


async def test_llm_every_vendor_answers_the_same_contract(model: LLMPort) -> None:
    async with (
        WreqDriver(**wreq_args()) as http,
        TEIEmbedDriver(http, **embed_args(model="Qwen/Qwen3-Embedding-0.6B")) as embed,
    ):
        engine = LLMEngine(dict.fromkeys(Tier, model), embed, "tei:test", 1024, retries=2, cache=model_cache())
        answer = await engine.run(Tier.LOW, INSTRUCTIONS, PROMPT, Answer)
    assert answer.product == "auto-plus"
    assert {cover.code: cover.limits for cover in answer.covers} == {
        "glass-breakage": frozenset({300, 600}),
        "theft": frozenset({1000}),
    }


async def test_embed_tei_answers_its_declared_width() -> None:
    conf = embed_args(model="Qwen/Qwen3-Embedding-0.6B")
    async with WreqDriver(**wreq_args()) as http, AsyncExitStack() as stack:
        try:
            embed = await stack.enter_async_context(TEIEmbedDriver(http, **conf))
            await embed.health()
        except ProviderError as error:
            pytest.skip(f"no local TEI: {error}")
        engine = LLMEngine(
            dict.fromkeys(Tier, OpenaiDriver(http, **openai_args())),
            embed,
            f"tei:{conf['model']}",
            1024,
            retries=2,
            cache=model_cache(),
        )
        vectors = await engine.embed(["póliza de auto", "¿qué cubre el todo riesgo?"], Purpose.DOCUMENT)
    assert (vectors.dimensions, len(vectors.vectors), {len(v) for v in vectors.vectors}) == (1024, 2, {1024})
