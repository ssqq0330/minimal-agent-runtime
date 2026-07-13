# Minimal Agent Runtime

## Goal

Build a minimal, self-managed Agent runtime step by step without using an Agent
framework. The project currently includes tools, an OpenAI-compatible HTTP
client, a structured Agent output parser, and a manual LLM smoke test.

## Technology stack

- Python 3.10
- FastAPI and Uvicorn
- Native HTML, CSS, and JavaScript
- SQLite (planned for sessions, messages, todos, and traces)
- pytest

## Current status

The current milestone can ask a configured LLM to choose a tool and parse its
structured decision. It intentionally does not execute the selected tool or run
an Agent loop yet.

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
```

The real tool-execution loop will be connected in stage 04.
