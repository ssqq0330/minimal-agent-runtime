# Problem-Solving Record

## Record template

- Date:
- Problem:
- Context:
- Investigation:
- Decision:
- Implementation:
- Verification:
- Follow-up:

## 2026-07-13: Tool system implementation

- Problem: Add independently testable tools without implementing the Agent Runtime.
- Context: This milestone needs a common protocol, a registry, arithmetic,
  local mock search, and session-scoped todo management.
- Investigation: The project has no persistence layer or Agent framework at
  this stage, so tools must own only the smallest state they require.
- Decision: Use a small JSON-Schema-like validator in `BaseTool`; it covers the
  requested scalar/container types, enum, required fields, numeric bounds, and
  `additionalProperties: false` without adding a dependency.
- Implementation: `ToolRegistry` maps names to tools and catches unexpected
  execution exceptions. Calculator uses an AST allow-list. Search reads a local
  static knowledge base and labels every result `mock`. Todo uses one `RLock`
  and `(user_id, session_id)` as its memory-store key.
- Verification: Tests cover required success paths, validation failures,
  isolation, and Registry exception conversion.
- Follow-up: Later milestones can pass `get_tool_schemas()` to the LLM client,
  replace Todo's in-memory store with SQLite, and let the custom Runtime invoke
  Registry methods.

## 2026-07-13: LLM configuration and HTTP client

- Problem: Add a small, testable OpenAI-compatible Chat Completions client
  without starting the Agent Runtime milestone.
- Why OpenAI-compatible HTTP: The protocol keeps the runtime independent from a
  specific model vendor and allows any compatible endpoint to be configured.
- Why httpx: Direct HTTP keeps request ownership and error behavior visible,
  avoids the OpenAI SDK, and uses a dependency already present in the project.
- API key protection: The key is read from environment configuration and is
  used only in the Authorization header. Request errors report a category or
  HTTP status only; they never include exception details, response bodies, or
  request headers.
- Testability: The client accepts an externally owned `httpx.Client`. Tests
  inject clients backed by `httpx.MockTransport`, so they can inspect requests
  and simulate success, status errors, timeouts, and connection failures with
  no real network access.
- Error boundaries: `LLMConfigurationError` identifies problems that can be
  fixed before a request, `LLMRequestError` represents transport or HTTP
  failures, and `LLMResponseError` represents an incompatible or malformed
  service response. Callers can therefore choose the correct recovery path.
- Verification: Added 50 isolated LLM client cases and ran the complete suite;
  all 85 tests passed without contacting a real API.
- Follow-up: A later runtime milestone can supply validated messages to
  `complete()` and consume `LLMResponse`, without changing this HTTP layer.

## 2026-07-13: Structured Agent decisions and prompts

- Why no full chain of thought: The application needs a machine-actionable
  decision, not private model deliberation. Requesting only a concise summary
  reduces unnecessary sensitive output and keeps the protocol focused.
- Role of `reasoning_summary`: It gives operators a short explanation of why
  the response is final or why tools are needed, without storing detailed
  internal reasoning.
- Why an explicit JSON protocol: A small `final`/`tool_call` union is easy to
  validate, serialize, test, and later dispatch from the custom Runtime.
- Why not a brace regex: Regular expressions cannot reliably distinguish
  nested objects, arrays, escaped quotes, and braces inside JSON strings. The
  parser instead tries `JSONDecoder.raw_decode()` at candidate object starts.
- Markdown and surrounding text: The same candidate scan naturally finds a
  JSON object inside fenced blocks or short explanatory text while selecting
  only the first object that can be fully decoded.
- Why include `tool_call_id`: It provides stable correlation between each model
  request and its real tool result, especially when one decision requests
  multiple tools.
- Mutual exclusion: `final` requires a non-empty answer and no tool calls;
  `tool_call` requires one or more calls and no answer. This prevents a Runtime
  from guessing whether to respond or execute tools.
