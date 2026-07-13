"""Real-API demonstration of persisted, isolated Session conversations."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from app.agent import AgentRuntime, AgentRuntimeError, SessionAgentService, SessionChatResult
from app.llm import LLMConfig, LLMConfigurationError, OpenAICompatibleLLMClient
from app.memory import MemoryStoreError, SQLiteStore
from app.tools import create_default_registry


DEMO_DB_PATH = Path("data/session-demo.db")
DEMO_USER_ID = "demo-user"
WEATHER_SESSION_ID = "weather-window"
REPORT_SESSION_ID = "report-window"


class SessionDemoValidationError(RuntimeError):
    """Raised when the final persisted window state is not isolated."""


def main() -> int:
    """Run two isolated conversations, recreate the stack, and continue them."""
    client: Optional[OpenAICompatibleLLMClient] = None
    try:
        _reset_demo_database()
        config = LLMConfig.from_env()
        store = SQLiteStore(DEMO_DB_PATH)
        store.create_session(
            DEMO_USER_ID,
            WEATHER_SESSION_ID,
            "天气窗口",
        )
        store.create_session(
            DEMO_USER_ID,
            REPORT_SESSION_ID,
            "周报窗口",
        )

        client = OpenAICompatibleLLMClient(config)
        service = _create_service(client, store)
        weather_first = service.chat(
            DEMO_USER_ID,
            WEATHER_SESSION_ID,
            "请使用 search 查询东京天气，并把“出门带伞”添加到当前会话的待办中。",
        )
        report_first = service.chat(
            DEMO_USER_ID,
            REPORT_SESSION_ID,
            "请把“周五前完成周报”添加到当前会话的待办中。",
        )
        _print_turn("weather-window / 第一轮", weather_first)
        _print_turn("report-window / 第一轮", report_first)

        client.close()
        client = None

        reopened_store = SQLiteStore(DEMO_DB_PATH)
        client = OpenAICompatibleLLMClient(config)
        reopened_service = _create_service(client, reopened_store)
        weather_follow_up = reopened_service.chat(
            DEMO_USER_ID,
            WEATHER_SESSION_ID,
            "请列出当前窗口的待办，并告诉我刚才查询的是哪个城市。",
        )
        report_follow_up = reopened_service.chat(
            DEMO_USER_ID,
            REPORT_SESSION_ID,
            "请列出当前窗口的待办。",
        )
        _print_turn("weather-window / 重启后追问", weather_follow_up)
        _print_turn("report-window / 重启后追问", report_follow_up)

        _print_window_state(
            reopened_service,
            reopened_store,
            WEATHER_SESSION_ID,
        )
        _print_window_state(
            reopened_service,
            reopened_store,
            REPORT_SESSION_ID,
        )
        _verify_isolation(reopened_store)
        return 0
    except LLMConfigurationError:
        _print_failure("LLM configuration is missing or invalid.")
        return 1
    except AgentRuntimeError as error:
        _print_failure(str(error))
        return 1
    except MemoryStoreError as error:
        _print_failure(str(error))
        return 1
    except SessionDemoValidationError as error:
        _print_failure(str(error))
        return 1
    except OSError:
        _print_failure("The demo database files could not be prepared.")
        return 1
    finally:
        if client is not None:
            client.close()


def _create_service(
    client: OpenAICompatibleLLMClient,
    store: SQLiteStore,
) -> SessionAgentService:
    registry = create_default_registry(todo_store=store)
    runtime = AgentRuntime(client, registry, max_steps=8)
    return SessionAgentService(runtime, store)


def _reset_demo_database() -> None:
    for path in (
        DEMO_DB_PATH,
        Path("{}-shm".format(DEMO_DB_PATH)),
        Path("{}-wal".format(DEMO_DB_PATH)),
    ):
        if path.exists():
            path.unlink()


def _print_turn(label: str, result: SessionChatResult) -> None:
    print("=== {} ===".format(label))
    print("Final answer: {}".format(result.agent_result.answer))
    print("Loaded history: {}".format(result.loaded_history_count))
    print("LLM calls: {}".format(result.agent_result.total_llm_calls))
    print("Tool calls: {}".format(result.agent_result.total_tool_calls))
    print()


def _print_window_state(
    service: SessionAgentService,
    store: SQLiteStore,
    session_id: str,
) -> None:
    messages = [
        message.to_dict()
        for message in service.get_history(DEMO_USER_ID, session_id)
    ]
    todos = [
        todo.to_dict()
        for todo in store.list_todos(DEMO_USER_ID, session_id)
    ]
    print("=== {} / 保存状态 ===".format(session_id))
    print("Messages:")
    print(json.dumps(messages, ensure_ascii=False, indent=2))
    print("Todos:")
    print(json.dumps(todos, ensure_ascii=False, indent=2))
    print()


def _verify_isolation(store: SQLiteStore) -> None:
    weather_contents = [
        todo.content
        for todo in store.list_todos(DEMO_USER_ID, WEATHER_SESSION_ID)
    ]
    report_contents = [
        todo.content
        for todo in store.list_todos(DEMO_USER_ID, REPORT_SESSION_ID)
    ]
    weather_ok = "出门带伞" in weather_contents and "周五前完成周报" not in weather_contents
    report_ok = "周五前完成周报" in report_contents and "出门带伞" not in report_contents

    print("=== 窗口隔离验证 ===")
    print("weather-window 中应包含“出门带伞”: {}".format(weather_ok))
    print("report-window 中应包含“周五前完成周报”: {}".format(report_ok))
    if not weather_ok or not report_ok:
        raise SessionDemoValidationError("Persisted Todo window isolation check failed.")


def _print_failure(message: str) -> None:
    print("Session memory demo failed: {}".format(message), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
