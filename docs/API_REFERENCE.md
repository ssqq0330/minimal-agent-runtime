# API Reference

Base URL：`http://127.0.0.1:8000`

服务启动后可访问 `http://127.0.0.1:8000/docs` 查看 FastAPI 自动生成的 OpenAPI 文档。本文示例只使用演示标识，不包含 API Key。成功时间字段均为带时区的 ISO 8601 字符串。

## 通用错误格式

```json
{
  "error": {
    "code": "session_not_found",
    "message": "Session 不存在"
  }
}
```

常见状态：`404` 资源不存在或不属于当前 user，`409` Session 冲突，`422` 请求/Agent 输入无效，`500` 存储或未知错误，`502` LLM 请求/决策错误，`503` LLM 未配置，`508` Runtime 达到最大步数。

## 1. 健康检查

### GET `/api/health`

参数：无。

请求：

```bash
curl http://127.0.0.1:8000/api/health
```

响应 `200`：

```json
{
  "status": "ok",
  "service": "minimal-agent-runtime",
  "llm_configured": true,
  "database": "available"
}
```

主要错误：正常启动后即使未配置 LLM 也返回 `200`，此时 `llm_configured=false`。应用服务不可用时才可能出现 `500`。

## 2. 创建 Session

### POST `/api/sessions`

JSON 参数：`user_id` 必填，1～128 字符；`session_id` 可选，1～128 字符，省略时后端生成；`title` 可选，默认“新会话”，1～200 字符。

请求：

```bash
curl -X POST http://127.0.0.1:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user","session_id":"weather-window","title":"天气窗口"}'
```

响应 `201`：

```json
{
  "user_id": "demo-user",
  "session_id": "weather-window",
  "title": "天气窗口",
  "created_at": "2026-07-13T10:00:00+00:00",
  "updated_at": "2026-07-13T10:00:00+00:00"
}
```

主要错误：`409 session_conflict`；`422 validation_error`；`500 database_error`。

## 3. 列出 Sessions

### GET `/api/sessions`

Query：`user_id` 必填，1～128 字符。

请求：

```bash
curl 'http://127.0.0.1:8000/api/sessions?user_id=demo-user'
```

响应 `200`：

```json
[
  {
    "user_id": "demo-user",
    "session_id": "weather-window",
    "title": "天气窗口",
    "created_at": "2026-07-13T10:00:00+00:00",
    "updated_at": "2026-07-13T10:02:00+00:00"
  }
]
```

主要错误：`422 validation_error`；`500 database_error`。

## 4. 获取 Session

### GET `/api/sessions/{session_id}`

Path：`session_id` 必填。Query：`user_id` 必填。

请求：

```bash
curl 'http://127.0.0.1:8000/api/sessions/weather-window?user_id=demo-user'
```

响应 `200`：与创建 Session 的响应结构相同。

主要错误：`404 session_not_found`；`422 validation_error`；`500 database_error`。

## 5. 重命名 Session

### PATCH `/api/sessions/{session_id}`

Path：`session_id` 必填。JSON：`user_id` 必填；`title` 必填，1～200 字符。

请求：

```bash
curl -X PATCH http://127.0.0.1:8000/api/sessions/weather-window \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user","title":"东京天气"}'
```

响应 `200`：

```json
{
  "user_id": "demo-user",
  "session_id": "weather-window",
  "title": "东京天气",
  "created_at": "2026-07-13T10:00:00+00:00",
  "updated_at": "2026-07-13T10:03:00+00:00"
}
```

主要错误：`404 session_not_found`；`422 validation_error`；`500 database_error`。

## 6. 删除 Session

### DELETE `/api/sessions/{session_id}`

Path：`session_id` 必填。Query：`user_id` 必填。删除会级联清理该范围的 Message、Todo 和 Trace。

请求：

```bash
curl -i -X DELETE 'http://127.0.0.1:8000/api/sessions/weather-window?user_id=demo-user'
```

响应：`204 No Content`，无 JSON body。

主要错误：`404 session_not_found`；`422 validation_error`；`500 database_error`。

## 7. 获取消息历史

### GET `/api/sessions/{session_id}/messages`

Path：`session_id` 必填。Query：`user_id` 必填；`limit` 可选，默认 50，范围 1～500。返回顺序为从旧到新。

请求：

```bash
curl 'http://127.0.0.1:8000/api/sessions/weather-window/messages?user_id=demo-user&limit=50'
```

响应 `200`：

```json
[
  {
    "id": 1,
    "role": "user",
    "content": "请查询东京天气。",
    "created_at": "2026-07-13T10:01:00+00:00",
    "metadata": null
  },
  {
    "id": 2,
    "role": "assistant",
    "content": "东京天气信息来自本地 Mock 数据。",
    "created_at": "2026-07-13T10:01:02+00:00",
    "metadata": {"agent":{"total_llm_calls":2,"total_tool_calls":1,"stopped_reason":"final","used_tools":["search"],"reasoning_summaries":["需要查询。","已有结果。"]}}
  }
]
```

主要错误：`404 session_not_found`；`422 validation_error`；`500 database_error`。

## 8. 清空消息历史

### DELETE `/api/sessions/{session_id}/messages`

Path：`session_id` 必填。Query：`user_id` 必填。该操作只清空消息，不删除 Session、Todo 或 Trace。

请求：

```bash
curl -X DELETE 'http://127.0.0.1:8000/api/sessions/weather-window/messages?user_id=demo-user'
```

响应 `200`：

```json
{"deleted_count": 4}
```

