"""System and tool-result prompts for the structured Agent protocol."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def build_agent_system_prompt(tool_schemas: List[Dict[str, Any]]) -> str:
    """Build the Agent system prompt with the available tool schemas."""
    if not isinstance(tool_schemas, list):
        raise ValueError("tool_schemas must be a list.")
    for index, schema in enumerate(tool_schemas):
        if not isinstance(schema, dict):
            raise ValueError("tool_schemas[{}] must be an object.".format(index))

    serialized_schemas = json.dumps(tool_schemas, ensure_ascii=False, indent=2)
    return """你是一个可以使用工具的 Agent。

你需要判断是直接回复用户，还是调用一个或多个工具。只能调用下方工具列表中存在的工具，参数必须严格遵守对应工具 Schema。不得虚构工具执行结果；没有收到真实工具结果前，不能声称工具执行成功。缺少必要信息时，可以使用 final 向用户追问。收到工具执行结果后，可以继续调用工具，或者返回 final。

输出规则：
- 只能输出一个 JSON object。
- 不要输出 Markdown，不要使用代码块，也不要在 JSON 前后添加说明文字。
- 不要输出完整内部思维链。
- reasoning_summary 只能是简短的决策摘要，用于说明为什么直接回答或为什么调用工具。
- 中文用户默认使用中文回复。

final 格式：
{{
  "type": "final",
  "reasoning_summary": "简短决策摘要",
  "answer": "最终回答或需要向用户追问的问题"
}}

tool_call 格式：
{{
  "type": "tool_call",
  "reasoning_summary": "简短决策摘要",
  "tool_calls": [
    {{
      "id": "call_1",
      "name": "工具名称",
      "arguments": {{}}
    }}
  ]
}}

arguments 必须是 JSON object，不要把 arguments 输出为字符串。tool_call 模式不输出 answer；final 模式不输出非空 tool_calls。

可用工具 Schema：
{}""".format(serialized_schemas)


def build_tool_result_message(
    tool_call_id: str,
    tool_name: str,
    result: Dict[str, Any],
) -> str:
    """Serialize one real tool result for the model's next decision."""
    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        raise ValueError("tool_call_id must be a non-empty string.")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("tool_name must be a non-empty string.")
    if not isinstance(result, dict):
        raise ValueError("result must be an object.")

    normalized_result = dict(result)
    normalized_result.setdefault("success", None)
    normalized_result.setdefault("output", None)
    normalized_result.setdefault("error", None)
    payload = {
        "tool_call_id": tool_call_id.strip(),
        "tool_name": tool_name.strip(),
        "result": normalized_result,
    }
    serialized_result = json.dumps(payload, ensure_ascii=False, indent=2)
    return """工具调用结果：
{}

请根据此真实工具结果继续决策。你可以继续调用工具，或者返回 final。不要虚构、修改或伪造工具结果。""".format(
        serialized_result
    )
