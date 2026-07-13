# Minimal Agent Runtime

## Goal

Build a minimal, self-managed Agent runtime step by step without using an Agent
framework. The project currently includes tools, an OpenAI-compatible HTTP
client, a structured Agent output parser, a core Agent Runtime loop, and manual
real-service demos.

## Technology stack

- Python 3.10
- FastAPI and Uvicorn
- Native HTML, CSS, and JavaScript
- SQLite (planned for sessions, messages, todos, and traces)
- pytest

## Current status

The current milestone runs the basic Agent loop: it asks the LLM for a
structured decision, executes requested registered tools, returns real tool
results to the model, and stops when the model produces a final answer.

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

Session persistence, long-term memory, context compression, and persistent
traces remain future milestones.