主要错误：`404 session_not_found`；`422 validation_error`；`500 database_error`。

## 9. 获取 Session Todos

### GET `/api/sessions/{session_id}/todos`

Path：`session_id` 必填。Query：`user_id` 必填。HTTP API 当前只提供 Todo 查询；新增、完成和删除由 Agent 的 todo 工具执行。

请求：

```bash
curl 'http://127.0.0.1:8000/api/sessions/weather-window/todos?user_id=demo-user'
```

响应 `200`：

```json
[
  {
    "id": 1,
    "content": "出门带伞",
    "completed": false,
    "created_at": "2026-07-13T10:01:01+00:00",
    "completed_at": null
  }
]
```

主要错误：`404 session_not_found`；`422 validation_error`；`500 database_error`。

## 10. Agent Chat

### POST `/api/chat`

JSON：`user_id` 必填，1～128 字符；`session_id` 必填，1～128 字符；`message` 必填，1～8000 字符。Session 必须预先存在。

请求：

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user","session_id":"weather-window","message":"请查询东京天气，并添加待办出门带伞。"}'
```

响应 `200`（部分时间与 metadata 省略为示例值）：

```json
{
  "session": {
    "user_id": "demo-user",
    "session_id": "weather-window",
    "title": "天气窗口",
    "created_at": "2026-07-13T10:00:00+00:00",
    "updated_at": "2026-07-13T10:01:02+00:00"
  },
  "user_message": {
    "id": 1,
    "role": "user",
    "content": "请查询东京天气，并添加待办出门带伞。",
    "created_at": "2026-07-13T10:01:02+00:00",
    "metadata": null
  },
  "assistant_message": {
    "id": 2,
    "role": "assistant",
    "content": "已查询东京天气，并添加待办“出门带伞”。",
    "created_at": "2026-07-13T10:01:02+00:00",
    "metadata": {}
  },
  "answer": "已查询东京天气，并添加待办“出门带伞”。",
  "run_id": "0123456789abcdef0123456789abcdef",
  "loaded_history_count": 0,
  "context": {
    "compressed": false,
    "original_message_count": 0,
    "output_message_count": 0,
    "summarized_message_count": 0,
    "retained_recent_count": 0,
    "original_char_count": 0,
    "output_char_count": 0
  },
  "agent": {
    "total_llm_calls": 2,
    "total_tool_calls": 2,
    "stopped_reason": "final"
  }
}
```

主要错误：`404 session_not_found`；`422 validation_error/agent_input_invalid`；`502 llm_request_failed/agent_response_invalid`；`503 llm_unavailable`；`508 agent_max_steps`；`500 context_compression_failed/database_error/trace_persistence_failed`。

## 11. 列出 Trace Runs

### GET `/api/traces`

Query：`user_id` 必填；`session_id` 可选；`status` 可选；`limit` 可选，默认 50，范围 1～200。返回最新 Run 在前。

请求：

```bash
curl 'http://127.0.0.1:8000/api/traces?user_id=demo-user&session_id=weather-window&status=completed&limit=20'
```

响应 `200`：

```json
[
  {
    "run_id": "0123456789abcdef0123456789abcdef",
    "user_id": "demo-user",
    "session_id": "weather-window",
    "status": "completed",
    "user_input": "请查询东京天气。",
    "final_answer": "东京天气信息来自本地 Mock 数据。",
    "error_type": null,
    "error_message": null,
    "total_llm_calls": 2,
    "total_tool_calls": 1,
    "started_at": "2026-07-13T10:01:00+00:00",
    "finished_at": "2026-07-13T10:01:02+00:00"
  }
]
```

主要错误：`422 validation_error/trace_invalid`；`500 trace_persistence_failed/database_error`。

## 12. 获取 Trace 详情

### GET `/api/traces/{run_id}`

Path：`run_id` 必填。Query：`user_id` 必填；若 Run 属于其他 user，也统一返回 404。

请求：

```bash
curl 'http://127.0.0.1:8000/api/traces/0123456789abcdef0123456789abcdef?user_id=demo-user'
```

响应 `200`：

```json
{
  "run": {
    "run_id": "0123456789abcdef0123456789abcdef",
    "user_id": "demo-user",
    "session_id": "weather-window",
    "status": "completed",
    "user_input": "请查询东京天气。",
    "final_answer": "东京天气信息来自本地 Mock 数据。",
    "error_type": null,
    "error_message": null,
    "total_llm_calls": 2,
    "total_tool_calls": 1,
    "started_at": "2026-07-13T10:01:00+00:00",
    "finished_at": "2026-07-13T10:01:02+00:00"
  },
  "events": [
    {
      "id": 1,
      "run_id": "0123456789abcdef0123456789abcdef",
      "sequence": 1,
      "event_type": "run_started",
      "step_number": null,
      "payload": {},
      "created_at": "2026-07-13T10:01:00+00:00"
    }
  ]
}
```

主要错误：`404 trace_not_found`；`422 validation_error/trace_invalid`；`500 trace_persistence_failed/database_error`。

## 13. 删除 Trace

### DELETE `/api/traces/{run_id}`

Path：`run_id` 必填。Query：`user_id` 必填。只删除该 Trace Run 与 Events，不删除 Session、消息或 Todo。

请求：

```bash
curl -i -X DELETE 'http://127.0.0.1:8000/api/traces/0123456789abcdef0123456789abcdef?user_id=demo-user'
```

响应：`204 No Content`，无 JSON body。

主要错误：`404 trace_not_found`；`422 validation_error/trace_invalid`；`500 trace_persistence_failed/database_error`。
