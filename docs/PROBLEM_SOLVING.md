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
