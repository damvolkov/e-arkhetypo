"""providers/drivers/llm/google: a Gemini model behind `LLMPort` — the Gemini API by key, or Vertex by ADC, one client.

The answer is constrained by the caller's JSON schema (`response_json_schema`), decoded here; how a reply ends decides
its error: cut at the ceiling is a `TruncatedError`, declined (a safety finish, a blocked prompt) a `RefusalError`, any
other failure — the SDK's own included — a `ModelError`, so the engine above reads one vocabulary whoever answers.
No sampling parameter is sent: Gemini answers best with its own."""

from typing import TYPE_CHECKING, ClassVar, Final, Self

import aiohttp
import msgspec
from google.genai import Client, errors, types

from e_infra.infra.errors import ModelError, RefusalError, TruncatedError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, Opened, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import SecretStr

    from e_infra.infra.payload import JSON

### the finishes that are a refusal, not an answer: the model, or its filter, declined.
REFUSED: Final[frozenset[types.FinishReason]] = frozenset(
    {
        types.FinishReason.SAFETY,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.RECITATION,
        types.FinishReason.SPII,
    }
)


### what the SDK raises when Google refuses (`APIError`) or does not answer (its aiohttp transport): the port's error.
FAILURES: Final[tuple[type[Exception], ...]] = (errors.APIError, aiohttp.ClientError, TimeoutError)


class GoogleLLMDriver:
    """One google-genai client behind `LLMPort`: Gemini API or Vertex, the model the settings name."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("google-genai", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)
    client = Opened[Client](ModelError)

    __slots__ = ("_api_key", "_client", "_enterprise", "_location", "_max_tokens", "_model", "_project", "_timeout_ms")

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        enterprise: bool,
        project: str | None,
        location: str,
        model: str,
        timeout_ms: int,
        max_tokens: int,
    ) -> None:
        (
            self._api_key,
            self._enterprise,
            self._project,
            self._location,
            self._model,
            self._timeout_ms,
            self._max_tokens,
        ) = api_key, enterprise, project, location, model, timeout_ms, max_tokens
        self._client: Client | None = None

    ##### PRIVATE #####

    def _structured_config(self, system: str, schema: Mapping[str, JSON]) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=dict(schema),
            max_output_tokens=self._max_tokens,
        )

    @staticmethod
    def _structured_answer(response: types.GenerateContentResponse) -> JSON:
        """The reply decoded, or the error its ending names."""
        finish = next((each.finish_reason for each in response.candidates or ()), None)
        feedback = response.prompt_feedback
        blocked = feedback.block_reason if feedback else None
        match (blocked, finish):
            case (types.BlockedReason() as reason, _):
                msg = f"the prompt was blocked: {reason}"
                raise RefusalError(msg)
            case (_, types.FinishReason.MAX_TOKENS):
                msg = f"the answer was cut at GENAI_MAX_TOKENS: …{(response.text or '')[-160:]!r}"
                raise TruncatedError(msg)
            case (_, reason) if reason in REFUSED:
                msg = f"the model declined: {reason}"
                raise RefusalError(msg)
            case _:
                try:
                    return msgspec.json.decode(response.text or "")
                except msgspec.DecodeError as error:
                    msg = f"the answer is not JSON (finish {finish}): …{(response.text or '')[-160:]!r}"
                    raise ModelError(msg) from error

    ############################################################

    ##### PUBLIC #####

    @property
    def model(self) -> str:
        return self._model

    async def __aenter__(self) -> Self:
        options = types.HttpOptions(timeout=self._timeout_ms)
        key = self._api_key.get_secret_value() if self._api_key is not None else None
        self._client = (
            Client(enterprise=True, project=self._project, location=self._location, http_options=options)
            if self._enterprise
            else Client(enterprise=False, api_key=key, http_options=options)
        )
        logger.info("google-genai opened", model=self._model, enterprise=self._enterprise)
        return self

    async def __aexit__(self, *exc: object) -> None:
        client, self._client = self._client, None
        _ = client is not None and await client.aio.aclose()
        logger.info("google-genai closed")

    async def health(self) -> bool:
        """The model, as the service describes it: the key or the credentials and the model at once."""
        try:
            await self.client.aio.models.get(model=self._model)
        except FAILURES as error:
            logger.warning("google-genai unhealthy", error=str(error))
            raise ModelError(str(error)) from error
        return True

    async def structured(self, system: str, prompt: str, schema: Mapping[str, JSON]) -> JSON:
        """The model's answer to `prompt` under `system`, decoded from JSON constrained by `schema`."""
        logger.debug("google-genai structured", model=self._model, prompt_chars=len(prompt))
        try:
            response = await self.client.aio.models.generate_content(
                model=self._model, contents=prompt, config=self._structured_config(system, schema)
            )
        except FAILURES as error:
            logger.error("google-genai failed", model=self._model, error=str(error))
            raise ModelError(str(error)) from error
        return self._structured_answer(response)