- Verification: Added isolated parser and prompt tests covering extraction,
  protocol validation, schemas, and tool-result messages. No tool or network
  execution is involved.

## 2026-07-13: Real LLM tool-selection smoke test

- Why a real API smoke test: Unit tests prove request and parsing behavior with
  deterministic fakes, but only a manual real-service check can confirm that a
  provider accepts the prompt and that its model follows the JSON protocol.
- Why selection only: This milestone isolates LLM integration risk. It verifies
  that the model sees Tool Schemas and selects `calculator`, while leaving state
  changes and tool execution to the next Runtime milestone.
- Dependency injection: `run_smoke_test()` accepts an external client so tests
  can return controlled `LLMResponse` values without a `.env` file or network.
  Externally injected clients remain caller-owned; internally created clients
  are always closed in `finally`.
- API key safety: The script never prints configuration objects, request
  headers, or exception details. Known secrets are redacted from normal model
  output, and expected request/configuration failures use category-only errors.
- Success criterion: The parsed decision must be `tool_call`, include a
  `calculator` call, and contain a non-empty string `expression` argument.
- Diagnosing non-JSON output: The raw content is printed on a successful parse.
  Parse failures identify the JSON-protocol category without echoing a possibly
  sensitive response; the system prompt and provider JSON-mode behavior are the
  first items to inspect manually.
- Provider differences: OpenAI-compatible services can differ in supported
  model names, base URL layout, authentication, response metadata, and how
  strictly models follow JSON instructions. The existing HTTP client normalizes
  the standard Chat Completions response while surfacing incompatible responses.
- Why Runtime is next: A complete loop needs call correlation, execution limits,
  tool-result messages, repeated model calls, and termination rules. Keeping
  those concerns out of this smoke test makes real-service diagnosis precise.

## 2026-07-13: Core Agent Runtime loop

- Runtime loop: Each run builds system/history/user messages, calls the LLM,
  parses one structured decision, appends the original assistant JSON, executes
  requested tools in order, appends one real result message per call, and
  repeats until `final`.
- Tool failure recovery: A failed `ToolResult` is useful model input rather than
  a Runtime exception. Returning it unchanged lets the model correct arguments,
  choose another tool, ask the user, or produce a final explanation.
- Step limit: `max_steps` provides deterministic termination when a model keeps
  requesting tools or never emits `final`, preventing an unbounded LLM/tool loop.
- Tool results use `user`: The current LLM client deliberately accepts only
  `system`, `user`, and `assistant`. A structured user message carries the real
  tool result until a future protocol explicitly supports a `tool` role.
- Reasoning records: Steps store only the model-provided short
  `reasoning_summary`; no full chain of thought is requested, invented, or
  persisted.
- Multiple calls: Calls are executed in the exact list order. Parallel arrays
  of call records and result records preserve correlation, while each result
  also contains its `tool_call_id`, tool name, arguments, and `ToolResult`.
- Context propagation: The same caller-supplied `ToolContext` is passed to every
  `ToolRegistry.execute()` call. Stateful tools therefore receive the correct
  `user_id` and `session_id` and retain their existing isolation behavior.
- Ownership and safety: Runtime never closes its injected LLM client. Known API
  keys are redacted recursively from returned messages and step records, and
  LLM boundary errors are converted to concise Runtime categories.

## 2026-07-13: Stage 05A — SQLite Session、消息与 Todo 持久化

- Why SQLite instead of an in-memory dictionary: Session and conversation data
  must survive process restarts. SQLite provides transactional persistence in a
  single local file without adding an ORM or database-server dependency.
- Composite Session key: `(user_id, session_id)` is the primary key because a
  Session id only needs to be unique for one user. This also lets two users use
  the same visible Session id without sharing records.
- No implicit Session creation: Messages and persistent Todos require an
  existing Session. A typo or stale client identifier therefore fails clearly
  instead of silently creating orphaned or unexpected conversation state.
