"""Chat model providers behind one small interface, selected with LLM_PROVIDER."""

import logging
from typing import Protocol, TypedDict, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import Settings

logger = logging.getLogger(__name__)

OutputT = TypeVar("OutputT", bound=BaseModel)


class Message(TypedDict):
    role: str  # "user" or "assistant"
    content: str


class LLMUnavailableError(RuntimeError):
    """The model could not be reached (network, quota, outage...)."""


class ChatModel(Protocol):
    def parse(
        self, system: str, messages: list[Message], output_format: type[OutputT]
    ) -> OutputT | None:
        """Return a validated instance of output_format, or None if the model gave none."""
        ...


class AnthropicChatModel:
    def __init__(self, settings: Settings) -> None:
        if settings.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
        self._model = settings.chat_model
        self._max_tokens = settings.max_output_tokens

    def parse(
        self, system: str, messages: list[Message], output_format: type[OutputT]
    ) -> OutputT | None:
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
                output_format=output_format,
            )
        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            raise LLMUnavailableError("The AI service is temporarily unavailable.") from exc

        if response.parsed_output is None:
            logger.warning("No structured output (stop_reason=%s)", response.stop_reason)
        return response.parsed_output


class OpenAIChatModel:
    """Optional provider. Requires `pip install openai` and LLM_PROVIDER=openai."""

    def __init__(self, settings: Settings) -> None:
        import openai  # imported lazily so the default install doesn't need it

        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is not set")
        self._openai = openai
        self._client = openai.OpenAI(api_key=settings.openai_api_key.get_secret_value())
        self._model = settings.chat_model
        self._max_tokens = settings.max_output_tokens

    def parse(
        self, system: str, messages: list[Message], output_format: type[OutputT]
    ) -> OutputT | None:
        try:
            completion = self._client.chat.completions.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "system", "content": system}, *messages],
                response_format=output_format,
            )
        except self._openai.OpenAIError as exc:
            logger.error("OpenAI API error: %s", exc)
            raise LLMUnavailableError("The AI service is temporarily unavailable.") from exc
        return completion.choices[0].message.parsed


def create_chat_model(settings: Settings) -> ChatModel:
    if settings.llm_provider == "openai":
        return OpenAIChatModel(settings)
    return AnthropicChatModel(settings)
