"""Core self-managed Agent loop for LLM decisions and tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agent.parser import AgentDecision, AgentOutputParseError, parse_llm_output
from app.agent.prompts import build_agent_system_prompt, build_tool_result_message
from app.llm import (
    LLMConfigurationError,
    LLMRequestError,
    LLMResponse,
    LLMResponseError,
    OpenAICompatibleLLMClient,
)
from app.tools import ToolContext, ToolRegistry


class AgentRuntimeError(Exception):
    """Base exception for Agent Runtime failures."""


class AgentInputError(AgentRuntimeError):
    """Raised when user input, context, or history is invalid."""


class AgentMaxStepsError(AgentRuntimeError):
    """Raised when the Agent does not return final within the step limit."""


class AgentLLMError(AgentRuntimeError):
    """Raised when LLM configuration, request, or response handling fails."""


class AgentDecisionError(AgentRuntimeError):
    """Raised when model output cannot be used as an Agent decision."""


@dataclass
class AgentStep:
    """Observable summary of one LLM decision and its tool results."""

    step_number: int
    decision_type: str
    reasoning_summary: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    model: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable step summary without private model reasoning."""
        return {
            "step_number": self.step_number,
            "decision_type": self.decision_type,
            "reasoning_summary": self.reasoning_summary,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "model": self.model,
        }


