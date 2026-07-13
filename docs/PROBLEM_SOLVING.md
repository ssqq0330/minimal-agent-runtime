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
