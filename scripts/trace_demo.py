"""Real-API demonstration of persistent Session Agent execution Trace events."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from app.agent import AgentRuntime, AgentRuntimeError, SessionAgentService
from app.llm import LLMConfig, LLMConfigurationError, OpenAICompatibleLLMClient
from app.memory import MemoryStoreError, SQLiteStore
from app.observability import AgentTraceResult, TraceError
from app.tools import create_default_registry


DEMO_DB_PATH = Path("data/trace-demo.db")
DEMO_USER_ID = "demo-user"
DEMO_SESSION_ID = "trace-window"
DEMO_PROMPT = "请计算 20 * (5 + 1)，并把“检查计算结果”添加到待办中。"


class TraceDemoValidationError(RuntimeError):
    """Raised when the real model does not produce the expected Trace shape."""


def main() -> int:
    """Run one real tool-assisted turn and print its persisted Trace."""
    client: Optional[OpenAICompatibleLLMClient] = None
    try:
        _reset_demo_database()
        config = LLMConfig.from_env()
        store = SQLiteStore(DEMO_DB_PATH)
        store.create_session(DEMO_USER_ID, DEMO_SESSION_ID, "Trace 演示")

        client = OpenAICompatibleLLMClient(config)
        runtime = AgentRuntime(
            client,
            create_default_registry(todo_store=store),
            max_steps=8,
        )
        service = SessionAgentService(runtime, store)
        result = service.chat(DEMO_USER_ID, DEMO_SESSION_ID, DEMO_PROMPT)
        if result.run_id is None:
            raise TraceDemoValidationError("The successful chat did not return run_id.")
        trace = service.trace_recorder.get_trace(result.run_id)
        _validate_trace(trace)

        print("=== Agent Trace Demo ===")
        print("Final answer: {}".format(result.agent_result.answer))
        print("run_id: {}".format(result.run_id))
        print("Run status: {}".format(trace.run.status))
        print("Started at: {}".format(trace.run.started_at))
        print("Finished at: {}".format(trace.run.finished_at))
        print("LLM calls: {}".format(trace.run.total_llm_calls))
        print("Tool calls: {}".format(trace.run.total_tool_calls))
        print("Events:")
        for event in trace.events:
            print(json.dumps(event.to_dict(), ensure_ascii=False, indent=2))
        return 0
    except LLMConfigurationError:
        _print_failure("LLM configuration is missing or invalid.")
        return 1
    except AgentRuntimeError as error:
        _print_failure(str(error))
        return 1
    except TraceError as error:
        _print_failure(str(error))
        return 1
    except MemoryStoreError as error:
        _print_failure(str(error))
        return 1
    except TraceDemoValidationError as error:
        _print_failure(str(error))
        return 1
    except OSError:
        _print_failure("The Trace demo database files could not be prepared.")
        return 1
    finally:
        if client is not None:
            client.close()


def _validate_trace(trace: AgentTraceResult) -> None:
    if trace.run.status != "completed":
        raise TraceDemoValidationError("The Trace run did not complete.")
    tool_names = {
        event.payload.get("tool_name")
        for event in trace.events
        if event.event_type == "tool_result"
    }
    if "calculator" not in tool_names or "todo" not in tool_names:
        raise TraceDemoValidationError(
            "The Trace did not contain both calculator and todo results."
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
    print("Trace demo failed: {}".format(message), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