- Session-local Todo ids: The public Todo number is allocated inside each
  `(user_id, session_id)` scope, so every Session begins at 1 and users see
  compact identifiers relevant only to their current conversation.
- Concurrent Todo allocation: A `todo_counters` row stores the next number for
  each scope. Allocation and insertion run in one `BEGIN IMMEDIATE` transaction
  under an `RLock`, preventing duplicate ids and preventing deleted ids from
  being reused.
- Short-lived connections: Every public operation opens, configures, commits or
  rolls back, and closes its own connection. This avoids sharing a SQLite
  connection across threads and makes connection ownership unambiguous.
- Backward-compatible registry: `create_default_registry()` still constructs an
  in-memory `TodoTool`. Persistence is opt-in through `todo_store=...`, so all
  existing callers and tests retain their original behavior.
- Data isolation: Every Session, message, Todo, and counter query binds both
  `user_id` and `session_id`. SQL parameters are bound rather than interpolated,
  and no lookup relies on `session_id` alone.
- Foreign-key cascade: Messages, Todos, and their counter rows reference the
  composite Session key with `ON DELETE CASCADE`. A Session deletion therefore
  removes dependent state atomically without manual multi-query cleanup.
- Why tests use `tmp_path`: Each test receives a separate disposable database,
  has no dependency on execution order, and cannot pollute `data/agent.db` or a
  developer's manual data.

## 2026-07-13: Stage 05B — Session 历史接入 Agent Runtime

- Why add `SessionAgentService`: Persisted conversations require orchestration
  across validation, history loading, Runtime execution, and atomic storage.
  Keeping that workflow in one service gives future HTTP handlers a small,
  testable application boundary.
- Why Runtime does not operate SQLite: `AgentRuntime` remains the stateless core
  LLM/tool loop. It can still be tested with plain history and reused with a
  different store without database branches entering its decision logic.
- When history is recalled: The service verifies the Session and loads existing
  messages immediately before `runtime.run`, before the current user message is
  written. Thus the current input appears exactly once and after prior history.
- Why the user message is not saved first: A Runtime request can fail because of
  configuration, networking, parsing, or step limits. Delayed persistence keeps
  failed attempts from appearing as unanswered conversation turns.
- Why one exchange is atomic: The user input and final assistant answer are one
  logical unit. `add_exchange` inserts both in one transaction and updates the
  Session once, so an assistant insert failure rolls back the user insert too.
- What enters the next Context: Only persisted natural-language `user` input and
  final `assistant` answers are converted to Runtime history, always in stored
  message order.
- What stays in metadata or future Trace: Counts, stop reason, first-seen unique
  tool names, and short reasoning summaries are persisted as compact assistant
  metadata. Full Runtime messages, prompts, tool payloads, headers, secrets, and
  raw HTTP responses are excluded; richer diagnostics belong in a future Trace.
- Why historical tool results are not recalled: Tool payloads can be large,
  stale, and overly influential. The assistant's final natural-language answer
  preserves the user-visible outcome without repeatedly expanding Context.
- User and window isolation: Every service operation and every persistent tool
  call carries both `user_id` and `session_id`. The Store's composite keys and
  bound predicates enforce that pair at the database boundary.
- Normal follow-ups: A direct final answer is atomically saved with the question;
  the next request receives that pair before its new input, enabling ordinary
  conversational continuity.
- Tool-assisted follow-ups: Tool calls/results remain available inside the
  current Runtime loop. After final, only the question, answer, and compact
  metadata persist, so the next request follows the natural-language result.
- Simulated restart: Tests and the manual demo rebuild `SQLiteStore`, registry,
  Runtime, and service against the same database path. Short-lived SQLite
  connections make the reconstructed stack see the previously committed data.
- Purpose of `history_limit`: It bounds only how many recent stored messages are
  supplied to a Runtime invocation. It does not delete or truncate database
  history, and the selected messages remain ordered from old to new.
