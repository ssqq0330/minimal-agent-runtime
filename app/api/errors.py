"""Safe, uniform HTTP error mapping for application-layer exceptions."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.security import sanitize_error_message

from app.agent import (
    AgentDecisionError,
    AgentInputError,
    AgentLLMError,
    AgentMaxStepsError,
)
from app.llm import LLMConfigurationError
from app.memory import (
    ContextCompressionError,
    DuplicateSessionError,
    MemoryStoreError,
    SessionNotFoundError,
    TodoNotFoundError,
)
from app.observability import (
    TraceNotFoundError,
    TracePersistenceError,
    TraceValidationError,
)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": sanitize_error_message(message)}},
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Register explicit mappings without exposing exception details."""
    mappings = [
        (DuplicateSessionError, 409, "session_conflict", "Session 已存在"),
        (SessionNotFoundError, 404, "session_not_found", "Session 不存在"),
        (TodoNotFoundError, 404, "todo_not_found", "Todo 不存在"),
        (AgentInputError, 422, "agent_input_invalid", "Agent 输入无效"),
        (AgentLLMError, 502, "llm_request_failed", "LLM 请求失败"),
        (AgentDecisionError, 502, "agent_response_invalid", "Agent 响应无效"),
        (AgentMaxStepsError, 508, "agent_max_steps", "Agent 达到最大执行步数"),
        (
            ContextCompressionError,
            500,
            "context_compression_failed",
            "Context 构建失败",
        ),
        (TraceNotFoundError, 404, "trace_not_found", "Trace 不存在"),
        (TraceValidationError, 422, "trace_invalid", "Trace 请求无效"),
        (TracePersistenceError, 500, "trace_persistence_failed", "Trace 存储失败"),
        (LLMConfigurationError, 503, "llm_unavailable", "LLM 服务未配置"),
        (MemoryStoreError, 500, "database_error", "数据库操作失败"),
        (ValueError, 422, "invalid_request", "请求参数无效"),
    ]
    for exception_type, status_code, code, message in mappings:
        app.add_exception_handler(
            exception_type,
            _handler(status_code, code, message),
        )

    async def validation_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request, error
        return error_response(422, "validation_error", "请求参数校验失败")

    app.add_exception_handler(RequestValidationError, validation_handler)

    async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
        del request, error
        return error_response(500, "internal_error", "服务器内部错误")

    app.add_exception_handler(Exception, unexpected_handler)


def _handler(
    status_code: int,
    code: str,
    message: str,
):
    async def handle(request: Request, error: Exception) -> JSONResponse:
        del request, error
        return error_response(status_code, code, message)

    return handle


__all__ = ["error_response", "install_exception_handlers", "sanitize_error_message"]
