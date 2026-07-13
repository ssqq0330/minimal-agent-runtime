"""OpenAI-compatible Chat Completions client built directly on httpx."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Dict, List, Optional, Type

import httpx
from dotenv import load_dotenv


class LLMError(Exception):
    """Base exception for all LLM client errors."""


class LLMConfigurationError(LLMError):
    """Raised when required LLM configuration is missing or invalid."""


class LLMRequestError(LLMError):
    """Raised when an HTTP request cannot be completed successfully."""


class LLMResponseError(LLMError):
    """Raised when an API response has invalid content or structure."""


@dataclass
class LLMConfig:
    """Configuration for an OpenAI-compatible Chat Completions endpoint."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 60.0
    temperature: float = 0.0

    def __post_init__(self) -> None:
        self.api_key = self._require_text(self.api_key, "LLM_API_KEY")
        self.base_url = self._require_text(self.base_url, "LLM_BASE_URL").rstrip("/")
        self.model = self._require_text(self.model, "LLM_MODEL")
        if not self.base_url:
            raise LLMConfigurationError("LLM_BASE_URL is required.")

        self.timeout_seconds = self._parse_number(
            self.timeout_seconds,
            "LLM_TIMEOUT_SECONDS",
        )
        if self.timeout_seconds <= 0:
            raise LLMConfigurationError("LLM_TIMEOUT_SECONDS must be greater than 0.")

        self.temperature = self._parse_number(
            self.temperature,
            "LLM_TEMPERATURE",
        )

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load LLM configuration from the project-root .env and environment."""
        project_root = Path(__file__).resolve().parents[2]
        load_dotenv(dotenv_path=project_root / ".env", override=False)
        return cls(
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", ""),
            model=os.getenv("LLM_MODEL", ""),
            timeout_seconds=os.getenv("LLM_TIMEOUT_SECONDS", "60"),
            temperature=os.getenv("LLM_TEMPERATURE", "0"),
        )

    @property
    def chat_completions_url(self) -> str:
        """Return the normalized Chat Completions endpoint URL."""
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return "{}/chat/completions".format(self.base_url)

    @staticmethod
    def _require_text(value: Any, variable_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise LLMConfigurationError("{} is required.".format(variable_name))
        return value.strip()

    @staticmethod
    def _parse_number(value: Any, variable_name: str) -> float:
        if isinstance(value, bool):
            raise LLMConfigurationError("{} must be a valid number.".format(variable_name))
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise LLMConfigurationError(
                "{} must be a valid number.".format(variable_name)
            ) from None
        if not math.isfinite(number):
            raise LLMConfigurationError("{} must be a finite number.".format(variable_name))
        return number


@dataclass
class LLMResponse:
    """Normalized content and metadata returned by the LLM service."""

    content: str
    model: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    raw_response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation suitable for application code."""
        return {
            "content": self.content,
            "model": self.model,
            "usage": self.usage,
            "raw_response": self.raw_response,
        }


class OpenAICompatibleLLMClient:
    """Synchronous HTTP client for OpenAI-compatible Chat Completions APIs."""

    _ALLOWED_ROLES = {"system", "user", "assistant"}

    def __init__(
        self,
        config: LLMConfig,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.config = config
        self._owns_http_client = http_client is None
        self._http_client = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=config.timeout_seconds)
        )

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """Send validated messages and return a normalized LLM response."""
        self._validate_messages(messages)
        headers = {
            "Authorization": "Bearer {}".format(self.config.api_key),
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }

        try:
            response = self._http_client.post(
                self.config.chat_completions_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise LLMRequestError("LLM request timed out.") from error
        except httpx.HTTPStatusError as error:
            raise LLMRequestError(
                "LLM request failed with HTTP status {}.".format(
                    error.response.status_code
                )
            ) from error
        except httpx.RequestError as error:
            raise LLMRequestError("LLM network request failed.") from error
        except RuntimeError as error:
            raise LLMRequestError("LLM HTTP client is not available.") from error

        try:
            response_data = response.json()
        except ValueError as error:
            raise LLMResponseError("LLM response was not valid JSON.") from error

        return self._parse_response(response_data)

    def close(self) -> None:
        """Close the HTTP client only when this object created it."""
        if self._owns_http_client and not self._http_client.is_closed:
            self._http_client.close()

    def __enter__(self) -> "OpenAICompatibleLLMClient":
        """Return this client for use in a with statement."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Release owned HTTP resources when leaving a with statement."""
        self.close()

    @classmethod
    def _validate_messages(cls, messages: List[Dict[str, str]]) -> None:
        if not isinstance(messages, list):
            raise ValueError("messages must be a list.")
        if not messages:
            raise ValueError("messages must not be empty.")

        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                raise ValueError("messages[{}] must be an object.".format(index))
            if "role" not in message:
                raise ValueError("messages[{}] is missing 'role'.".format(index))
            if "content" not in message:
                raise ValueError("messages[{}] is missing 'content'.".format(index))

            role = message["role"]
            content = message["content"]
            if role not in cls._ALLOWED_ROLES:
                raise ValueError(
                    "messages[{}].role must be system, user, or assistant.".format(
                        index
                    )
                )
            if not isinstance(content, str):
                raise ValueError("messages[{}].content must be a string.".format(index))
            if not content.strip():
                raise ValueError("messages[{}].content must not be empty.".format(index))

    @staticmethod
    def _parse_response(response_data: Any) -> LLMResponse:
        if not isinstance(response_data, dict):
            raise LLMResponseError("LLM response must be a JSON object.")
        if "choices" not in response_data:
            raise LLMResponseError("LLM response is missing 'choices'.")

        choices = response_data["choices"]
        if not isinstance(choices, list):
            raise LLMResponseError("LLM response 'choices' must be a list.")
        if not choices:
            raise LLMResponseError("LLM response 'choices' must not be empty.")
        if not isinstance(choices[0], dict):
            raise LLMResponseError("LLM response first choice must be an object.")
        if "message" not in choices[0]:
            raise LLMResponseError("LLM response choice is missing 'message'.")

        message = choices[0]["message"]
        if not isinstance(message, dict):
            raise LLMResponseError("LLM response 'message' must be an object.")
        if "content" not in message:
            raise LLMResponseError("LLM response message is missing 'content'.")

        content = message["content"]
        if not isinstance(content, str):
            raise LLMResponseError("LLM response 'content' must be a string.")
        if not content.strip():
            raise LLMResponseError("LLM response 'content' must not be empty.")

        if "usage" in response_data and not isinstance(response_data["usage"], dict):
            raise LLMResponseError("LLM response 'usage' must be an object.")
        if "model" in response_data and not isinstance(response_data["model"], str):
            raise LLMResponseError("LLM response 'model' must be a string.")

        return LLMResponse(
            content=content,
            model=response_data.get("model"),
            usage=response_data.get("usage"),
            raw_response=response_data,
        )
