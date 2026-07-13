# Minimal Agent Runtime

## Goal

Build a minimal, self-managed Agent runtime step by step without using an Agent
framework. The project currently includes tools, an OpenAI-compatible HTTP
client, a structured Agent output parser, a core Agent Runtime loop, SQLite
storage for Sessions/messages/Todos, persisted Session conversations, and
manual real-service demos. Its Session service automatically builds bounded
Context and persists a sanitized execution Trace for every Agent run.

## Technology stack

- Python 3.10
- FastAPI and Uvicorn
- Native HTML, CSS, and JavaScript
- SQLite for Sessions, messages, and optional persistent Todos
- pytest

## Current status

The current milestone runs the basic Agent loop: it asks the LLM for a
structured decision, executes requested registered tools, returns real tool
results to the model, and stops when the model produces a final answer. A
standalone Session service now loads and bounds persisted natural-language
history before the Runtime call, then atomically saves each successful
user/assistant exchange.

## Run locally

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 in a browser. The health check is available at
http://127.0.0.1:8000/api/health.

## Web UI

The FastAPI service now serves a native HTML, CSS, and JavaScript multi-Session
chat and Inspector interface at http://127.0.0.1:8000/. Start it with:

```bash
python -m uvicorn app.main:app --reload
```

The main flow is:

1. Keep the default `demo-user` or apply another demonstration user ID.
2. Create an explicitly named Session; Chat never creates one implicitly.
3. Select a Session, send a message, and let the Agent decide whether a tool is
   needed.
4. Switch between Sessions to verify that their persisted histories stay
   isolated, then rename, clear, or delete them as needed.
5. Use the right-side Inspector to review Context metrics, Session-scoped Todos,
   Trace Run history, and each ordered Trace event.

The user ID is only an isolation identifier for this local demonstration. It is
not login or authentication. The browser never stores an API key, messages,
Todos, or Trace data. `localStorage` contains only the selected user ID, active
Session ID, sidebar preference, and Inspector open/tab preferences;
conversation and Inspector data always come from the backend.

Inspector data is read from the same SQLite persistence layer but is never sent
back into the LLM Context. The Todo tab is intentionally read-only because the
current HTTP API only exposes Todo queries. The Trace tab lists Runs newest
first, shows the sanitized event timeline, and can delete a Trace without
deleting its Session, messages, or Todos.

Chat messages support a deliberately small, safe Markdown subset: newlines,
`**bold**`, inline backtick code, and lines beginning with `- `. Links and raw
HTML are not interpreted; content is constructed with DOM text nodes rather
than inserted as HTML.

For a concise recording, create weather and report Sessions, send one tool task
in each, switch between their Todo lists, open the newest Trace from
`run_started` through `run_completed`, then demonstrate the collapsible
Inspector at desktop and mobile widths.

## LLM configuration

Create a private `.env` file from the example in Windows CMD:

```cmd
copy .env.example .env
notepad .env
```

Example configuration:

```dotenv
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://example.com/v1
LLM_MODEL=example-model
LLM_TIMEOUT_SECONDS=60
LLM_TEMPERATURE=0
```

These values are placeholders only. This project uses the OpenAI-Compatible
Chat Completions API; replace them with values supplied by your chosen service.
Never commit `.env`.

## LLM smoke test

After configuring `.env`, run:

```cmd
python -m scripts.llm_smoke_test
```

The smoke test checks only that:

- the real API can be reached;
- the model receives the Tool Schemas;
- the model selects `calculator` for a calculation request; and
- the model's JSON output can be parsed into an `AgentDecision`.

It does not execute `calculator` or any other tool.

## Agent Runtime demo

The Runtime demo performs the complete current loop and really executes the
selected tool:

```cmd
python -m scripts.agent_runtime_demo
```

The two manual scripts serve different purposes:

- `llm_smoke_test` verifies only API access, Tool Schema visibility, tool
  selection, and JSON parsing. It never executes a tool.
- `agent_runtime_demo` lets the model select tools, executes them through
  `ToolRegistry`, sends each real result back to the model, and waits for a
  final answer.

The Runtime limits the number of LLM decision steps so malformed or repetitive
model behavior cannot create an infinite loop. Tool failures are returned to
the LLM as real results so it can correct its arguments, choose another tool,
or answer the user.

## SQLite persistence