- Future Context compression: A later layer can inspect message count or token
  estimates, summarize older natural-language turns, and combine that summary
  with recent messages before Runtime execution without changing the Runtime or
  the atomic exchange contract.

## 2026-07-13: Stage 06A — 独立 Context 管理与基础压缩

- Why not send all history: Persisted history grows without a natural upper
  bound. Sending it all makes each request slower and more expensive and can
  ultimately exceed a model's Context window, so recall needs a bounded layer
  even though the database keeps the complete conversation.
- Why approximate characters first: Character length plus fixed message
  overhead is deterministic, dependency-free, and works across providers. It
  is not exact Token counting, but it is sufficient to establish the Context
  boundary without adding a model-specific tokenizer dependency.
- Why compression does not call an LLM: A rule-based summary is reproducible,
  fast, offline-testable, and cannot introduce an extra API failure or charge.
  Its limited semantic quality is an explicit tradeoff for this first layer.
- Why recent messages stay original: The newest turns carry the immediate
  question, references, corrections, and conversational intent. Keeping them
  in chronological order retains more useful local detail than treating all
  history uniformly.
- Why the summary uses `assistant`: The existing Runtime history protocol only
  accepts `user` and `assistant`, while `system` is reserved for the Runtime's
  own instructions. A conspicuous Chinese heading prevents the synthetic
  assistant entry from looking like a current answer.
- Why metadata is excluded: Operational fields such as `reasoning_summary`,
  tool names, Runtime messages, headers, secrets, and raw HTTP responses are not
  natural conversation. Copying only `role` and `content` prevents them from
  leaking into prompts or repeatedly influencing tool choices.
- Avoiding recursive summaries: If the first input entry already begins with
  the project summary heading, its heading and boilerplate are stripped before
  the earlier body is merged into a new summary. The output therefore contains
  at most one generated summary heading instead of nested summaries.
- Handling extreme messages: The manager caps each old entry, caps the combined
  summary, then reduces retained messages from oldest to newest. Every output
  content remains non-empty; if structural overhead alone exceeds a tiny
  `max_chars`, the manager returns legal messages rather than looping or
  failing.
- Limits of basic compression: Character counts do not equal Tokens, and
  prefix truncation cannot identify semantic importance or consolidate facts.
  A future policy may add provider-aware Token estimates or higher-quality
  summaries while preserving the same normalized result boundary.
- Next Session integration: `SessionAgentService` can later pass recalled
  `MessageRecord` values through `BasicContextManager.build()` immediately
  before `runtime.run()`. This keeps persistence complete and leaves the
  Runtime loop unchanged while bounding only the per-request history.

## 2026-07-13: Stage 06B — Session 自动 Context 构建

- Recall timing: `SessionAgentService.chat()` validates the scope, verifies the
  Session, loads stored messages, and immediately calls the Context manager.
  Only the manager's normalized result is passed to the still-stateless Runtime.
- Why `history_limit` runs first: `history_limit` controls database retrieval,
  while Context configuration controls compression of the retrieved window.
  Applying them in that order makes `loaded_history_count` meaningful and
  prevents the manager from processing data the caller explicitly did not
  recall.
- Why SQLite retains full history: Context limits are per-request operational
  limits, not retention policy. Keeping real user/final-assistant messages
  intact supports later audits, different compression policies, and rebuilding
  a better Context without losing source material.
- Why summaries are not persisted: A deterministic summary can be rebuilt from
  source messages on every turn. Writing it back would duplicate information,
  make summaries recursively grow, and mix synthetic content with the user's
  actual conversation.
- Why Context statistics are metadata-safe: Counts and approximate sizes help
  diagnose when compression happened without carrying conversation content.
  They are scalar operational facts, and the next Context build ignores the
  entire metadata object.
- Why summary text stays out of metadata: Persisting the text would duplicate
  sensitive conversation content and could later be mistaken for authoritative
  source history. Compressed messages, system prompts, and HTTP details are
  excluded for the same reason.
