"""tests/unit/e_infra/engines/llm: the model agent — a tier answers a typed contract or a typed error; embeddings
carry their embedder.

The schema sent is the contract's, references inlined and the keywords constrained decoders refuse left out; the
contract itself, those keywords included, is held on decode. A reply that does not decode is sent back with the error,
LLM_RETRIES times, then `InvalidOutputError`. What the models answer is kept by content: RECORD reads first, REPLAY only
reads, OFF never meets the cache."""

import asyncio
from typing import TYPE_CHECKING, Annotated, Any

import msgspec
import pytest

from e_infra.engines.llm import LOOSE, LLMEngine, ModelCache, Purpose, Vectors
from e_infra.infra.config.engines import CacheMode, Tier
from e_infra.infra.errors import CacheError, InvalidOutputError, ModelError, ReplayMissError
from support.cache import MemoryCache, model_cache
from support.models import ScriptedEmbed, ScriptedModel

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs


class Cover(msgspec.Struct, frozen=True):
    code: Annotated[str, msgspec.Meta(pattern="^[a-z]+$")]
    limits: frozenset[int] = frozenset()


class Code(msgspec.Struct, frozen=True):
    code: str
    covers: list[Cover]


GOOD = {"code": "a", "covers": [{"code": "b", "limits": [1, 2]}]}


def engine(
    *replies: Any, retries: int = 2, width: int = 3, cache: ModelCache | None = None
) -> tuple[LLMEngine, ScriptedModel]:
    model = ScriptedModel(*replies)
    tiers = dict.fromkeys(Tier, model)
    return LLMEngine(tiers, ScriptedEmbed(width), "fake:model", 3, retries=retries, cache=cache or model_cache()), model


##### RUN #####
async def test_run_schema_not_an_object_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("e_infra.engines.llm.msgspec.json.schema", lambda _: {"$ref": "#/$defs/x", "$defs": {"x": []}})
    llm, model = engine(GOOD)
    with pytest.raises(ModelError, match="no object schema"):
        await llm.run(Tier.LOW, "s", "p", Code)
    assert model.calls == []


async def test_run_answers_the_contract_type() -> None:
    llm, model = engine(GOOD)
    assert await llm.run(Tier.MEDIUM, "be exact", "read", Code) == Code(
        code="a", covers=[Cover(code="b", limits=frozenset({1, 2}))]
    )
    assert [(system, prompt) for system, prompt, _ in model.calls] == [("be exact", "read")]


async def test_run_sends_the_schema_inlined_and_without_the_loose_keywords() -> None:
    llm, model = engine(GOOD)
    await llm.run(Tier.LOW, "s", "p", Code)
    sent = msgspec.json.encode(model.calls[0][2]).decode()
    assert ("$ref" in sent, "$defs" in sent, any(word in sent for word in LOOSE)) == (False, False, False)
    assert model.calls[0][2]["properties"]["covers"]["items"]["properties"]["code"] == {"type": "string"}
    assert model.calls[0][2]["properties"]["covers"]["items"]["properties"]["limits"]["type"] == "array"


async def test_run_holds_the_loose_keywords_on_decode() -> None:
    """`pattern` is not sent, yet a reply that breaks it is refused and sent back."""
    llm, model = engine({"code": "a", "covers": [{"code": "B1"}]}, GOOD, retries=1)
    assert (await llm.run(Tier.LOW, "s", "p", Code)).covers[0].code == "b"
    assert "did not decode" in model.calls[1][1]


async def test_run_sends_the_error_back_then_answers() -> None:
    llm, model = engine({"code": 1}, GOOD)
    assert (await llm.run(Tier.HIGH, "s", "p", Code)).code == "a"
    assert (len(model.calls), "Expected `str`" in model.calls[1][1], model.calls[1][1].startswith("p")) == (
        2,
        True,
        True,
    )


async def test_run_out_of_retries_is_an_invalid_output() -> None:
    llm, model = engine({"code": 1}, {"code": 2}, {"code": 3}, retries=2)
    with pytest.raises(InvalidOutputError, match="3 replies"):
        await llm.run(Tier.HIGH, "s", "p", Code)
    assert len(model.calls) == 3