`SQLiteStore` uses `data/agent.db` by default, creates its parent directory and
schema automatically, and opens a short-lived connection for every operation.
Sessions are identified by the composite key `(user_id, session_id)`. Messages
and Todos carry the same pair as a foreign key, so identical `session_id`
values owned by different users remain isolated. Deleting a Session cascades
to its messages and Todos.

The default tool registry deliberately keeps the original in-memory Todo mode:

```python
from app.tools import create_default_registry

registry = create_default_registry()
```

To opt in to persistent Todos, first create the Session and inject the store:

```python
from app.memory import SQLiteStore
from app.tools import ToolContext, create_default_registry

store = SQLiteStore("data/agent.db")
store.create_session("demo-user", "demo-session", "持久化演示")
registry = create_default_registry(todo_store=store)
context = ToolContext(user_id="demo-user", session_id="demo-session")
result = registry.execute(
    "todo",
    {"action": "add", "content": "验证 SQLite 持久化"},
    context,
)
print(result.to_dict())
```

`TodoTool` never creates a Session implicitly. Recreate `SQLiteStore` with the
same path to read previously saved data. Tests always use pytest `tmp_path`, so
they do not write to the default database.

## Persisted Session conversations

`SessionAgentService` connects storage to the otherwise stateless Runtime. It
validates the user and Session, loads history by `(user_id, session_id)`, builds
the correct `ToolContext`, runs the Agent, and saves the successful exchange.
`AgentRuntime` does not import or operate `SQLiteStore`, so its LLM/tool loop
remains independently testable and reusable with other storage backends.

```text
SQLite 完整历史
  ↓
history_limit 数据库召回上限
  ↓
BasicContextManager
  ↓
较早摘要 + 最近原始消息
  ↓
AgentRuntime Loop
  ↓
得到 final
  ↓
原子保存本轮真实 user + assistant
```

The database retains the complete natural-language conversation. Generated
Context summaries exist only for one Runtime invocation and are never written
back to the messages table. Assistant metadata keeps compact Agent and Context
statistics, but never the summary text or compressed messages. System prompts,
raw tool-call JSON, tool results, complete Runtime messages, request headers,
API keys, and raw HTTP responses are not recalled or stored in that metadata.

The current Session layer supports:

- normal conversational follow-ups;
- follow-ups after tool use;
- isolated Sessions for one user;
- isolation between different users;
- continuing after Store/Runtime/Service recreation; and
- persistent Session-scoped Todos;
- Runtime maximum-step protection; and
- automatic basic Context compression.

After configuring `.env`, run the real two-window persistence demo:

```cmd
python -m scripts.session_memory_demo
```

The demo uses only `data/session-demo.db`, recreates the application stack
between turns, and verifies that its two windows retain separate Todo lists.
It never deletes `data/agent.db`.

## Basic Context management

Long-running conversations cannot safely send every stored message to an LLM
forever: requests become larger, slower, and eventually exceed the model's
Context limit. `SessionAgentService` now passes every recalled history window
through `BasicContextManager` before calling the Runtime.

Compression starts when either the normalized history has more than
`max_messages` messages or its estimated size is greater than `max_chars`.
The estimate adds each message's role length, content length, and a small fixed
structural allowance. It is a character-level approximation, not exact Token
counting from a model tokenizer.

When neither threshold is exceeded, normalized messages are returned in their
original order. When either threshold is exceeded, the manager:

- converts older messages into one deterministic `assistant` message beginning
  with `【较早会话摘要】`;
- keeps the configured number of most recent original messages in old-to-new
  order; and
- shortens the summary first, then older retained messages, if the combined
  result still exceeds the approximate character budget.

Only `role` and trimmed natural-language `content` enter the result. Extra
dictionary fields and `MessageRecord.metadata` are ignored, so
`reasoning_summary`, `used_tools`, historical tool results, Runtime messages,
raw LLM HTTP responses, request headers, and API keys stored outside natural
message content do not enter Context.

`history_limit` and the Context thresholds have distinct roles. The former is
the maximum number of recent database messages recalled; `max_messages` and
`max_chars` decide whether that recalled window is compressed. The fixed order
is full SQLite history → `history_limit` → Context compression. Neither limit
deletes or rewrites database history, and the current `user_input` is appended
by `AgentRuntime` after the built history rather than included in compression.

After configuring `.env`, run the real compression demonstration with:

```bash
python -m scripts.context_compression_demo
```

It seeds 24 natural-language messages in `data/context-demo.db`, forces basic
compression, performs one real LLM request, prints the Context statistics, and
verifies that no generated summary was persisted. It never deletes
`data/agent.db`.