- Avoiding nested summaries: Normal Session operation always rebuilds from raw
  database messages, where generated summaries never exist. The manager's own
  one-heading protection remains useful for direct callers and defensive reuse.
- Context error behavior: `ContextCompressionError` propagates before
  `runtime.run()` and before `add_exchange()`. The failed request therefore
  produces no LLM call and no partial user or assistant database row.
- Tool isolation after compression: Compression changes only history messages.
  The service still creates `ToolContext` from the validated `user_id` and
  `session_id`, so persistent tools receive the same scoped identifiers as
  before integration.
- Character-compression limitation: Approximate characters are not model Tokens,
  and prefix truncation does not understand semantic priority. This stage gains
  deterministic bounds without a tokenizer or summarization LLM, leaving those
  possible refinements for later work.

## 2026-07-13: Stage 07 — Agent Trace 持久化

- Why Trace and Context are separate: Context is model input optimized for
  conversational continuity, while Trace is operational evidence optimized for
  debugging. Keeping separate tables and code paths prevents stale tool events
  or diagnostic fields from influencing later model decisions.
- Why only `reasoning_summary` is recorded: The Runtime protocol already asks
  for a concise, user-safe decision summary. Persisting that value explains the
  step without requesting or storing complete hidden chain-of-thought content.
- Why every invocation has a `run_id`: Session ids identify conversation
  windows, not individual executions. A random run id correlates one Context
  build, all LLM/tool events, completion or failure, and a future UI request.
- Why events use `sequence`: Timestamps can tie and are not a reliable ordering
  mechanism. A transactionally allocated per-run integer preserves exact
  decision/call/result order across multiple tools and Runtime steps.
- Tool failures: A tool failure is still a real Runtime result, so Trace records
  its call followed by a `tool_result` with `success=false`, sanitized output,
  and concise error. The next LLM step can then be understood without changing
  Runtime recovery behavior.
- Runtime failures: The service starts Trace before Context construction and
  catches the outer operation only to call `fail_run` and re-raise. Failed
  Context, LLM, parsing, step-limit, or message persistence operations therefore
  create a terminal failed run without becoming successful chat responses.
- Sensitive-data filtering: Trace payloads are recursively copied before write.
  Secret-bearing keys are replaced case-insensitively, named credentials inside
  strings are redacted, and oversized strings are truncated with an explicit
  marker; caller-owned objects remain unchanged.
- Why raw HTTP responses are excluded: They may contain provider diagnostics,
  echoed request material, or other sensitive/large values and are unnecessary
  to reconstruct the Agent's application-level decision and real tool outcome.
- Why Trace cascades with Session deletion: A run has meaning only inside its
  user/Session scope and can contain conversation-derived data. Foreign-key
  cascade makes the Session deletion boundary complete and prevents orphaned
  diagnostic records.
- Future web presentation: `SessionChatResult` returns only `run_id`. A later
  authenticated Trace route can enforce user ownership, call `get_trace`, and
  render the sequence as a timeline without bloating every chat response.

## 2026-07-13: Stage 08 — FastAPI 后端接口

- Why `ApplicationServices`: The API needs one explicit composition root for
  Store, LLM client, tools, Runtime, Context, Trace, and Session orchestration.
  A small container makes ownership visible and lets tests inject a complete
  offline graph without patching globals.
- Why LLM initialization cannot happen at import: Importing `app.main` is used
  by Uvicorn, tests, documentation tools, and health checks. Reading `.env` or
  creating an HTTP client there would make all those operations depend on
  secrets and could fail before FastAPI can serve a useful error.
- Lifespan resource management: Startup creates configured services, or a
  database-only degraded graph when LLM configuration is absent. Shutdown calls
  `close()`; only internally owned clients are closed, so injected test clients
  remain caller-owned.
