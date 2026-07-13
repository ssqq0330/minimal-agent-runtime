"""Run the real-LLM final acceptance journey against a dedicated database."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.agent import AgentOutputParseError, parse_llm_output
from app.dependencies import create_application_services
from app.security import sanitize_error_message


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "final-acceptance.db"
REPORT_ITEMS = (
    "LLM API",
    "Agent Runtime Loop",
    "Calculator",
    "Search",
    "Todo",
    "Session Isolation",
    "User Isolation",
    "History Recall",
    "Context Compression",
    "Trace Logging",
    "Persistence After Restart",
)


class AcceptanceFailure(RuntimeError):
    pass


class ProtocolRetryLLMClient:
    """Retry only malformed model decisions before Runtime executes any tools."""

    def __init__(self, client, attempts: int = 3) -> None:
        self.client = client
        self.attempts = attempts
        self.config = getattr(client, "config", None)

    def complete(self, messages):
        last_error = None
        for _ in range(self.attempts):
            response = self.client.complete(messages)
            try:
                parse_llm_output(response.content)
            except AgentOutputParseError as error:
                last_error = error
                continue
            return response
        raise last_error or AcceptanceFailure("model decision validation failed")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def clean_acceptance_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for path in (DB_PATH, Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm")):
        path.unlink(missing_ok=True)


def validate_trace(trace) -> None:
    require(trace.run.status == "completed", "a successful Run was not completed")
    sequences = [event.sequence for event in trace.events]
    require(sequences == list(range(1, len(sequences) + 1)), "Trace sequence is invalid")
    require(trace.events[0].event_type == "run_started", "Trace start event is missing")
    require(trace.events[-1].event_type == "run_completed", "Trace completion event is missing")


def run_acceptance() -> Dict[str, bool]:
    clean_acceptance_database()
    checks = {name: False for name in REPORT_ITEMS}
    services = create_application_services(DB_PATH)
    try:
        retry_client = ProtocolRetryLLMClient(services.llm_client)
        services.runtime.llm_client = retry_client
        service = services.require_session_service()
        store = services.store
        recorder = services.trace_recorder
        user = "acceptance-user"
        store.create_session(user, "weather-window", "Weather Window")
        store.create_session(user, "report-window", "Report Window")

        weather = service.chat(
            user,
            "weather-window",
            "请必须调用 search 查询东京天气，并调用 todo 添加待办“出门带伞”，完成后再回答。",
        )
        report = service.chat(
            user,
            "report-window",
            "请必须调用 todo 添加待办“周五前完成周报”，完成后再回答。",
        )
        weather_follow = service.chat(
            user,
            "weather-window",
            "刚才查询的是哪个城市？当前待办有哪些？请依据本 Session 历史回答。",
        )
        report_follow = service.chat(
            user,
            "report-window",
            "当前待办有哪些？请依据本 Session 历史回答。",
        )
        calculator = service.chat(
            user,
            "weather-window",
            "请必须调用 calculator 计算 12 * (3 + 2)，并在最终回答中明确写出结果。",
        )

        checks["LLM API"] = all(
            result.agent_result.total_llm_calls >= 1
            for result in (weather, report, weather_follow, report_follow, calculator)
        )
        checks["Agent Runtime Loop"] = weather.agent_result.total_tool_calls >= 2
        checks["Calculator"] = (
            "60" in calculator.agent_result.answer
            and calculator.agent_result.total_tool_calls >= 1
        )
        weather_trace = recorder.get_trace(weather.run_id)
        checks["Search"] = any(
            event.event_type == "tool_result"
            and event.payload.get("tool_name") == "search"
            and event.payload.get("success") is True
            for event in weather_trace.events
        )
        weather_todos = store.list_todos(user, "weather-window")
        report_todos = store.list_todos(user, "report-window")
        checks["Todo"] = (
            any(todo.content == "出门带伞" for todo in weather_todos)
            and any(todo.content == "周五前完成周报" for todo in report_todos)
        )
        checks["Session Isolation"] = (
            all(todo.content != "周五前完成周报" for todo in weather_todos)
            and all(todo.content != "出门带伞" for todo in report_todos)
            and len(recorder.list_runs(user, session_id="weather-window")) == 3
            and len(recorder.list_runs(user, session_id="report-window")) == 2
        )
        checks["History Recall"] = (
            "东京" in weather_follow.agent_result.answer
            and "出门带伞" in weather_follow.agent_result.answer
            and "周五前完成周报" in report_follow.agent_result.answer
        )

        for index in range(12):
            store.add_exchange(
                user,
                "weather-window",
                "压缩验收历史问题 {}：请记住东京和出门带伞。".format(index),
                "压缩验收历史回答 {}。".format(index),
            )
        compression = service.chat(
            user,
            "weather-window",
            "请简短确认已收到；这是 Context 压缩验收。",
        )
        messages = store.list_messages(user, "weather-window")
        checks["Context Compression"] = (
            compression.context_compressed
            and all("【较早会话摘要】" not in message.content for message in messages)
        )

        successful = (weather, report, weather_follow, report_follow, calculator, compression)
        for result in successful:
            validate_trace(recorder.get_trace(result.run_id))
        checks["Trace Logging"] = True

        other_user = "acceptance-other-user"
        store.create_session(other_user, "weather-window", "Other User Window")
        store.add_exchange(other_user, "weather-window", "private", "isolated")
        checks["User Isolation"] = (
            store.get_session(user, "weather-window") is not None
            and store.get_session(other_user, "weather-window") is not None
            and all(
                message.content not in {"private", "isolated"}
                for message in store.list_messages(user, "weather-window")
            )
            and recorder.list_runs(other_user, session_id="weather-window") == []
        )

        require(
            all(
                checks[name]
                for name in REPORT_ITEMS
                if name != "Persistence After Restart"
            ),
            "one or more live acceptance checks failed",
        )
    finally:
        services.close()

    restarted = create_application_services(DB_PATH)
    try:
        persisted = restarted.store.list_messages("acceptance-user", "report-window")
        checks["Persistence After Restart"] = (
            len(persisted) == 4
            and any("周五前完成周报" in message.content for message in persisted)
        )
        require(checks["Persistence After Restart"], "history was not readable after restart")
    finally:
        restarted.close()
    return checks


def print_report(checks: Dict[str, bool], error: str = "") -> None:
    print("=== Final Acceptance Report ===")
    for name in REPORT_ITEMS:
        print("{}: {}".format(name, "PASS" if checks.get(name) else "FAIL"))
    print("")
    print("Overall: {}".format("PASS" if all(checks.get(name) for name in REPORT_ITEMS) else "FAIL"))
    if error:
        print("Reason: {}".format(sanitize_error_message(error, max_chars=300)))


def main() -> int:
    checks = {name: False for name in REPORT_ITEMS}
    try:
        checks = run_acceptance()
    except Exception as error:
        print_report(checks, str(error) or error.__class__.__name__)
        return 1
    print_report(checks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