@dataclass
class AgentRunResult:
    """Final answer and in-memory trace for one Agent Runtime invocation."""

    answer: str
    steps: List[AgentStep]
    messages: List[Dict[str, str]]
    total_llm_calls: int
    total_tool_calls: int
    stopped_reason: str = "final"

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable result for future APIs and trace views."""
        return {
            "answer": self.answer,
            "steps": [step.to_dict() for step in self.steps],
            "messages": self.messages,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "stopped_reason": self.stopped_reason,
        }


class AgentRuntime:
    """Coordinate LLM decisions and registered tools until a final answer."""

    def __init__(
        self,
        llm_client: OpenAICompatibleLLMClient,
        tool_registry: ToolRegistry,
        max_steps: int = 8,
    ) -> None:
        if llm_client is None:
            raise ValueError("llm_client is required.")
        if tool_registry is None:
            raise ValueError("tool_registry is required.")
        if not isinstance(max_steps, int) or isinstance(max_steps, bool):
            raise ValueError("max_steps must be an integer greater than 0.")
        if max_steps <= 0:
            raise ValueError("max_steps must be greater than 0.")

        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.max_steps = max_steps
        self._secrets = self._discover_secrets(llm_client)

    def run(
        self,
        user_input: str,
        context: ToolContext,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AgentRunResult:
        """Run the Agent loop until final output or the configured step limit."""
        validated_history = self._validate_inputs(user_input, context, history)
        system_prompt = build_agent_system_prompt(
            self.tool_registry.get_tool_schemas()
        )
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            *validated_history,
            {"role": "user", "content": user_input},
        ]
        steps: List[AgentStep] = []
        total_llm_calls = 0
        total_tool_calls = 0

        for step_number in range(1, self.max_steps + 1):
            response = self._complete(messages)
            total_llm_calls += 1
            decision = self._parse_decision(response.content)
            messages.append({"role": "assistant", "content": response.content})

            if decision.is_final:
                steps.append(
                    AgentStep(
                        step_number=step_number,
                        decision_type="final",
                        reasoning_summary=self._redact_text(
                            decision.reasoning_summary
                        ),
                        tool_calls=[],
                        tool_results=[],
                        model=self._redact_optional_text(response.model),
                    )
                )
                return AgentRunResult(
                    answer=self._redact_text(decision.answer or ""),
                    steps=steps,
                    messages=self._redact_messages(messages),
                    total_llm_calls=total_llm_calls,
                    total_tool_calls=total_tool_calls,
                )

            if not decision.requires_tools:
                raise AgentDecisionError("LLM returned an unsupported Agent decision.")

            step_tool_calls: List[Dict[str, Any]] = []
            step_tool_results: List[Dict[str, Any]] = []
            for tool_call in decision.tool_calls:
                tool_result = self.tool_registry.execute(
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                    context=context,
                )
                total_tool_calls += 1
                result_dict = tool_result.to_dict()
                tool_call_dict = tool_call.to_dict()
                result_record = {
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "result": result_dict,
                }
                step_tool_calls.append(self._redact_data(tool_call_dict))
                step_tool_results.append(self._redact_data(result_record))
                messages.append(
                    {
                        "role": "user",
                        "content": build_tool_result_message(
                            tool_call_id=tool_call.id,
                            tool_name=tool_call.name,
                            result=result_dict,
                        ),
                    }
                )

            steps.append(
                AgentStep(
                    step_number=step_number,
                    decision_type="tool_call",
                    reasoning_summary=self._redact_text(decision.reasoning_summary),
                    tool_calls=step_tool_calls,
                    tool_results=step_tool_results,
                    model=self._redact_optional_text(response.model),
                )
            )

        raise AgentMaxStepsError(
            "Agent reached max_steps={} without a final answer.".format(
                self.max_steps
            )
        )

    def _complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        try:
            return self.llm_client.complete(messages)
        except LLMConfigurationError as error:
            raise AgentLLMError("LLM configuration failed during Agent run.") from error
        except LLMRequestError as error:
            raise AgentLLMError("LLM request failed during Agent run.") from error
        except LLMResponseError as error:
            raise AgentLLMError("LLM response failed during Agent run.") from error

    @staticmethod
    def _parse_decision(content: str) -> AgentDecision:
        try:
            return parse_llm_output(content)
        except AgentOutputParseError as error:
            raise AgentDecisionError(
                "LLM output could not be parsed as an Agent decision."
            ) from error

    @staticmethod
    def _validate_inputs(
        user_input: str,
        context: ToolContext,
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        if not isinstance(user_input, str):
            raise AgentInputError("user_input must be a string.")
        if not user_input.strip():
            raise AgentInputError("user_input must not be empty.")
        if not isinstance(context, ToolContext):
            raise AgentInputError("context must be a ToolContext.")
        if history is None:
            return []
        if not isinstance(history, list):
            raise AgentInputError("history must be a list.")

        validated_history: List[Dict[str, str]] = []
        for index, message in enumerate(history):
            if not isinstance(message, dict):
                raise AgentInputError(
                    "history[{}] must be an object.".format(index)
                )
            if "role" not in message:
                raise AgentInputError("history[{}] is missing 'role'.".format(index))
            if "content" not in message:
                raise AgentInputError(
                    "history[{}] is missing 'content'.".format(index)
                )
            role = message["role"]
            content = message["content"]
            if role not in {"user", "assistant"}:
                raise AgentInputError(
                    "history[{}].role must be user or assistant; system is not allowed.".format(
                        index
                    )
                )
            if not isinstance(content, str):
                raise AgentInputError(
                    "history[{}].content must be a string.".format(index)
                )
            if not content.strip():
                raise AgentInputError(
                    "history[{}].content must not be empty.".format(index)
                )
            validated_history.append({"role": role, "content": content})
        return validated_history

    @staticmethod
    def _discover_secrets(llm_client: Any) -> List[str]:
        config = getattr(llm_client, "config", None)
        api_key = getattr(config, "api_key", None)
        if isinstance(api_key, str) and api_key:
            return [api_key]
        return []

    def _redact_text(self, value: str) -> str:
        redacted_value = value
        for secret in self._secrets:
            redacted_value = redacted_value.replace(secret, "[REDACTED]")
        return redacted_value

    def _redact_optional_text(self, value: Optional[str]) -> Optional[str]:
        return self._redact_text(value) if value is not None else None

    def _redact_messages(
        self,
        messages: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        return [
            {"role": message["role"], "content": self._redact_text(message["content"])}
            for message in messages
        ]

    def _redact_data(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, list):
            return [self._redact_data(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._redact_data(item)
                for key, item in value.items()
            }
        return value