async def test_run_each_tier_reaches_its_own_model() -> None:
    models = {tier: ScriptedModel(GOOD, name=str(tier)) for tier in Tier}
    llm = LLMEngine(models, ScriptedEmbed(), "fake:model", 3, retries=2, cache=model_cache())
    await llm.run(Tier.LOW, "s", "p", Code)
    assert [len(models[tier].calls) for tier in Tier] == [0, 0, 1]


async def test_run_a_tier_without_a_model_is_refused_at_build() -> None:
    with pytest.raises(ModelError, match="low"):
        LLMEngine(
            {Tier.HIGH: ScriptedModel(), Tier.MEDIUM: ScriptedModel()},
            ScriptedEmbed(),
            "fake:model",
            3,
            retries=2,
            cache=model_cache(),
        )


##### EMBED #####
@pytest.mark.parametrize(("purpose", "query"), [(Purpose.QUERY, True), (Purpose.DOCUMENT, False)])
async def test_embed_carries_its_embedder_and_purpose(purpose: Purpose, query: bool) -> None:
    embed = ScriptedEmbed()
    llm = LLMEngine(dict.fromkeys(Tier, ScriptedModel()), embed, "fake:model", 3, retries=2, cache=model_cache())
    vectors = await llm.embed(["a", "b"], purpose)
    assert vectors == Vectors(embedder="fake:model", dimensions=3, vectors=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    assert embed.queries == [query]


async def test_embed_a_width_other_than_declared_is_refused() -> None:
    llm, _ = engine(width=4)
    with pytest.raises(ModelError, match="4"):
        await llm.embed(["a"], Purpose.DOCUMENT)


async def test_embed_nothing_is_no_call() -> None:
    llm, _ = engine()
    assert (await llm.embed([], Purpose.DOCUMENT)).vectors == ()


##### CACHE #####
async def test_cache_record_a_second_run_asks_no_model() -> None:
    answers = MemoryCache[Any]()
    llm, model = engine(GOOD, cache=ModelCache(answers, MemoryCache[list[float]](), CacheMode.RECORD))
    first = await llm.run(Tier.LOW, "s", "p", Code)
    assert (await llm.run(Tier.LOW, "s", "p", Code), len(model.calls), answers.writes) == (first, 1, 1)


async def test_cache_record_keeps_the_reply_that_decoded() -> None:
    """The retries are paid once: the reply kept is the one that met the contract."""
    cache = model_cache(CacheMode.RECORD)
    llm, model = engine({"code": 1}, GOOD, cache=cache)
    await llm.run(Tier.LOW, "s", "p", Code)
    assert ((await llm.run(Tier.LOW, "s", "p", Code)).code, len(model.calls)) == ("a", 2)


@pytest.mark.parametrize(
    ("instructions", "prompt", "output"),
    [("other", "p", Code), ("s", "other", Code), ("s", "p", Cover)],
    ids=["instructions", "prompt", "contract"],
)
async def test_cache_record_any_input_changed_is_a_new_key(instructions: str, prompt: str, output: type) -> None:
    llm, model = engine(GOOD, {"code": "b", "covers": []}, cache=model_cache(CacheMode.RECORD))
    await llm.run(Tier.LOW, "s", "p", Code)
    await llm.run(Tier.LOW, instructions, prompt, output)
    assert len(model.calls) == 2


async def test_cache_record_two_misses_at_once_pay_one_call() -> None:
    llm, model = engine(GOOD, cache=model_cache(CacheMode.RECORD))
    first, second = await asyncio.gather(*(llm.run(Tier.LOW, "s", "p", Code) for _ in range(2)))
    assert (first == second, len(model.calls)) == (True, 1)


async def test_cache_replay_answers_what_record_kept_and_refuses_the_rest() -> None:
    recorded = model_cache(CacheMode.RECORD)
    await engine(GOOD, cache=recorded)[0].run(Tier.LOW, "s", "p", Code)
    llm, model = engine(cache=ModelCache(recorded.answers, recorded.vectors, CacheMode.REPLAY))
    assert (await llm.run(Tier.LOW, "s", "p", Code)).code == "a"
    with pytest.raises(ReplayMissError, match="REPLAY"):
        await llm.run(Tier.LOW, "s", "unseen", Code)
    assert model.calls == []


async def test_cache_off_never_meets_the_cache() -> None:
    answers, vectors = MemoryCache[Any](), MemoryCache[list[float]]()
    llm, model = engine(GOOD, GOOD, cache=ModelCache(answers, vectors, CacheMode.OFF))
    await llm.run(Tier.LOW, "s", "p", Code)
    await llm.run(Tier.LOW, "s", "p", Code)
    await llm.embed(["a"], Purpose.DOCUMENT)
    assert (len(model.calls), answers.reads, vectors.reads) == (2, 0, 0)


async def test_cache_record_a_cache_down_is_said_and_the_model_answers(logs: Logs) -> None:
    answers = MemoryCache[Any]()
    answers.down = True
    llm, model = engine(GOOD, cache=ModelCache(answers, MemoryCache[list[float]](), CacheMode.RECORD))
    assert ((await llm.run(Tier.LOW, "s", "p", Code)).code, len(model.calls)) == ("a", 1)
    assert logs.at("warning") == ["llm cache read failed", "llm cache write failed"]


async def test_cache_replay_a_cache_down_is_raised() -> None:
    answers = MemoryCache[Any]()
    answers.down = True
    llm, model = engine(GOOD, cache=ModelCache(answers, MemoryCache[list[float]](), CacheMode.REPLAY))
    with pytest.raises(CacheError):
        await llm.run(Tier.LOW, "s", "p", Code)
    assert model.calls == []


async def test_cache_record_embeds_each_text_it_lacks_once() -> None:
    embed = ScriptedEmbed()
    vectors = MemoryCache[list[float]]()
    cache = ModelCache(MemoryCache[Any](), vectors, CacheMode.RECORD)
    llm = LLMEngine(dict.fromkeys(Tier, ScriptedModel()), embed, "fake:model", 3, retries=2, cache=cache)
    assert (await llm.embed(["a", "b", "a"], Purpose.DOCUMENT)).vectors == ((0.0,) * 3, (1.0,) * 3, (0.0,) * 3)
    assert (await llm.embed(["b", "c"], Purpose.DOCUMENT)).vectors == ((1.0,) * 3, (0.0,) * 3)
    assert (await llm.embed(["c", "a"], Purpose.DOCUMENT)).vectors == ((0.0,) * 3, (0.0,) * 3)
    assert (embed.queries, vectors.writes) == ([False, False], 3)


async def test_cache_record_a_query_and_a_passage_are_two_keys() -> None:
    embed = ScriptedEmbed()
    llm = LLMEngine(
        dict.fromkeys(Tier, ScriptedModel()), embed, "fake:model", 3, retries=2, cache=model_cache(CacheMode.RECORD)
    )
    await llm.embed(["a"], Purpose.DOCUMENT)
    await llm.embed(["a"], Purpose.QUERY)
    assert embed.queries == [False, True]


async def test_cache_replay_a_vector_it_lacks_is_refused() -> None:
    vectors = MemoryCache[list[float]]()
    embed = ScriptedEmbed()
    record = LLMEngine(
        dict.fromkeys(Tier, ScriptedModel()), embed, "fake:model", 3, retries=2,
        cache=ModelCache(MemoryCache[Any](), vectors, CacheMode.RECORD),
    )  # fmt: skip
    await record.embed(["a"], Purpose.DOCUMENT)
    replay = LLMEngine(
        dict.fromkeys(Tier, ScriptedModel()), embed, "fake:model", 3, retries=2,
        cache=ModelCache(MemoryCache[Any](), vectors, CacheMode.REPLAY),
    )  # fmt: skip
    assert (await replay.embed(["a"], Purpose.DOCUMENT)).vectors == ((0.0,) * 3,)
    with pytest.raises(ReplayMissError, match="1 of 2"):
        await replay.embed(["a", "b"], Purpose.DOCUMENT)
    assert embed.queries == [False]