On macOS, manually run the focused and complete test suites with:

```bash
source .venv/bin/activate
python -m pytest -q tests/test_context_manager.py
python -m pytest -q tests/test_session_context_integration.py
python -m pytest -q
```

## Persistent Agent Trace

`SessionAgentService` enables `SQLiteTraceRecorder` by default. Each validated
chat starts one `run_id`, records Context statistics and Runtime decisions,
then ends as `completed` or `failed`. Successful conversation messages are
still saved separately, and Trace data is never recalled into the next LLM
Context.

The `agent_runs` table stores one lifecycle row per invocation: Session scope,
status, bounded user input/final answer, concise failure information, call
counts, and timestamps. The `trace_events` table stores ordered events using a
per-run `sequence`:

```text
run_started
→ context_built
→ llm_decision
→ tool_call → tool_result      (repeated in execution order)
→ llm_decision                 (for later Runtime steps)
→ run_completed | run_failed
```

Trace payloads retain Context counts, short `reasoning_summary` values, model
name, tool names/arguments, and real sanitized tool results. They do not retain
the Runtime's complete messages, system Prompt, full hidden reasoning, API
keys, authorization values, passwords/tokens, or raw HTTP responses. Sensitive
keys are recursively replaced with `[REDACTED]`, and long strings are bounded.

Runs are isolated by `user_id` and optional `session_id` filters. Deleting a
Session cascades to its runs and events. `SessionChatResult.run_id` is the
stable lookup key intended for a later HTTP API and Trace panel; the result does
not inline every event.

After configuring `.env`, run the real calculator + Todo Trace demonstration:

```bash
python -m scripts.trace_demo
```

The script uses only `data/trace-demo.db`, prints the completed run and ordered
events, and verifies that real calculator and Todo results were recorded.

## FastAPI backend

Start the complete HTTP service with:

```bash
python -m uvicorn app.main:app --reload
```

The application lifespan creates and owns the production service graph. If LLM
configuration is missing, import and startup still succeed: `/api/health`, the
static page, and database-backed Session/Message/Todo/Trace endpoints remain
available, while `/api/chat` returns `503 llm_unavailable` without attempting a
network request.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions` | Create a Session |
| GET | `/api/sessions?user_id=...` | List one user's Sessions |
| GET/PATCH/DELETE | `/api/sessions/{session_id}` | Read, rename, or delete a Session |
| GET/DELETE | `/api/sessions/{session_id}/messages` | Read or clear history |
| GET | `/api/sessions/{session_id}/todos` | List Session-scoped Todos |
| POST | `/api/chat` | Run one persisted Agent turn |
| GET | `/api/traces` | List user-scoped Trace runs |
| GET/DELETE | `/api/traces/{run_id}` | Read or delete one owned Trace |
| GET | `/api/health` | Check service, LLM configuration, and database state |

A Session must exist before Chat; Chat never creates one implicitly. Every
operation carries both `user_id` and `session_id`, so identical Session ids for
different users and separate windows for one user remain isolated. A successful
Chat response includes compact Agent/Context statistics and `run_id`, but not
Runtime messages, the system Prompt, raw HTTP data, or hidden reasoning.

Create a Session and chat with curl:

```bash
curl -X POST http://127.0.0.1:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-a","session_id":"window-1","title":"天气窗口"}'

curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-a","session_id":"window-1","message":"查询东京天气"}'

curl 'http://127.0.0.1:8000/api/traces?user_id=user-a&session_id=window-1'
curl 'http://127.0.0.1:8000/api/traces/RUN_ID?user_id=user-a'
```

Errors consistently use this safe shape:

```json
{"error":{"code":"session_not_found","message":"Session 不存在"}}
```

LLM request or response failures use HTTP 502, missing configuration uses 503,
and the Runtime step-limit uses HTTP 508. Error bodies never echo credentials,
headers, traceback text, system prompts, or raw provider responses.

With the server running, exercise two isolated windows through HTTP:

```bash
python -m scripts.api_demo
```

## Current architecture

```text
用户请求
  ↓
System Prompt + Tool Schema
  ↓
OpenAI-Compatible LLM API
  ↓
JSON 输出
  ↓
Agent Output Parser
  ↓
AgentDecision(final/tool_call)
  ├─ final → Final answer
  └─ tool_call
       ↓
     ToolRegistry.execute
       ↓
     Real tool result
       ↓
     Return result to LLM and continue
```

The multi-window web UI and long-term user memory remain future milestones.
