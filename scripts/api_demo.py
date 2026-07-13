"""Local HTTP demonstration of Session, Chat, Todo, and Trace APIs."""

from __future__ import annotations

import sys
from typing import Any, Dict, List

import httpx


BASE_URL = "http://127.0.0.1:8000"
DEMO_USER_ID = "api-demo-user"
WEATHER_SESSION_ID = "weather-window"
REPORT_SESSION_ID = "report-window"


class APIDemoValidationError(RuntimeError):
    """Raised when local API responses do not demonstrate isolation."""


def main() -> int:
    """Exercise the running local API without reading any LLM credentials."""
    try:
        with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
            _remove_previous_demo_sessions(client)
            try:
                _create_session(client, WEATHER_SESSION_ID, "天气窗口")
                _create_session(client, REPORT_SESSION_ID, "周报窗口")

                weather_chat = _post_json(
                    client,
                    "/api/chat",
                    {
                        "user_id": DEMO_USER_ID,
                        "session_id": WEATHER_SESSION_ID,
                        "message": "查询东京天气并添加“出门带伞”。",
                    },
                )
                report_chat = _post_json(
                    client,
                    "/api/chat",
                    {
                        "user_id": DEMO_USER_ID,
                        "session_id": REPORT_SESSION_ID,
                        "message": "添加“周五前完成周报”。",
                    },
                )

                weather_messages = _get_json(
                    client,
                    "/api/sessions/{}/messages".format(WEATHER_SESSION_ID),
                    {"user_id": DEMO_USER_ID},
                )
                report_messages = _get_json(
                    client,
                    "/api/sessions/{}/messages".format(REPORT_SESSION_ID),
                    {"user_id": DEMO_USER_ID},
                )
                weather_todos = _get_json(
                    client,
                    "/api/sessions/{}/todos".format(WEATHER_SESSION_ID),
                    {"user_id": DEMO_USER_ID},
                )
                report_todos = _get_json(
                    client,
                    "/api/sessions/{}/todos".format(REPORT_SESSION_ID),
                    {"user_id": DEMO_USER_ID},
                )
                traces = _get_json(
                    client,
                    "/api/traces",
                    {
                        "user_id": DEMO_USER_ID,
                        "session_id": WEATHER_SESSION_ID,
                    },
                )
                trace = _get_json(
                    client,
                    "/api/traces/{}".format(weather_chat["run_id"]),
                    {"user_id": DEMO_USER_ID},
                )
                _validate_isolation(weather_todos, report_todos)
            finally:
                _remove_previous_demo_sessions(client)

        print("=== Local FastAPI Demo ===")
        print("weather-window run_id: {}".format(weather_chat["run_id"]))
        print("report-window run_id: {}".format(report_chat["run_id"]))
        print("weather-window messages: {}".format(len(weather_messages)))
        print("report-window messages: {}".format(len(report_messages)))
        print("weather-window todos: {}".format(_todo_contents(weather_todos)))
        print("report-window todos: {}".format(_todo_contents(report_todos)))
        print("weather-window Trace runs: {}".format(len(traces)))
        print(
            "weather-window event types: {}".format(
                [event["event_type"] for event in trace["events"]]
            )
        )
        print("Window isolation verified: True")
        return 0
    except httpx.RequestError:
        _print_failure("The local FastAPI service could not be reached.")
        return 1
    except httpx.HTTPStatusError as error:
        _print_failure("The local API returned HTTP {}.".format(error.response.status_code))
        return 1
    except (KeyError, TypeError, ValueError, APIDemoValidationError) as error:
        _print_failure(str(error))
        return 1


def _remove_previous_demo_sessions(client: httpx.Client) -> None:
    for session_id in (WEATHER_SESSION_ID, REPORT_SESSION_ID):
        client.delete(
            "/api/sessions/{}".format(session_id),
            params={"user_id": DEMO_USER_ID},
        )


def _create_session(client: httpx.Client, session_id: str, title: str) -> None:
    _post_json(
        client,
        "/api/sessions",
        {
            "user_id": DEMO_USER_ID,
            "session_id": session_id,
            "title": title,
        },
        expected_status=201,
    )


def _post_json(
    client: httpx.Client,
    path: str,
    payload: Dict[str, Any],
    expected_status: int = 200,
) -> Any:
    response = client.post(path, json=payload)
    if response.status_code != expected_status:
        response.raise_for_status()
        raise APIDemoValidationError("The local API returned an unexpected status.")
    return response.json()


def _get_json(client: httpx.Client, path: str, params: Dict[str, Any]) -> Any:
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def _todo_contents(todos: List[Dict[str, Any]]) -> List[str]:
    return [str(todo["content"]) for todo in todos]


def _validate_isolation(
    weather_todos: List[Dict[str, Any]],
    report_todos: List[Dict[str, Any]],
) -> None:
    weather = _todo_contents(weather_todos)
    report = _todo_contents(report_todos)
    if "出门带伞" not in weather or "周五前完成周报" in weather:
        raise APIDemoValidationError("weather-window Todo isolation failed.")
    if "周五前完成周报" not in report or "出门带伞" in report:
        raise APIDemoValidationError("report-window Todo isolation failed.")


def _print_failure(message: str) -> None:
    print("API demo failed: {}".format(message), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
