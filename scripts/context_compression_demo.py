"""Real-API demonstration of Session history Context compression."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from app.agent import AgentRuntime, AgentRuntimeError, SessionAgentService
from app.llm import LLMConfig, LLMConfigurationError, OpenAICompatibleLLMClient
from app.memory import (
    BasicContextManager,
    ContextCompressionError,
    ContextConfig,
    MemoryStoreError,
    SQLiteStore,
)
from app.tools import create_default_registry


DEMO_DB_PATH = Path("data/context-demo.db")
DEMO_USER_ID = "context-demo-user"
DEMO_SESSION_ID = "long-window"


class ContextDemoValidationError(RuntimeError):
    """Raised when the demo's persistence invariants are not satisfied."""


def main() -> int:
    """Seed long history, run one real turn, and display Context statistics."""
    client: Optional[OpenAICompatibleLLMClient] = None
    try:
        _reset_demo_database()
        config = LLMConfig.from_env()
        store = SQLiteStore(DEMO_DB_PATH)
        store.create_session(
            DEMO_USER_ID,
            DEMO_SESSION_ID,
            "长对话压缩演示",
        )
        _seed_demo_history(store)

        client = OpenAICompatibleLLMClient(config)
        runtime = AgentRuntime(
            client,
            create_default_registry(todo_store=store),
            max_steps=8,
        )
        manager = BasicContextManager(
            ContextConfig(
                max_messages=8,
                recent_messages=4,
                max_chars=1600,
                summary_max_chars=800,
                per_message_chars=120,
            )
        )
        service = SessionAgentService(
            runtime,
            store,
            context_manager=manager,
        )
        result = service.chat(
            DEMO_USER_ID,
            DEMO_SESSION_ID,
            "根据之前的对话，请告诉我较早提到的城市、项目代号，以及最近的待办是什么。",
        )

        _validate_persisted_history(store)
        context = result.context_result
        if context is None:
            raise ContextDemoValidationError("Context result is unexpectedly missing.")

        print("=== Context Compression Demo ===")
        print("Final answer: {}".format(result.agent_result.answer))
        print("loaded_history_count: {}".format(result.loaded_history_count))
        print("context compressed: {}".format(result.context_compressed))
        print("original_message_count: {}".format(context.original_message_count))
        print("output_message_count: {}".format(context.output_message_count))
        print("summarized_message_count: {}".format(context.summarized_message_count))
        print("retained_recent_count: {}".format(context.retained_recent_count))
        print("original_char_count: {}".format(context.original_char_count))
        print("output_char_count: {}".format(context.output_char_count))
        print("Runtime LLM calls: {}".format(result.agent_result.total_llm_calls))
        print("Runtime tool calls: {}".format(result.agent_result.total_tool_calls))
        print(
            "Database message count: {}".format(
                store.count_messages(DEMO_USER_ID, DEMO_SESSION_ID)
            )
        )
        print("Database contains Context summary: False")
        return 0
    except LLMConfigurationError:
        _print_failure("LLM configuration is missing or invalid.")
        return 1
    except ContextCompressionError as error:
        _print_failure(str(error))
        return 1
    except AgentRuntimeError as error:
        _print_failure(str(error))
        return 1
    except MemoryStoreError as error:
        _print_failure(str(error))
        return 1
    except ContextDemoValidationError as error:
        _print_failure(str(error))
        return 1
    except OSError:
        _print_failure("The Context demo database files could not be prepared.")
        return 1
    finally:
        if client is not None:
            client.close()


def _seed_demo_history(store: SQLiteStore) -> None:
    turns = [
        ("请记住，较早提到的城市是东京。", "好的，较早提到的城市是东京。"),
        ("请记住，项目代号是 Atlas。", "好的，项目代号是 Atlas。"),
        ("我们正在搭建最小 Agent Runtime。", "已记录项目背景。"),
        ("第一阶段完成 FastAPI 骨架。", "已记录第一阶段进度。"),
        ("第二阶段完成工具系统。", "已记录第二阶段进度。"),
        ("第三阶段完成 LLM Client。", "已记录第三阶段进度。"),
        ("第四阶段完成 Runtime Loop。", "已记录第四阶段进度。"),
        ("第五阶段完成 SQLite Session。", "已记录第五阶段进度。"),
        ("第六阶段开始管理 Context。", "已记录第六阶段进度。"),
        ("压缩规则使用确定性字符控制。", "已记录压缩规则。"),
        ("摘要不会写回数据库。", "已记录数据库约束。"),
        ("最新待办是完成 README。", "已记录：最新待办是完成 README。"),
    ]
    for user_content, assistant_content in turns:
        store.add_exchange(
            DEMO_USER_ID,
            DEMO_SESSION_ID,
            user_content,
            assistant_content,
        )


def _validate_persisted_history(store: SQLiteStore) -> None:
    messages = store.list_messages(DEMO_USER_ID, DEMO_SESSION_ID)
    if len(messages) != 26:
        raise ContextDemoValidationError(
            "Expected 26 real database messages after the demo turn."
        )
    if any(message.content.startswith("【较早会话摘要】") for message in messages):
        raise ContextDemoValidationError(
            "A generated Context summary was unexpectedly persisted."
        )


def _reset_demo_database() -> None:
    for path in (
        DEMO_DB_PATH,
        Path("{}-shm".format(DEMO_DB_PATH)),
        Path("{}-wal".format(DEMO_DB_PATH)),
    ):
        if path.exists():
            path.unlink()


def _print_failure(message: str) -> None:
    print("Context compression demo failed: {}".format(message), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