- Fake LLM injection: API tests construct real Store, registry, Runtime,
  Context, Trace, and Session services around a deterministic Fake client, then
  pass that `ApplicationServices` to `create_app`. No test reads `.env` or uses
  the network.
- Why Chat does not create Sessions: Explicit creation makes titles, ownership,
  window selection, and 404 behavior deterministic. It also prevents typos or
  stale browser state from silently creating new persistence scopes.
- Exception-to-HTTP mapping: Domain exceptions retain their Python behavior in
  lower layers, while FastAPI handlers map missing resources, invalid inputs,
  LLM failures, parse failures, step limits, and persistence failures to stable
  status/code pairs. The chosen step-limit status is HTTP 508.
- Safe error responses: Handlers return fixed, concise messages instead of
  exception text. This prevents API keys, Authorization headers, provider
  response bodies, system prompts, and traceback details from crossing the HTTP
  boundary.
- Why Trace details are separate: Chat returns only `run_id` and compact counts.
  Clients fetch the potentially larger ordered event list on demand, with an
  explicit `user_id` ownership check before disclosure or deletion.
- Why Chat omits Runtime messages: Those messages contain the system Prompt,
  tool-result protocol records, and raw structured model decisions. The API
  needs only the final answer, persisted messages, run id, and operational
  counts for normal UI rendering.
- Future web client: A multi-window page can create/list Sessions, load their
  messages and Todos, post Chat turns, then use returned `run_id` to open a
  lazy Trace timeline. The same composite user/Session identifiers preserve
  isolation across every endpoint.

## 2026-07-13: Stage 09A — 原生多 Session Web UI

- 为什么使用原生 JavaScript：当前界面只有一个页面、少量后端资源和明确的交互边界。ES Modules、`fetch`、`dialog` 与 DOM API 已能覆盖需求，同时保持 FastAPI 直接托管静态文件的零构建流程。
- 为什么不用前端框架：框架会引入 Node、包管理、构建产物与额外升级面。本阶段重点是验证 Agent 的多 Session 主流程，不需要组件生态或客户端路由带来的复杂度。
- 前端状态如何管理：`state.js` 集中保存当前用户、Session 列表、选中项、消息和加载状态；`app.js` 负责事件与渲染；`api.js` 只处理 HTTP 契约。页面不会把 DOM 当成业务状态源。
- 如何避免 Session 响应串线：每次消息加载都有递增请求版本，Chat 请求则捕获发送时的 `user_id + session_id`。响应返回后必须同时匹配当前用户和当前 Session，才允许写入可见消息区。
- 为什么聊天内容不写 localStorage：后端 SQLite 才是完整历史的唯一来源。浏览器只保存用户 ID、选中 Session 和侧栏偏好，避免本地副本陈旧、越界展示或残留敏感对话。
- 如何处理乐观消息：发送时只插入一条标记为 pending 的真实用户输入，不伪造助手答复。成功后用后端返回的 user/assistant 消息替换它；失败时保留输入框内容并将 pending 气泡标为失败。
- 如何避免 XSS：所有 Session 标题、消息、错误与元数据均通过 `textContent` 写入；动态列表使用 `createElement`，不拼接 HTML，不使用 `eval`、`new Function` 或内联事件。
- 为什么 Chat 前必须选择 Session：后端明确拒绝隐式创建，且所有历史、Todo 和 Trace 都以 `user_id + session_id` 为隔离边界。显式选中可避免拼写错误产生意外数据归属。
- 如何展示 Agent 加载状态：发送期间禁用重复提交和删除操作，同时显示“Agent 正在思考和调用工具”；历史加载使用独立骨架。成功消息仅展示紧凑的 LLM、工具和 Context 压缩统计，不展示推理正文。
- 9B 如何增加 Trace 和 Todo 面板：可复用当前 active Session 与 `lastRunId`，按需请求 Trace/Todo API，在聊天主区域旁增加惰性面板；现有 API、状态与 ownership 快照边界无需修改 Agent Runtime。
