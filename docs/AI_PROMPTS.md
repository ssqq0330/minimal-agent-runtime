# AI Prompts

## 2026-07-13: Project initialization

Location: the user request in the current Codex task conversation.

Scope: initialize the Minimal Agent Runtime project skeleton with FastAPI,
static web assets, configuration placeholders, and a health-check test. Do not
implement agent logic, tools, database tables, or LLM requests at this stage.

## 2026-07-13: Tool system

Location: the user request in the current Codex task conversation.

Full prompt:

```text
当前项目第一阶段已经完成，并已提交到 GitHub。

现在开始第二阶段：实现工具系统。

本阶段不要实现 LLM 调用、Agent Runtime、Session API、Context 压缩和网页聊天功能，只实现工具抽象、工具注册机制、三个工具和对应测试。

一、统一工具协议

请在 app/tools/base.py 中实现：

1. ToolContext 数据类

字段：

- user_id: str
- session_id: str

2. ToolResult 数据类

字段：

- success: bool
- output: Any
- error: str | None = None

提供：

- to_dict() 方法

注意项目当前使用 Python 3.10，类型标注需要兼容 Python 3.10。

3. BaseTool 抽象基类

每个工具必须具有：

- name: str
- description: str
- parameters_schema: dict[str, Any]

定义抽象方法：

execute(
    arguments: dict[str, Any],
    context: ToolContext
) -> ToolResult

增加通用方法：

- get_schema()
- validate_arguments(arguments)

get_schema() 返回：

{
  "name": "工具名称",
  "description": "工具描述",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}

参数校验至少支持：

- 必填字段检查
- string
- number
- integer
- boolean
- array
- object
- enum
- additionalProperties=false

参数非法时，不允许产生未捕获异常，应返回清晰的失败结果。

二、工具注册中心

请在 app/tools/registry.py 中实现 ToolRegistry。

功能：

- register(tool: BaseTool)
- unregister(name: str)
- get(name: str) -> BaseTool
- has(name: str) -> bool
- list_tools() -> list[BaseTool]
- get_tool_schemas() -> list[dict[str, Any]]
- execute(name, arguments, context) -> ToolResult

要求：

1. 不允许注册重复名称的工具。
2. 获取不存在的工具时给出清晰错误。
3. 工具执行异常必须由 Registry 捕获，并转换成 ToolResult。
4. 提供 create_default_registry()，自动注册三个默认工具。
5. Registry 自身不能依赖任何 Agent 框架。

三、Calculator 工具

请在 app/tools/calculator.py 中实现 CalculatorTool。

工具名称：

calculator

工具描述：

安全地计算数学表达式，支持加减乘除、乘方、取模和括号。

参数 Schema：

{
  "type": "object",
  "properties": {
    "expression": {
      "type": "string",
      "description": "需要计算的数学表达式"
    }
  },
  "required": ["expression"],
  "additionalProperties": false
}

安全要求：

1. 禁止使用 eval 和 exec。
2. 使用 ast 解析表达式。
3. 只允许：
   - 数字常量
   - 加法
   - 减法
   - 乘法
   - 除法
   - 乘方
   - 取模
   - 一元正负号
   - 括号
4. 拒绝：
   - 变量
   - 函数调用
   - 属性访问
   - 下标访问
   - 导入操作
5. 处理除零错误。
6. 表达式最大长度为 200。
7. 乘方指数绝对值不能超过 100。
8. 计算结果不能是 NaN 或无穷大。
9. 成功时 output 返回：

{
  "expression": "12 * (3 + 2)",
  "result": 60
}

四、Mock Search 工具

请在 app/tools/mock_search.py 中实现 MockSearchTool。

工具名称：

search

工具描述：

从本地模拟知识库搜索相关信息，用于演示 Agent 的搜索工具调用。返回结果不是实时互联网信息。

参数 Schema：

- query：string，必填
- limit：integer，非必填，默认 3，最小 1，最大 5

本地模拟知识库至少包含：

- FastAPI
- Python
- Agent Runtime
- SQLite
- 东京天气
- 北京天气

搜索规则：

1. 根据 query 进行大小写不敏感的关键词匹配。
2. 可以匹配标题或正文。
3. 匹配不到时返回空结果和明确说明，不抛异常。
4. limit 小于 1 或大于 5 时返回参数错误，不要静默修改。
5. output 格式：

{
  "query": "FastAPI",
  "results": [
    {
      "title": "...",
      "snippet": "..."
    }
  ],
  "source": "mock"
}

6. 必须明确标记 source 为 mock，不能伪装成实时搜索。

五、Todo 工具

请在 app/tools/todo.py 中实现 TodoTool。

当前阶段使用线程安全的内存存储，后续再迁移 SQLite。

工具名称：

todo

工具描述：

管理当前用户当前会话中的待办事项，支持添加、查看、完成和删除。

参数 Schema：

- action：string，必填，枚举：
  - add
  - list
  - complete
  - delete
- content：string，添加待办时使用
- todo_id：integer，完成或删除待办时使用

待办必须使用：

user_id + session_id

作为隔离键。

同一用户的不同 session 互不影响，不同用户之间也互不影响。

每条 Todo 包含：

- id
- content
- completed
- created_at

行为要求：

1. add 必须提供非空 content。
2. list 返回当前 user_id 和 session_id 下的全部 Todo。
3. complete 必须提供 todo_id。
4. delete 必须提供 todo_id。
5. Todo 不存在时返回清晰错误。
6. 使用 threading.RLock 保证线程安全。
7. 每个 session 内 todo_id 从 1 开始递增。
8. 提供 clear() 方法，方便测试清空数据。
9. created_at 使用带时区的 ISO 8601 字符串。
10. execute 不允许抛出未捕获异常。

六、导出工具

更新 app/tools/__init__.py，导出：

- BaseTool
- ToolContext
- ToolResult
- ToolRegistry
- CalculatorTool
- MockSearchTool
- TodoTool
- create_default_registry

七、测试

新增 tests/test_tools.py。

至少覆盖：

Calculator：

1. 正常加法。
2. 带括号的乘法。
3. 除零失败。
4. 拒绝 import。
5. 拒绝函数调用。
6. 拒绝变量。
7. 缺少 expression 失败。
8. 额外参数失败。
9. 过长表达式失败。
10. 过大指数失败。

Search：

1. 搜索 FastAPI 有结果。
2. 搜索 Agent 有结果。
3. 搜索未知内容不抛异常。
4. limit 等于 1 时只返回最多一条。
5. limit 大于 5 时失败。
6. limit 小于 1 时失败。
7. 缺少 query 时失败。
8. 额外参数失败。

Todo：

1. 添加待办。
2. 查看待办。
3. 完成待办。
4. 删除待办。
5. 添加空内容失败。
6. 完成时缺少 todo_id 失败。
7. 不同 session 数据隔离。
8. 不同 user 数据隔离。
9. 错误 todo_id 返回失败。
10. clear 可以清空数据。

Registry：

1. 默认包含 calculator、search、todo。
2. 可以获取工具 Schema。
3. 重复注册被拒绝。
4. 调用未知工具返回失败。
5. Registry 能正常执行 calculator。
6. 工具内部抛异常时，Registry 能转换为失败 ToolResult。

要求：

1. 测试之间相互隔离，不能依赖执行顺序。
2. 不修改已经工作的健康检查接口。
3. 不增加不必要的第三方依赖。
4. 不使用 LangChain、LangGraph、OpenHands、OpenClaw 等 Agent 框架。
5. 所有公共方法添加类型标注。
6. 保持实现简单，避免过度设计。
7. 将本阶段使用的完整提示词追加记录到 docs/AI_PROMPTS.md。
8. 将实现过程中的主要设计选择记录到 docs/PROBLEM_SOLVING.md。

完成后：

1. 运行 python -m pytest -q。
2. 修复全部失败测试。
3. 列出创建和修改的文件。
4. 说明工具 Schema 未来如何提供给 LLM。
5. 说明 Todo 如何根据 user_id 和 session_id 隔离。
6. 给出 CMD 下的手动测试命令。
7. 不要自动执行 git commit 或 git push。
```

## 2026-07-13: LLM configuration and HTTP client

Location: the user request in the current Codex task conversation.

Full prompt:

```text
当前项目已经完成并提交：

stage-01：FastAPI 项目骨架
stage-02：工具注册机制，以及 calculator、search、todo

目前完整测试结果为 35 passed。

现在重新开始第三阶段。本次只完成第三阶段的第一部分：LLM 配置和 OpenAI-Compatible HTTP 客户端。

不要实现 Agent Runtime。
不要实现工具调用循环。
不要实现 Agent 输出解析器。
不要实现系统 Prompt。
不要实现 Session、Memory、数据库和网页聊天功能。
不要执行 git commit 或 git push。

项目使用 Python 3.10。

一、实现目标

使用 httpx 自行调用 OpenAI-Compatible Chat Completions API。

不能使用：

- OpenAI SDK
- LangChain
- LangGraph
- OpenAI Agents SDK
- OpenHands
- OpenClaw
- 其他 Agent 框架

二、LLM 异常类型

在 app/llm/client.py 中实现以下异常：

1. LLMError
   - 所有 LLM 相关异常的基类

2. LLMConfigurationError
   - 环境变量或配置错误

3. LLMRequestError
   - 网络错误、超时、HTTP 错误

4. LLMResponseError
   - API 响应结构或内容错误

所有错误信息中都不能包含 API Key。

三、LLMConfig

在 app/llm/client.py 中实现 LLMConfig 数据类。

字段：

- api_key: str
- base_url: str
- model: str
- timeout_seconds: float = 60.0
- temperature: float = 0.0

实现：

@classmethod
from_env(cls) -> "LLMConfig"

要求：

1. 使用 python-dotenv 的 load_dotenv() 读取项目根目录中的 .env。
2. 从以下环境变量读取：

   - LLM_API_KEY
   - LLM_BASE_URL
   - LLM_MODEL
   - LLM_TIMEOUT_SECONDS，可选，默认 60
   - LLM_TEMPERATURE，可选，默认 0

3. API Key、Base URL 或模型名称缺失时，抛出 LLMConfigurationError。
4. 空白字符串也视为缺失。
5. timeout 必须大于 0。
6. temperature 必须是有效数字。
7. base_url 去掉末尾的斜杠。
8. 提供 chat_completions_url 属性。

URL 规则：

如果 base_url 已经以：

/chat/completions

结尾，则直接使用。

否则自动拼接：

/chat/completions

例如：

https://example.com/v1

转换为：

https://example.com/v1/chat/completions

四、LLMResponse

在 app/llm/client.py 中实现 LLMResponse 数据类。

字段：

- content: str
- model: str | None = None
- usage: dict[str, Any] | None = None
- raw_response: dict[str, Any] | None = None

实现：

to_dict() -> dict[str, Any]

五、OpenAICompatibleLLMClient

在 app/llm/client.py 中实现 OpenAICompatibleLLMClient。

初始化：

OpenAICompatibleLLMClient(
    config: LLMConfig,
    http_client: httpx.Client | None = None
)

要求：

1. 没有传入 http_client 时，自行创建 httpx.Client。
2. 自行创建的客户端使用 config.timeout_seconds。
3. 注入的客户端不能由本类擅自关闭。
4. 记录客户端是否由当前对象创建。
5. 提供 close()。
6. 支持 with 上下文管理器：

with OpenAICompatibleLLMClient(config) as client:
    ...

六、消息校验

实现私有方法或独立函数，对 messages 做校验。

complete 接收：

messages: list[dict[str, str]]

要求：

1. messages 必须是非空 list。
2. 每条消息必须是 dict。
3. 每条消息必须包含 role 和 content。
4. role 只能是：

   - system
   - user
   - assistant

5. content 必须是字符串。
6. content 不能只是空白。
7. 参数错误使用 ValueError，错误信息清晰。

七、complete 方法

实现：

complete(
    messages: list[dict[str, str]]
) -> LLMResponse

HTTP 请求：

方法：

POST

URL：

config.chat_completions_url

请求头：

Authorization: Bearer <API_KEY>
Content-Type: application/json

请求体：

{
  "model": config.model,
  "messages": messages,
  "temperature": config.temperature
}

要求：

1. 使用 httpx.Client.post。
2. 正确发送 Authorization 请求头。
3. 正确发送 JSON 请求体。
4. HTTP 4xx 或 5xx 转换为 LLMRequestError。
5. 超时转换为 LLMRequestError。
6. 网络连接错误转换为 LLMRequestError。
7. 返回内容不是 JSON 时转换为 LLMResponseError。
8. 错误中不能包含完整响应内容。
9. 错误中不能包含 API Key。

八、响应解析

支持标准 OpenAI-Compatible 响应：

{
  "id": "chatcmpl-123",
  "model": "example-model",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "模型返回内容"
      }
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  }
}

提取：

- choices[0].message.content
- model
- usage
- 完整 JSON 作为 raw_response

以下情况抛出 LLMResponseError：

1. 顶层不是 JSON object。
2. choices 不存在。
3. choices 不是 list。
4. choices 为空。
5. choices[0] 不是 object。
6. message 不存在。
7. message 不是 object。
8. content 不存在。
9. content 不是字符串。
10. content 是空字符串或只有空白。
11. usage 存在但不是 object。
12. model 存在但不是字符串。

九、模块导出

更新 app/llm/__init__.py，导出：

- LLMError
- LLMConfigurationError
- LLMRequestError
- LLMResponseError
- LLMConfig
- LLMResponse
- OpenAICompatibleLLMClient

十、环境变量示例

更新 .env.example：

LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=60
LLM_TEMPERATURE=0

确认 .gitignore 已经忽略：

.env

不要在代码、测试、README 或日志中写入真实 API Key。

十一、测试

新增：

tests/test_llm_client.py

使用 pytest 和 httpx.MockTransport，禁止调用真实网络。

至少测试：

LLMConfig：

1. 正常读取配置。
2. API Key 缺失。
3. Base URL 缺失。
4. Model 缺失。
5. 空白配置视为缺失。
6. 默认 timeout 为 60。
7. 默认 temperature 为 0。
8. 自定义 timeout 和 temperature。
9. timeout 非数字时报错。
10. timeout 小于等于 0 时报错。
11. temperature 非数字时报错。
12. URL 自动拼接 chat/completions。
13. 已包含 chat/completions 时不重复拼接。
14. Base URL 末尾斜杠处理正确。

消息校验：

15. messages 为空时报错。
16. messages 不是 list 时报错。
17. 单条消息不是 dict 时报错。
18. 缺少 role 时报错。
19. 缺少 content 时报错。
20. role 非法时报错。
21. content 不是字符串时报错。
22. content 为空时报错。

正常请求：

23. 正常解析 content。
24. 正确解析 model。
25. 正确解析 usage。
26. 正确保存 raw_response。
27. 请求地址正确。
28. Authorization 请求头正确。
29. 请求体包含 model。
30. 请求体包含 messages。
31. 请求体包含 temperature。

异常请求：

32. HTTP 401 转换为 LLMRequestError。
33. HTTP 500 转换为 LLMRequestError。
34. 请求超时转换为 LLMRequestError。
35. 网络异常转换为 LLMRequestError。
36. 响应不是 JSON。
37. choices 缺失。
38. choices 不是 list。
39. choices 为空。
40. message 缺失。
41. message 不是 object。
42. content 缺失。
43. content 不是字符串。
44. content 为空。
45. usage 类型错误。
46. model 类型错误。
47. 异常信息中不包含 API Key。
48. close 能关闭内部创建的客户端。
49. close 不关闭外部注入的客户端。
50. 上下文管理器正常工作。

测试要求：

1. 不依赖测试执行顺序。
2. 不调用真实 LLM API。
3. 不修改已有工具测试。
4. 不修改健康检查接口。
5. 运行完整测试。
6. 修复所有失败。
7. 不降低已有测试覆盖。
8. 保持实现简单，不要过度设计。

十二、文档记录

将本次第三阶段第一部分的完整提示词追加到：

docs/AI_PROMPTS.md

在：

docs/PROBLEM_SOLVING.md

记录：

1. 为什么使用 OpenAI-Compatible HTTP API。
2. 为什么使用 httpx 而不是 OpenAI SDK。
3. 如何避免 API Key 泄露。
4. 如何使用依赖注入和 MockTransport 测试网络请求。
5. 为什么区分配置错误、请求错误和响应错误。

十三、完成后

1. 运行：

python -m pytest -q

2. 修复全部失败测试。
3. 输出测试结果。
4. 列出创建和修改的文件。
5. 简要说明请求流程。
6. 给出 CMD 手动检查配置的命令。
7. 不运行真实 API。
8. 不执行 git commit。
9. 不执行 git push。
```

## 2026-07-13: Structured Agent output and prompts

Location: the user request in the current Codex task conversation.

Full prompt:

````text
当前项目已经完成：

stage-01：FastAPI 项目骨架
stage-02：工具注册机制、calculator、search、todo
stage-03A：OpenAI-Compatible LLM 配置与 HTTP 客户端

当前完整测试结果为：

85 passed

现在完成第三阶段第二部分：Agent 结构化输出协议、LLM 输出解析器和系统 Prompt。

本阶段不要实现：

- Agent Runtime Loop
- 工具真正执行流程
- Session 数据库
- Context 压缩
- 网页聊天功能
- 真实 API 冒烟测试
- git commit
- git push

项目使用 Python 3.10。

一、设计目标

LLM 收到用户输入和工具 Schema 后，需要返回两类结构化决策：

1. final：直接返回最终答案
2. tool_call：请求调用一个或多个工具

不要求模型返回完整内部思维链。

只保存一个简短的 reasoning_summary，用于说明：

- 为什么可以直接回答
- 为什么需要调用某个工具

二、ParsedToolCall

在 app/agent/parser.py 中实现 ParsedToolCall 数据类。

字段：

- id: str
- name: str
- arguments: dict[str, Any]

要求：

1. 提供 to_dict()。
2. id 去除首尾空白后不能为空。
3. name 去除首尾空白后不能为空。
4. arguments 必须是 dict。
5. 数据验证主要由解析函数统一完成，数据类保持简单。

示例：

{
  "id": "call_1",
  "name": "calculator",
  "arguments": {
    "expression": "12 * (3 + 2)"
  }
}

三、AgentDecision

在 app/agent/parser.py 中实现 AgentDecision 数据类。

字段：

- type: str
- reasoning_summary: str
- answer: str | None = None
- tool_calls: list[ParsedToolCall] = field(default_factory=list)

提供：

1. to_dict()
2. is_final 属性
3. requires_tools 属性

规则：

- type 只能是 final 或 tool_call
- final：
  - answer 必须是非空字符串
  - tool_calls 必须为空列表
- tool_call：
  - answer 必须为 None
  - tool_calls 至少包含一项

is_final：

type == "final"

requires_tools：

type == "tool_call"

四、解析异常

定义：

AgentOutputParseError

继承 ValueError。

要求：

1. 错误信息清晰。
2. 错误信息不要包含完整模型输出。
3. 最多只允许附带经过截断的少量响应摘要。
4. 不泄露 API Key 等敏感信息。

五、LLM 输出协议

直接回答时：

{
  "type": "final",
  "reasoning_summary": "无需调用工具，可以直接回答。",
  "answer": "最终答案"
}

调用工具时：

{
  "type": "tool_call",
  "reasoning_summary": "用户需要计算数学表达式，因此调用 calculator。",
  "tool_calls": [
    {
      "id": "call_1",
      "name": "calculator",
      "arguments": {
        "expression": "12 * (3 + 2)"
      }
    }
  ]
}

多个工具调用示例：

{
  "type": "tool_call",
  "reasoning_summary": "需要先搜索信息，再记录待办。",
  "tool_calls": [
    {
      "id": "call_1",
      "name": "search",
      "arguments": {
        "query": "东京天气"
      }
    },
    {
      "id": "call_2",
      "name": "todo",
      "arguments": {
        "action": "add",
        "content": "携带雨伞"
      }
    }
  ]
}

六、JSON 提取

在 app/agent/parser.py 中实现：

parse_llm_output(content: str) -> AgentDecision

要求支持：

1. 纯 JSON：

{"type":"final", ...}

2. Markdown JSON 代码块：

```json
{"type":"final", ...}
不带 json 标记的代码块：
{"type":"final", ...}
JSON 前后有少量说明文字：

下面是结果：
{"type":"final", ...}
请根据结果继续。

JSON 字符串内容中包含大括号：

{
"type": "final",
"reasoning_summary": "直接回答",
"answer": "JSON 对象可以写成 {"name":"Agent"}"
}

支持 JSON 中存在嵌套 object 和 array。
只提取第一个可以成功解码的完整 JSON object。
不要使用简单的贪婪正则提取大括号。
推荐使用 json.JSONDecoder().raw_decode()，从候选的 “{” 位置依次尝试。
禁止使用 eval 或 exec。

七、字段校验

parse_llm_output 至少校验：

顶层：

content 必须是非空字符串。
解析结果必须是 JSON object。
type 必须存在且为字符串。
type 只能为 final 或 tool_call。
reasoning_summary 必须存在。
reasoning_summary 必须是字符串。
reasoning_summary 去除空白后不能为空。

final：

answer 必须存在。
answer 必须是字符串。
answer 去除空白后不能为空。
如果存在 tool_calls，必须是空列表。
返回的 AgentDecision.tool_calls 必须为空。

tool_call：

tool_calls 必须存在。
tool_calls 必须是 list。
tool_calls 至少包含一项。
每项必须是 object。
每项必须有 id。
id 必须是非空字符串。
每项必须有 name。
name 必须是非空字符串。
每项必须有 arguments。
arguments 必须是 object。
tool_call 模式下如果 answer 存在且不是 null，应报错。
tool_call id 不要求全局唯一，但同一次决策中的 id 不允许重复。

额外字段可以忽略，不需要因为额外字段直接失败。

八、系统 Prompt

在 app/agent/prompts.py 中实现：

build_agent_system_prompt(
tool_schemas: list[dict[str, Any]]
) -> str

要求：

tool_schemas 必须是 list。
每个 Schema 必须是 dict。
使用 json.dumps：
ensure_ascii=False
indent=2
将工具 Schema 原样嵌入系统 Prompt。
Prompt 必须明确说明：
你是一个可以使用工具的 Agent。
需要判断直接回复还是调用工具。
只能调用工具列表中存在的工具。
参数必须严格遵守工具 Schema。
不得虚构工具执行结果。
没有工具结果前，不能声称工具执行成功。
缺少必要信息时，可以用 final 向用户追问。
收到工具执行结果后，可以继续调用工具或返回 final。
只能输出一个 JSON object。
不要输出 Markdown。
不要在 JSON 前后添加说明文字。
不要输出完整内部思维链。
reasoning_summary 只能是简短决策摘要。
中文用户默认使用中文回复。
Prompt 中明确给出 final 格式：

{
"type": "final",
"reasoning_summary": "简短决策摘要",
"answer": "最终回答或需要向用户追问的问题"
}

Prompt 中明确给出 tool_call 格式：

{
"type": "tool_call",
"reasoning_summary": "简短决策摘要",
"tool_calls": [
{
"id": "call_1",
"name": "工具名称",
"arguments": {}
}
]
}

提醒模型：
arguments 必须是 JSON object
不要把 arguments 输出为字符串
tool_call 模式不输出 answer
final 模式不输出非空 tool_calls

九、工具结果消息

在 app/agent/prompts.py 中实现：

build_tool_result_message(
tool_call_id: str,
tool_name: str,
result: dict[str, Any]
) -> str

要求：

tool_call_id 必须为非空字符串。
tool_name 必须为非空字符串。
result 必须是 dict。
使用 JSON 格式表达结果。
ensure_ascii=False。
内容明确说明：
哪个 call id
哪个工具
是否成功
工具输出或错误
告诉模型：
根据此真实工具结果继续决策
可以继续调用工具
或返回 final
不得修改或伪造工具结果

示例结构可以类似：

工具调用结果：
{
"tool_call_id": "call_1",
"tool_name": "calculator",
"result": {
"success": true,
"output": {
"result": 60
},
"error": null
}
}

请根据真实工具结果继续决策。你可以继续调用工具，或者返回 final。不要虚构或修改工具结果。

十、模块导出

更新 app/agent/init.py，导出：

ParsedToolCall
AgentDecision
AgentOutputParseError
parse_llm_output
build_agent_system_prompt
build_tool_result_message

十一、测试

新增：

tests/test_agent_parser.py
tests/test_prompts.py

Parser 测试至少覆盖：

解析合法 final。
解析合法单工具调用。
解析多个工具调用。
is_final 正确。
requires_tools 正确。
to_dict 正确。
解析 Markdown json 代码块。
解析普通 Markdown 代码块。
从前后文字中提取 JSON。
JSON 字符串包含大括号。
JSON 包含嵌套对象。
JSON 包含数组。
空字符串失败。
纯空白失败。
content 不是字符串失败。
找不到 JSON 失败。
JSON 格式损坏失败。
顶层是数组失败。
type 缺失失败。
type 不是字符串失败。
type 非法失败。
reasoning_summary 缺失失败。
reasoning_summary 不是字符串失败。
reasoning_summary 为空失败。
final 缺少 answer 失败。
final 的 answer 不是字符串失败。
final 的 answer 为空失败。
final 存在非空 tool_calls 失败。
tool_call 缺少 tool_calls 失败。
tool_calls 不是 list 失败。
tool_calls 为空失败。
单个 tool call 不是 object 失败。
id 缺失失败。
id 不是字符串失败。
id 为空失败。
name 缺失失败。
name 不是字符串失败。
name 为空失败。
arguments 缺失失败。
arguments 不是 object 失败。
tool_call 模式包含非空 answer 失败。
同一次决策中的重复 call id 失败。
额外字段不会导致失败。
前面存在无效大括号时，仍能找到后面的合法 JSON。
错误信息不会包含过长的原始模型响应。

Prompt 测试至少覆盖：

默认三个工具名称都出现在 Prompt 中。
calculator 参数 Schema 出现在 Prompt 中。
search 参数 Schema 出现在 Prompt 中。
todo 参数 Schema 出现在 Prompt 中。
Prompt 包含 final 协议。
Prompt 包含 tool_call 协议。
Prompt 明确只能输出 JSON。
Prompt 明确禁止 Markdown。
Prompt 明确禁止虚构工具执行结果。
Prompt 明确要求 arguments 为 object。
Prompt 明确不输出完整思维链。
Prompt 提醒中文用户默认中文回答。
tool_schemas 不是 list 时失败。
Schema 项不是 dict 时失败。
build_tool_result_message 包含 call id。
build_tool_result_message 包含工具名称。
build_tool_result_message 包含 success。
build_tool_result_message 包含 output。
build_tool_result_message 包含 error。
中文内容不会被转义为 Unicode 编码。
空 tool_call_id 失败。
空 tool_name 失败。
result 不是 dict 失败。

十二、文档

把本次完整提示词追加到：

docs/AI_PROMPTS.md

在 docs/PROBLEM_SOLVING.md 记录：

为什么不要求模型输出完整思维链。
reasoning_summary 的作用。
为什么使用明确 JSON 协议。
为什么不能用简单正则提取 JSON。
如何处理 Markdown 代码块和前后说明文字。
为什么工具结果需要带 tool_call_id。
final 和 tool_call 为什么需要互斥字段约束。

十三、限制

不修改 app/llm/client.py，除非修复明确发现的兼容问题。
不修改已有工具行为。
不修改健康检查接口。
不调用真实 API。
不执行工具。
不实现 Agent Runtime。
不实现数据库。
不增加第三方依赖。
不使用 eval 或 exec。
不执行 git commit 或 git push。

十四、完成后

运行完整测试：

python -m pytest -q

单独运行：

python -m pytest tests/test_agent_parser.py tests/test_prompts.py -q

修复全部测试失败。
列出创建和修改的文件。
说明 JSON 提取和验证流程。
给出 CMD 手动测试解析器和 Prompt 的命令。
不执行 git commit。
不执行 git push。
````

## 2026-07-13: Real LLM smoke test

Location: the user request in the current Codex task conversation.

Full prompt:

```text
当前项目已经完成：

stage-01：FastAPI 项目骨架
stage-02：工具注册机制、calculator、search、todo
stage-03A：OpenAI-Compatible LLM HTTP 客户端
stage-03B：Agent JSON 输出解析器和系统 Prompt

现在完成第三阶段第三部分：真实 LLM API 冒烟测试脚本、相关测试和文档。

本阶段不要实现完整 Agent Runtime Loop。
不要真正执行 calculator、search 或 todo。
不要实现 Session、Memory、数据库和网页聊天。
不要执行 git commit 或 git push。

项目使用 Python 3.10。

一、实现真实 LLM 冒烟测试脚本

创建：

scripts/__init__.py
scripts/llm_smoke_test.py

运行方式：

python -m scripts.llm_smoke_test

脚本需要完成以下流程：

1. 从 .env 读取真实 LLM 配置。
2. 使用 LLMConfig.from_env() 创建配置。
3. 使用 create_default_registry() 创建默认工具注册中心。
4. 使用 registry.get_tool_schemas() 获取工具 Schema。
5. 使用 build_agent_system_prompt() 构造系统 Prompt。
6. 构造 messages：

[
  {
    "role": "system",
    "content": "系统 Prompt"
  },
  {
    "role": "user",
    "content": "请帮我计算 12 * (3 + 2)"
  }
]

7. 使用 OpenAICompatibleLLMClient.complete() 调用真实 API。
8. 打印：
   - 当前模型名称
   - API 返回的原始 content
   - parse_llm_output() 解析后的 AgentDecision
9. 不真正执行 calculator。
10. 不打印 API Key。
11. 不打印 Authorization 请求头。
12. API 调用结束后正确关闭客户端。

二、输出格式

正常情况下，终端输出类似：

=== Minimal Agent LLM Smoke Test ===
Model: example-model

Raw LLM content:
{
  "type": "tool_call",
  "reasoning_summary": "用户需要计算数学表达式，因此调用 calculator。",
  "tool_calls": [
    {
      "id": "call_1",
      "name": "calculator",
      "arguments": {
        "expression": "12 * (3 + 2)"
      }
    }
  ]
}

Parsed decision:
{
  "type": "tool_call",
  "reasoning_summary": "用户需要计算数学表达式，因此调用 calculator。",
  "answer": null,
  "tool_calls": [
    {
      "id": "call_1",
      "name": "calculator",
      "arguments": {
        "expression": "12 * (3 + 2)"
      }
    }
  ]
}

Smoke test passed: LLM selected calculator.

三、冒烟测试判定

脚本需要进行基础验证：

1. AgentDecision.type 必须是 tool_call。
2. tool_calls 中至少有一个 name 为 calculator。
3. calculator 的 arguments 中必须包含 expression。
4. expression 不要求与原始字符串完全相同，但必须是非空字符串。
5. 满足条件时输出：

Smoke test passed: LLM selected calculator.

6. 如果模型返回 final，输出清晰错误。
7. 如果模型选择了错误工具，输出清晰错误。
8. 如果 JSON 解析失败，输出清晰错误。
9. 如果 API 配置错误，输出清晰错误。
10. 如果请求失败，输出清晰错误。
11. 如果响应格式错误，输出清晰错误。
12. 失败时程序使用非零退出码。
13. 成功时退出码为 0。
14. 错误输出中不能出现 API Key。

四、代码结构

为了便于测试，不要把所有逻辑都堆在 main() 中。

建议实现：

DEFAULT_SMOKE_PROMPT = "请帮我计算 12 * (3 + 2)"

def build_smoke_messages(
    tool_schemas: list[dict[str, Any]],
    user_prompt: str = DEFAULT_SMOKE_PROMPT
) -> list[dict[str, str]]

def validate_smoke_decision(
    decision: AgentDecision
) -> None

def run_smoke_test(
    config: LLMConfig | None = None,
    llm_client: OpenAICompatibleLLMClient | None = None,
    user_prompt: str = DEFAULT_SMOKE_PROMPT
) -> AgentDecision

def main() -> int

要求：

1. run_smoke_test 支持注入假的 LLM Client，方便测试。
2. 外部注入的客户端不由脚本关闭。
3. 脚本内部创建的客户端必须关闭。
4. main() 捕获预期异常并返回非零退出码。
5. 文件结尾使用：

if __name__ == "__main__":
    raise SystemExit(main())

五、不要执行工具

本阶段只验证模型是否能够根据工具 Schema 选择工具。

不能调用：

registry.execute(...)

不能直接执行 CalculatorTool。

最终结果不应该是数字 60。

真正执行工具将在第四阶段 Agent Runtime Loop 中完成。

六、测试

新增：

tests/test_llm_smoke_test.py

测试中禁止访问真实网络。

使用假的 LLM Client 或 httpx.MockTransport。

至少测试：

1. build_smoke_messages 返回 system 和 user 两条消息。
2. system 消息包含 calculator。
3. system 消息包含 search。
4. system 消息包含 todo。
5. user 消息包含默认计算请求。
6. 支持传入自定义 user_prompt。
7. 合法 calculator 决策验证通过。
8. calculator arguments 包含 expression。
9. decision 为 final 时验证失败。
10. decision 为 tool_call 但没有 calculator 时失败。
11. tool_calls 为空时失败。
12. calculator 缺少 expression 时失败。
13. expression 不是字符串时失败。
14. expression 为空字符串时失败。
15. run_smoke_test 能调用注入的假客户端。
16. run_smoke_test 能解析合法模型响应。
17. run_smoke_test 返回 AgentDecision。
18. 注入的客户端不会被关闭。
19. 内部创建客户端时最终会关闭。
20. 配置错误被 main 捕获。
21. 请求错误被 main 捕获。
22. 响应错误被 main 捕获。
23. JSON 解析错误被 main 捕获。
24. 验证失败时 main 返回非零状态。
25. 成功时 main 返回 0。
26. 输出内容不包含 API Key。

测试要求：

1. 不调用真实 LLM。
2. 不依赖 .env 中存在真实配置。
3. 测试之间相互隔离。
4. 不修改现有工具和 LLM Client 行为。
5. 不修改健康检查接口。
6. 运行完整测试并修复全部失败。

七、更新环境变量示例

确认 .env.example 内容至少为：

LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=60
LLM_TEMPERATURE=0

确认 .gitignore 包含：

.env

不能将真实 API Key 写入：

- .env.example
- README.md
- 测试代码
- docs
- 日志
- Git 提交

八、更新 README

README 增加以下部分：

1. LLM 配置方法

Windows CMD：

copy .env.example .env
notepad .env

配置示例：

LLM_API_KEY=your_api_key
LLM_BASE_URL=https://example.com/v1
LLM_MODEL=example-model
LLM_TIMEOUT_SECONDS=60
LLM_TEMPERATURE=0

必须注明：

- example 内容只是占位符
- 不要提交 .env
- 项目使用 OpenAI-Compatible Chat Completions API

2. 运行冒烟测试

python -m scripts.llm_smoke_test

3. 冒烟测试说明

说明当前脚本只测试：

- 真实 API 能否调用
- 模型能否看到 Tool Schema
- 模型能否选择 calculator
- 模型输出能否被解析

暂时不会执行工具。

4. 当前系统架构

增加：

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

并注明：

第四阶段才会接入真正的工具执行循环。

九、更新文档

把本阶段完整提示词追加到：

docs/AI_PROMPTS.md

在 docs/PROBLEM_SOLVING.md 记录：

1. 为什么需要真实 API 冒烟测试。
2. 为什么冒烟测试只验证工具选择而不执行工具。
3. 为什么脚本支持注入假客户端。
4. 如何防止 API Key 出现在日志和异常中。
5. 如何判定模型成功选择 calculator。
6. 模型没有严格返回 JSON 时如何定位问题。
7. 不同 OpenAI-Compatible 服务可能存在的响应差异。
8. 为什么完整 Agent Loop 放到下一阶段实现。

十、限制

1. 不实现 Agent Runtime Loop。
2. 不调用 ToolRegistry.execute。
3. 不执行 calculator。
4. 不实现 Session。
5. 不实现数据库。
6. 不修改网页。
7. 不增加 Agent 框架。
8. 不增加 OpenAI SDK。
9. 不使用 eval 或 exec。
10. 不运行真实 API，真实 API 由用户手动配置后运行。
11. 不执行 git commit。
12. 不执行 git push。

十一、完成后

1. 运行：

python -m pytest -q

2. 单独运行：

python -m pytest tests/test_llm_smoke_test.py -q

3. 修复全部失败。
4. 列出创建和修改的文件。
5. 说明冒烟测试执行流程。
6. 给出 Windows CMD 下配置 .env 的命令。
7. 给出运行真实冒烟测试的命令。
8. 不执行 git commit 或 git push。
```

## 2026-07-13: Core Agent Runtime loop

Location: the user request in the current Codex task conversation.

Full prompt:

```text
当前项目已经完成：

stage-01：FastAPI 项目骨架
stage-02：工具注册机制、calculator、search、todo
stage-03：真实 LLM HTTP 客户端、结构化输出解析器、系统 Prompt 和真实 API 冒烟测试

现在开始第四阶段：自行实现 Agent Runtime 基本循环。

这一阶段是项目的核心。禁止使用 LangChain、LangGraph、OpenAI Agents SDK、OpenHands、OpenClaw 或其他 Agent 框架。

本阶段先实现 Runtime 核心和自动化测试，不实现 Session 数据库、Context 压缩、网页聊天和持久化 Trace。

项目使用 Python 3.10。

一、目标流程

Agent Runtime 必须自行实现以下循环：

1. 接收用户输入。
2. 构造 system、history、user 消息。
3. 调用真实或注入的 LLM Client。
4. 使用 parse_llm_output 解析模型输出。
5. 如果是 final，结束并返回答案。
6. 如果是 tool_call：
   - 根据工具名称从 ToolRegistry 查找工具
   - 使用参数 Schema 校验并执行工具
   - 将真实工具结果交还给 LLM
7. LLM 根据工具结果决定：
   - 继续调用工具
   - 或返回 final
8. 超过最大循环次数时终止。

二、实现位置

主要实现：

app/agent/runtime.py

可以按需要少量更新：

app/agent/__init__.py
app/observability/trace.py

不要修改已有工具的公开行为。
不要修改 LLM Client 的公开行为。
不要修改 parser 的协议。

三、Runtime 异常

在 app/agent/runtime.py 中实现：

1. AgentRuntimeError
   - Runtime 异常基类

2. AgentInputError
   - 用户输入或 history 不合法

3. AgentMaxStepsError
   - 达到最大循环次数仍没有 final

4. AgentLLMError
   - LLM 请求或响应失败

5. AgentDecisionError
   - 模型输出无法解析或决策不合法

错误信息必须清晰，并且不能包含 API Key。

四、步骤记录

实现 AgentStep 数据类。

字段至少包含：

- step_number: int
- decision_type: str
- reasoning_summary: str
- tool_calls: list[dict[str, Any]]
- tool_results: list[dict[str, Any]]
- model: str | None = None

提供：

- to_dict()

要求：

1. 只记录 reasoning_summary。
2. 不记录或虚构完整内部思维链。
3. tool_results 必须来自真实 ToolRegistry.execute 返回值。
4. 不记录 Authorization 请求头和 API Key。

五、运行结果

实现 AgentRunResult 数据类。

字段至少包含：

- answer: str
- steps: list[AgentStep]
- messages: list[dict[str, str]]
- total_llm_calls: int
- total_tool_calls: int
- stopped_reason: str = "final"

提供：

- to_dict()

要求：

1. answer 必须是最终 final 决策中的回答。
2. steps 保存每次 LLM 决策及对应工具结果。
3. messages 保存本次运行中实际使用的上下文消息。
4. stopped_reason 正常结束时为 final。
5. 返回对象不能包含 API Key。

六、AgentRuntime 初始化

实现：

AgentRuntime(
    llm_client: OpenAICompatibleLLMClient,
    tool_registry: ToolRegistry,
    max_steps: int = 8
)

要求：

1. llm_client 和 tool_registry 必须提供。
2. max_steps 必须是大于 0 的整数。
3. Runtime 不负责关闭外部传入的 LLM Client。
4. Runtime 不在初始化时调用网络。

七、run 方法

实现：

run(
    user_input: str,
    context: ToolContext,
    history: list[dict[str, str]] | None = None
) -> AgentRunResult

输入校验：

1. user_input 必须是非空字符串。
2. context 必须是 ToolContext。
3. history 为 None 时视为空列表。
4. history 必须是 list。
5. history 每项必须是 dict。
6. history 中 role 只允许：
   - user
   - assistant
7. history 中 content 必须是非空字符串。
8. history 不允许调用者传入 system 消息。
9. 不直接修改调用者传入的 history。

初始 messages：

[
  {
    "role": "system",
    "content": build_agent_system_prompt(tool_registry.get_tool_schemas())
  },
  ...history,
  {
    "role": "user",
    "content": user_input
  }
]

八、Runtime 循环

每一步执行：

1. 调用：

llm_client.complete(messages)

2. total_llm_calls 加 1。

3. 使用：

parse_llm_output(response.content)

解析决策。

4. 将模型的原始结构化 content 作为 assistant 消息加入 messages：

{
  "role": "assistant",
  "content": response.content
}

5. 如果 decision.type == final：

- 创建 AgentStep
- 返回 AgentRunResult
- 不执行任何工具

6. 如果 decision.type == tool_call：

按 tool_calls 原顺序执行每个工具：

tool_registry.execute(
    name=tool_call.name,
    arguments=tool_call.arguments,
    context=context
)

7. 每次工具调用后：

- total_tool_calls 加 1
- 保存 ToolResult.to_dict()
- 使用 build_tool_result_message 构造消息
- 以 user role 加入 messages

消息形式：

{
  "role": "user",
  "content": build_tool_result_message(...)
}

因为当前 LLM Client 只支持 system、user、assistant，不使用 tool role。

8. 一次决策包含多个 tool_calls 时：

- 全部按顺序执行
- 每个结果分别加入 messages
- 然后进行下一次 LLM 调用

9. 工具返回 success=false 时：

- 不立即终止 Runtime
- 将失败结果原样交给 LLM
- 允许 LLM 修改参数、调用其他工具或返回 final

10. 未知工具：

- ToolRegistry 应返回失败 ToolResult
- Runtime 将失败结果交给 LLM
- 不产生未捕获异常

11. 达到 max_steps 且仍未得到 final：

抛出 AgentMaxStepsError。

九、异常处理

1. LLMConfigurationError、LLMRequestError、LLMResponseError：
   - 转换成 AgentLLMError
   - 保留简洁错误原因
   - 不包含 API Key

2. AgentOutputParseError：
   - 转换成 AgentDecisionError

3. 工具内部异常：
   - 应由 ToolRegistry 转换成失败 ToolResult
   - Runtime 不应崩溃

4. 不要使用宽泛的 except Exception 隐藏程序错误。
5. 可以在边界处捕获异常，但必须保留明确分类。

十、工具结果关联

AgentStep.tool_calls 和 tool_results 必须保持相同顺序。

每条工具结果记录建议包含：

{
  "tool_call_id": "call_1",
  "tool_name": "calculator",
  "arguments": {
    "expression": "12 * (3 + 2)"
  },
  "result": {
    "success": true,
    "output": {
      "expression": "12 * (3 + 2)",
      "result": 60
    },
    "error": null
  }
}

这样后续网页 Trace 可以直接展示。

十一、模块导出

更新 app/agent/__init__.py，导出：

- AgentRuntime
- AgentStep
- AgentRunResult
- AgentRuntimeError
- AgentInputError
- AgentMaxStepsError
- AgentLLMError
- AgentDecisionError

保留已有 parser 和 prompts 导出。

十二、Fake LLM 测试辅助

在 tests 中实现简单的 FakeLLMClient，不需要放入正式生产代码。

Fake Client：

1. 构造时接收预设 response content 列表。
2. complete 每调用一次，返回下一个 LLMResponse。
3. 保存每次收到的 messages，方便断言。
4. 响应耗尽时给出明确错误。
5. 不调用真实网络。

十三、测试

新增：

tests/test_agent_runtime.py

至少覆盖：

输入与初始化：

1. max_steps 正常初始化。
2. max_steps 等于 0 失败。
3. max_steps 为负数失败。
4. max_steps 不是整数失败。
5. user_input 为空失败。
6. user_input 不是字符串失败。
7. context 类型错误失败。
8. history 不是列表失败。
9. history 项不是 dict 失败。
10. history 包含 system role 失败。
11. history role 非法失败。
12. history content 为空失败。
13. 不修改原始 history。

直接回答：

14. 第一次 LLM 返回 final。
15. answer 正确。
16. total_llm_calls 等于 1。
17. total_tool_calls 等于 0。
18. steps 只有一项。
19. stopped_reason 为 final。
20. messages 包含 system、user、assistant。
21. system Prompt 中包含三个工具 Schema。

单工具循环：

22. 第一次返回 calculator tool_call。
23. Runtime 真实执行 calculator。
24. 工具结果中 result 等于 60。
25. 第二次 LLM 返回 final。
26. total_llm_calls 等于 2。
27. total_tool_calls 等于 1。
28. 第二次 LLM 收到真实工具结果。
29. 工具结果消息包含 call_1。
30. 工具结果消息包含 calculator。
31. 工具结果消息包含 60。

多工具调用：

32. 一次决策包含 search 和 todo。
33. 两个工具都按顺序执行。
34. total_tool_calls 等于 2。
35. 第二次 LLM 收到两个工具结果。
36. AgentStep 中 tool_calls 与 tool_results 顺序一致。

继续循环：

37. 第一轮调用工具。
38. 第二轮再次调用工具。
39. 第三轮返回 final。
40. total_llm_calls 等于 3。
41. steps 数量等于 3。

失败恢复：

42. calculator 除零返回失败。
43. Runtime 不立即终止。
44. 失败结果被传给 LLM。
45. LLM 可以随后返回 final。
46. 未知工具不会导致 Runtime 崩溃。
47. 未知工具结果 success=false。
48. 未知工具错误被传给下一次 LLM。

Session Context：

49. Todo 工具收到正确 user_id。
50. Todo 工具收到正确 session_id。
51. 相同 Runtime 使用不同 context 时 Todo 相互隔离。

异常：

52. LLMRequestError 转换为 AgentLLMError。
53. LLMResponseError 转换为 AgentLLMError。
54. 解析失败转换为 AgentDecisionError。
55. 达到 max_steps 抛出 AgentMaxStepsError。
56. max_steps 场景不会无限循环。

结果与安全：

57. AgentRunResult.to_dict 正确。
58. AgentStep.to_dict 正确。
59. 不包含完整内部思维链字段。
60. 返回内容不包含 API Key。
61. Runtime 不关闭外部 LLM Client。

测试要求：

1. 不调用真实网络。
2. 不依赖 .env。
3. 测试之间相互隔离。
4. 不依赖执行顺序。
5. 保留此前所有测试。
6. 修复全部测试失败。

十四、真实 Runtime 演示脚本

创建：

scripts/agent_runtime_demo.py

运行方式：

python -m scripts.agent_runtime_demo

流程：

1. 从 .env 加载真实 LLM 配置。
2. 创建 OpenAICompatibleLLMClient。
3. 创建默认 ToolRegistry。
4. 创建 AgentRuntime，max_steps=5。
5. 创建：

ToolContext(
    user_id="demo-user",
    session_id="demo-session"
)

6. 调用：

runtime.run(
    user_input="请帮我计算 12 * (3 + 2)，并告诉我结果。",
    context=context
)

7. 打印：
   - 最终 answer
   - total_llm_calls
   - total_tool_calls
   - 每一步 reasoning_summary
   - 工具名称、参数和结果

8. 不打印 API Key。
9. 确保关闭 LLM Client。
10. 出错时清晰输出并使用非零退出码。

这次真实演示应该真正执行 calculator，并最终得到与 60 一致的回答。

十五、文档

1. 更新 README，增加 Agent Runtime Loop 说明。
2. 增加真实 Runtime 演示命令：

python -m scripts.agent_runtime_demo

3. 明确区分：
   - llm_smoke_test：只验证模型选择工具
   - agent_runtime_demo：真正执行工具并继续 Loop

4. 将本次完整提示词追加到 docs/AI_PROMPTS.md。
5. 在 docs/PROBLEM_SOLVING.md 记录：
   - Runtime Loop 如何实现
   - 为什么工具失败后仍交还给 LLM
   - 为什么设置 max_steps
   - 为什么当前工具结果使用 user role
   - 为什么只记录 reasoning_summary
   - 多工具调用如何保持顺序
   - Runtime 如何传递 user_id 和 session_id

十六、限制

1. 不实现 SQLite Session。
2. 不实现长期 Memory。
3. 不实现 Context 压缩。
4. 不实现网页聊天。
5. 不持久化 Trace。
6. 不修改现有工具公开行为。
7. 不使用 Agent 框架。
8. 不自动执行 git commit 或 git push。

十七、完成后

1. 运行：

python -m pytest -q

2. 单独运行：

python -m pytest tests/test_agent_runtime.py -q

3. 修复全部失败测试。
4. 列出创建和修改的文件。
5. 说明 Runtime 一次完整循环。
6. 给出真实 Runtime Demo 的运行命令。
7. 不执行 git commit。
8. 不执行 git push。
```

## 2026-07-13: Stage 05A — SQLite Session、消息与 Todo 持久化

```text
当前项目已经完成：

stage-01：FastAPI 项目骨架
stage-02：工具注册机制、calculator、search、todo
stage-03：真实 LLM Client、结构化输出解析器、Prompt
stage-04：自行实现 Agent Runtime Loop

现在开始第五阶段第一部分：SQLite Session、消息和 Todo 持久化。

本阶段只实现数据存储层，以及持久化 Todo 接入能力。

暂时不要实现：

- Chat API
- Session API 路由
- 网页多窗口界面
- Context 压缩
- Runtime 自动读取和写入历史
- Trace 持久化
- 长期 Memory
- git commit
- git push

项目使用 Python 3.10。

禁止使用 ORM、LangChain、LangGraph 或其他 Agent 框架。
使用 Python 标准库 sqlite3 自行实现。

一、总体目标

使用 SQLite 保存：

1. 用户的多个 Session
2. 每个 Session 的消息历史
3. 每个 Session 独立的 Todo

必须满足：

用户 A 的 session-1 和 session-2 完全隔离。

用户 B 即使使用相同的 session_id，也不能读取用户 A 的数据。

程序重新启动、重新创建 SQLiteStore 对象后，历史数据仍然存在。

二、数据库实现位置

主要修改：

app/memory/store.py

按需要更新：

app/memory/__init__.py
app/tools/todo.py
app/tools/registry.py
app/tools/__init__.py

新增测试：

tests/test_memory_store.py
tests/test_persistent_todo.py

数据库默认位置：

data/agent.db

测试必须使用 pytest 的 tmp_path 创建临时数据库，禁止污染正式 data/agent.db。

三、时间处理

所有时间使用：

datetime.now(timezone.utc).isoformat()

即带 UTC 时区的 ISO 8601 字符串。

不要使用没有时区信息的 datetime.utcnow()。

四、数据结构

在 app/memory/store.py 中实现以下数据类。

1. SessionRecord

字段：

- user_id: str
- session_id: str
- title: str
- created_at: str
- updated_at: str

提供：

- to_dict()

2. MessageRecord

字段：

- id: int
- user_id: str
- session_id: str
- role: str
- content: str
- created_at: str
- metadata: dict[str, Any] | None = None

提供：

- to_dict()

3. TodoRecord

字段：

- id: int
- user_id: str
- session_id: str
- content: str
- completed: bool
- created_at: str
- completed_at: str | None = None

提供：

- to_dict()

注意：

TodoRecord.id 是当前 user_id + session_id 范围内的待办编号。

每个 Session 的 Todo id 都从 1 开始。

五、SQLiteStore 初始化

实现：

SQLiteStore(
    db_path: str | Path = "data/agent.db"
)

要求：

1. db_path 同时支持 str 和 pathlib.Path。
2. 自动创建数据库父目录。
3. 初始化时自动创建数据库表。
4. 使用 sqlite3。
5. 每个数据库连接设置：

PRAGMA foreign_keys = ON

6. 文件数据库建议设置：

PRAGMA journal_mode = WAL

7. 设置 sqlite3.Row 作为 row_factory。
8. 不要在对象中长期共享一个 SQLite connection。
9. 每个公开操作自行获取短生命周期连接。
10. 使用上下文管理器正确提交和关闭连接。
11. 增加 threading.RLock，保护初始化及必要的写操作。
12. 提供 initialize()，重复执行不会报错。
13. SQLiteStore 初始化后即可使用。

六、数据库表

实现以下表。

1. sessions

字段：

- user_id TEXT NOT NULL
- session_id TEXT NOT NULL
- title TEXT NOT NULL
- created_at TEXT NOT NULL
- updated_at TEXT NOT NULL

联合主键：

PRIMARY KEY (user_id, session_id)

2. messages

字段：

- id INTEGER PRIMARY KEY AUTOINCREMENT
- user_id TEXT NOT NULL
- session_id TEXT NOT NULL
- role TEXT NOT NULL
- content TEXT NOT NULL
- metadata_json TEXT
- created_at TEXT NOT NULL

外键：

FOREIGN KEY (user_id, session_id)
REFERENCES sessions(user_id, session_id)
ON DELETE CASCADE

增加适合按 Session 和顺序查询消息的索引。

3. todos

字段：

- user_id TEXT NOT NULL
- session_id TEXT NOT NULL
- todo_id INTEGER NOT NULL
- content TEXT NOT NULL
- completed INTEGER NOT NULL DEFAULT 0
- created_at TEXT NOT NULL
- completed_at TEXT

联合主键：

PRIMARY KEY (user_id, session_id, todo_id)

外键：

FOREIGN KEY (user_id, session_id)
REFERENCES sessions(user_id, session_id)
ON DELETE CASCADE

增加适合按 Session 查询 Todo 的索引。

七、输入校验

所有公开方法都要进行基础校验。

user_id：

- 必须是字符串
- 去除首尾空白后不能为空

session_id：

- 必须是字符串
- 去除首尾空白后不能为空

title：

- 必须是字符串
- 去除首尾空白后不能为空
- 最大长度建议 200

content：

- 必须是字符串
- 去除首尾空白后不能为空

role：

只允许：

- user
- assistant

metadata：

- 必须是 dict 或 None
- 必须能够被 json.dumps 序列化

todo_id：

- 必须是大于 0 的整数
- bool 不能被视为合法整数

错误使用 ValueError 或清晰的自定义异常。

八、Session 操作

实现：

create_session(
    user_id: str,
    session_id: str | None = None,
    title: str = "新会话"
) -> SessionRecord

规则：

1. session_id 为 None 时，使用 uuid.uuid4().hex 生成。
2. 同一个 user_id 下不能创建重复 session_id。
3. 不同 user_id 可以使用相同 session_id。
4. 重复创建时返回明确错误，不要静默覆盖。

实现：

get_session(
    user_id: str,
    session_id: str
) -> SessionRecord | None

必须同时匹配 user_id 和 session_id。

实现：

list_sessions(
    user_id: str
) -> list[SessionRecord]

规则：

- 只返回当前用户的 Session
- 按 updated_at 降序
- 最新更新的 Session 在前

实现：

update_session_title(
    user_id: str,
    session_id: str,
    title: str
) -> SessionRecord

Session 不存在时返回明确错误。

实现：

touch_session(
    user_id: str,
    session_id: str
) -> SessionRecord

更新 updated_at。

实现：

delete_session(
    user_id: str,
    session_id: str
) -> bool

规则：

- 删除存在的 Session 返回 True
- 不存在返回 False
- 删除 Session 后，其 messages 和 todos 应通过外键级联删除
- 不能删除其他用户相同 session_id 的 Session

九、消息操作

实现：

add_message(
    user_id: str,
    session_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None
) -> MessageRecord

规则：

1. Session 必须已经存在。
2. 不允许自动创建 Session。
3. 保存消息后更新 Session.updated_at。
4. metadata 使用 JSON 保存。
5. ensure_ascii=False。
6. 返回保存后的 MessageRecord。

实现：

list_messages(
    user_id: str,
    session_id: str,
    limit: int | None = None
) -> list[MessageRecord]

规则：

1. 必须只读取指定用户和 Session。
2. 默认返回全部消息。
3. 按消息 id 升序，也就是从旧到新。
4. limit 必须是大于 0 的整数。
5. limit 表示返回最近 N 条消息。
6. 即使查询最近 N 条，最终返回顺序仍然为旧到新。
7. Session 不存在时返回空列表或明确的统一行为，并在测试中固定下来。
8. 不允许读取其他用户的数据。

实现：

count_messages(
    user_id: str,
    session_id: str
) -> int

实现：

clear_messages(
    user_id: str,
    session_id: str
) -> int

返回删除的消息数量，但不删除 Session。

十、Todo 操作

在 SQLiteStore 中实现：

add_todo(
    user_id: str,
    session_id: str,
    content: str
) -> TodoRecord

规则：

1. Session 必须存在。
2. todo_id 在当前 user_id + session_id 内从 1 开始递增。
3. 不同 Session 各自从 1 开始。
4. 删除 Todo 后，不复用旧 id。
5. 为避免并发重复 id，写入过程使用事务。
6. 可使用 BEGIN IMMEDIATE 加写锁。
7. 保存后更新 Session.updated_at。

实现：

list_todos(
    user_id: str,
    session_id: str
) -> list[TodoRecord]

按 todo_id 升序。

实现：

complete_todo(
    user_id: str,
    session_id: str,
    todo_id: int
) -> TodoRecord

规则：

- 设置 completed=True
- 设置 completed_at
- 已完成的 Todo 再次完成应保持幂等，不报错
- Todo 不存在时返回明确错误

实现：

delete_todo(
    user_id: str,
    session_id: str,
    todo_id: int
) -> bool

存在时返回 True，不存在时返回 False。

实现：

clear_todos(
    user_id: str,
    session_id: str
) -> int

返回删除数量。

十一、持久化 TodoTool

当前 TodoTool 使用内存保存。

要求在不破坏现有测试和行为的基础上，让它支持可选 SQLiteStore。

修改 TodoTool 构造方法，例如：

TodoTool(store: SQLiteStore | None = None)

规则：

1. store 为 None 时，继续使用当前线程安全内存模式。
2. store 不为 None 时，使用 SQLiteStore 的 Todo 方法。
3. 工具对外 Schema、名称和 action 行为保持不变。
4. add：
   - 如果 SQLite Session 不存在，返回清晰失败 ToolResult
5. list、complete、delete 使用 context.user_id 和 context.session_id。
6. 返回的 Todo 字段与之前兼容。
7. clear()：
   - 内存模式继续清空内存数据
   - SQLite 模式不得危险地删除所有用户数据库数据
   - SQLite 模式可以明确要求指定 context，或者提供安全的测试辅助方法
8. 不允许 TodoTool 自行创建 Session。

十二、默认工具注册

修改：

create_default_registry(...)

使其支持可选参数：

create_default_registry(
    todo_store: SQLiteStore | None = None
) -> ToolRegistry

规则：

1. 不传 todo_store 时，行为与之前完全相同。
2. 传入 todo_store 时，TodoTool 使用 SQLite 持久化。
3. calculator 和 search 不受影响。
4. 保持所有已有调用兼容。

十三、模块导出

更新 app/memory/__init__.py，导出：

- SQLiteStore
- SessionRecord
- MessageRecord
- TodoRecord

保留其他已有导出。

十四、数据库异常处理

可以定义：

MemoryStoreError
SessionNotFoundError
TodoNotFoundError
DuplicateSessionError

要求：

1. 错误分类清晰。
2. 不向调用者暴露很长的原始 SQL。
3. 不泄露 API Key。
4. 不使用宽泛 except Exception 吞掉编程错误。
5. sqlite3.IntegrityError 应在适当位置转换为明确错误。
6. 数据库损坏等 sqlite3.Error 可以转换为 MemoryStoreError。

十五、测试 SQLiteStore

新增：

tests/test_memory_store.py

至少覆盖：

初始化：

1. 创建临时数据库。
2. 自动创建父目录。
3. 重复 initialize 不报错。
4. 数据库文件重新打开后数据仍然存在。

Session：

5. 创建指定 session_id。
6. 自动生成 session_id。
7. 默认标题为新会话。
8. 同一用户重复 session_id 失败。
9. 不同用户可以使用相同 session_id。
10. get_session 正常。
11. get_session 不会读取其他用户数据。
12. list_sessions 只返回当前用户。
13. list_sessions 按 updated_at 降序。
14. update_session_title 正常。
15. 更新不存在 Session 失败。
16. touch_session 更新 updated_at。
17. delete_session 正常。
18. 删除不存在 Session 返回 False。
19. 用户 A 不能删除用户 B 的同名 Session。

消息：

20. 添加 user 消息。
21. 添加 assistant 消息。
22. Session 不存在时添加失败。
23. 非法 role 失败。
24. 空内容失败。
25. metadata 保存并恢复。
26. metadata 含中文能够正确恢复。
27. 不可 JSON 序列化 metadata 失败。
28. list_messages 按顺序返回。
29. limit 返回最近 N 条且顺序正确。
30. limit 非法失败。
31. count_messages 正确。
32. clear_messages 返回删除数量。
33. 不同 Session 消息隔离。
34. 不同用户消息隔离。
35. 添加消息会更新 Session.updated_at。

Todo：

36. 第一个 Todo id 为 1。
37. 第二个 Todo id 为 2。
38. 不同 Session 都从 id 1 开始。
39. 不同用户 Todo 隔离。
40. list_todos 按 id 排序。
41. complete_todo 正常。
42. completed_at 被设置。
43. 重复 complete 幂等。
44. 完成不存在 Todo 失败。
45. delete_todo 正常。
46. 删除不存在 Todo 返回 False。
47. 删除后新增 Todo 不复用旧 id。
48. clear_todos 返回删除数量。
49. 添加 Todo 会更新 Session.updated_at。
50. Session 不存在时添加 Todo 失败。

级联删除：

51. 删除 Session 后消息被删除。
52. 删除 Session 后 Todo 被删除。
53. 删除用户 A 的 Session 不影响用户 B 的同名 Session。

校验：

54. 空 user_id 失败。
55. 空 session_id 失败。
56. 空 title 失败。
57. 空 Todo content 失败。
58. bool 类型 todo_id 失败。
59. todo_id 小于等于 0 失败。

十六、测试持久化 TodoTool

新增：

tests/test_persistent_todo.py

至少覆盖：

1. 传入 SQLiteStore 后 add 正常。
2. list 正常。
3. complete 正常。
4. delete 正常。
5. 数据重新创建 TodoTool 后仍存在。
6. 数据重新创建 SQLiteStore 后仍存在。
7. 不同 Session 隔离。
8. 不同 user 隔离。
9. Session 不存在时 add 返回 success=false。
10. 不存在 todo_id 返回明确失败。
11. create_default_registry(todo_store=store) 使用持久化 Todo。
12. create_default_registry() 仍然使用原有内存 Todo。
13. calculator 不受 todo_store 影响。
14. search 不受 todo_store 影响。
15. 现有 tests/test_tools.py 全部继续通过。

十七、安全与兼容要求

1. 所有 SQL 使用参数绑定，不拼接用户输入。
2. 不使用 eval 或 exec。
3. 不增加第三方依赖。
4. 不修改 LLM Client。
5. 不修改 Agent Runtime。
6. 不修改 parser。
7. 不修改健康检查接口。
8. 不创建或提交真实 data/agent.db。
9. .gitignore 中继续忽略：

data/*.db
data/*.db-shm
data/*.db-wal

10. 保证现有全部测试继续通过。

十八、文档

更新 README，增加：

1. SQLite 持久化说明。
2. 数据库默认位置 data/agent.db。
3. Session 使用 user_id + session_id 联合隔离。
4. 消息和 Todo 都归属于 Session。
5. 删除 Session 会级联删除消息与 Todo。
6. 当前尚未接入网页与 Runtime 自动历史恢复。
7. 下一步会把 Runtime 接入持久化历史。

将本阶段完整提示词追加到：

docs/AI_PROMPTS.md

在 docs/PROBLEM_SOLVING.md 记录：

1. 为什么使用 SQLite 而不是内存字典。
2. 为什么 Session 使用 user_id + session_id 联合主键。
3. 为什么消息不允许自动创建 Session。
4. 为什么 Todo id 要在 Session 内独立递增。
5. 如何避免多个 Todo 并发生成相同 id。
6. 为什么数据库连接采用短生命周期。
7. 为什么 default registry 保持内存模式兼容。
8. 如何保证用户和 Session 数据隔离。
9. 为什么使用外键级联删除。
10. 为什么测试使用 tmp_path。

十九、完成后

1. 运行完整测试：

python -m pytest -q

2. 单独运行：

python -m pytest tests/test_memory_store.py tests/test_persistent_todo.py -q

3. 修复全部失败。
4. 列出创建和修改的文件。
5. 说明数据库表设计。
6. 说明 user_id + session_id 隔离如何实现。
7. 给出 CMD 下的手动持久化测试命令。
8. 不运行真实 LLM API。
9. 不执行 git commit。
10. 不执行 git push。
```

## 2026-07-13: Stage 05B — Session 历史接入 Agent Runtime

```text
当前项目已经完成并提交：

stage-01：FastAPI 项目骨架
stage-02：工具注册机制、calculator、search、todo
stage-03：真实 LLM Client、结构化输出解析器、Prompt
stage-04：自行实现 Agent Runtime Loop
stage-05a：SQLite Session、消息和 Todo 持久化

当前 SQLiteStore 已经能够保存：

- sessions
- messages
- todos

AgentRuntime.run 已经支持：

run(
    user_input: str,
    context: ToolContext,
    history: list[dict[str, str]] | None = None
)

现在开始第五阶段第二部分：把 SQLite Session 历史接入 Agent Runtime，使不同窗口能够独立续聊。

本阶段不实现：

- FastAPI Chat 路由
- Session HTTP 路由
- 网页多窗口界面
- Context 摘要压缩
- 独立 Trace 数据库表
- 长期用户画像 Memory
- git commit
- git push

项目使用 Python 3.10。

禁止使用 LangChain、LangGraph、OpenAI Agents SDK、OpenHands、OpenClaw 或其他 Agent 框架。

一、总体设计

不要让 AgentRuntime 直接依赖 SQLiteStore。

保持 AgentRuntime 是无状态的核心循环，并新增一个 Session 服务层负责：

1. 验证 user_id 和 session_id。
2. 检查 Session 是否存在。
3. 从 SQLite 加载当前 Session 历史。
4. 转换为 AgentRuntime 所需的 history。
5. 创建正确的 ToolContext。
6. 调用 AgentRuntime.run。
7. 成功后将当前 user 消息和最终 assistant 回答写入 SQLite。
8. 返回本次运行结果和持久化消息。

这样保持职责分离：

SQLiteStore：
负责数据读写。

AgentRuntime：
负责 LLM 与工具循环。

SessionAgentService：
负责把 Session、历史消息和 Runtime 连接起来。

二、原子保存一轮对话

在 app/memory/store.py 中新增：

add_exchange(
    user_id: str,
    session_id: str,
    user_content: str,
    assistant_content: str,
    assistant_metadata: dict[str, Any] | None = None
) -> tuple[MessageRecord, MessageRecord]

要求：

1. Session 必须存在。
2. user_content 和 assistant_content 都必须是非空字符串。
3. assistant_metadata 必须是可 JSON 序列化的 dict 或 None。
4. 使用同一个 SQLite 事务写入：
   - 一条 role=user 消息
   - 一条 role=assistant 消息
5. 两条消息必须连续写入。
6. 更新一次 Session.updated_at。
7. 任意一步失败时整个事务回滚，不能只留下 user 消息。
8. 返回：
   - user MessageRecord
   - assistant MessageRecord
9. SQL 必须使用参数绑定。
10. 保持已有 add_message 行为和测试不变。
11. 可以提取私有辅助方法减少重复，但不能破坏现有接口。

三、SessionChatResult

新增：

app/agent/session_service.py

实现 SessionChatResult 数据类。

字段至少包含：

- session: SessionRecord
- user_message: MessageRecord
- assistant_message: MessageRecord
- agent_result: AgentRunResult
- loaded_history_count: int

提供：

to_dict() -> dict[str, Any]

to_dict 返回结构应清晰，包括：

{
  "session": {...},
  "user_message": {...},
  "assistant_message": {...},
  "agent_result": {...},
  "loaded_history_count": 2
}

四、SessionAgentService

在 app/agent/session_service.py 中实现：

SessionAgentService(
    runtime: AgentRuntime,
    store: SQLiteStore,
    history_limit: int | None = None
)

要求：

1. runtime 必须是 AgentRuntime。
2. store 必须是 SQLiteStore。
3. history_limit 为 None 时加载当前 Session 的全部历史。
4. history_limit 不为 None 时必须是大于 0 的整数。
5. bool 不能被视为合法整数。
6. 初始化时不调用 LLM。
7. 初始化时不修改数据库。
8. 服务不负责关闭 LLM Client。

五、chat 方法

实现：

chat(
    user_id: str,
    session_id: str,
    user_input: str
) -> SessionChatResult

执行顺序必须是：

1. 校验 user_id。
2. 校验 session_id。
3. 校验 user_input。
4. 使用：

store.get_session(user_id, session_id)

获取 Session。

5. Session 不存在时抛出清晰的 SessionNotFoundError，不能自动创建。
6. 在写入当前 user_input 之前，加载已有消息：

store.list_messages(
    user_id,
    session_id,
    limit=history_limit
)

7. 将 MessageRecord 转换为：

[
  {
    "role": message.role,
    "content": message.content
  }
]

8. 只能将 user 和 assistant 消息放入 history。
9. metadata 不进入 LLM Context。
10. 创建：

ToolContext(
    user_id=user_id,
    session_id=session_id
)

11. 调用：

runtime.run(
    user_input=user_input,
    context=tool_context,
    history=history
)

12. Runtime 成功返回 final 后，使用 add_exchange 原子保存：
    - 当前 user_input
    - agent_result.answer

13. Runtime 发生异常时：
    - 不保存当前 user 消息
    - 不保存 assistant 消息
    - 原有历史不变
    - 将原异常继续抛出，不要伪装成成功

14. 保存 assistant 消息时，将以下紧凑信息放入 metadata：

{
  "agent": {
    "total_llm_calls": 2,
    "total_tool_calls": 1,
    "stopped_reason": "final",
    "used_tools": ["calculator"],
    "reasoning_summaries": [
      "需要调用计算器。",
      "已有计算结果，可以回答。"
    ]
  }
}

要求：

- used_tools 按第一次出现顺序保存
- 相同工具不要重复
- 只保存 reasoning_summary
- 不保存完整内部思维链
- 不保存 API Key
- 不保存 Authorization 请求头
- 不保存完整 system Prompt
- 不保存完整 Runtime messages
- 不保存原始 LLM HTTP 响应

15. 返回 SessionChatResult。
16. 返回的 session 应反映保存消息后的最新 updated_at，可以保存后重新读取。
17. 不修改 AgentRuntime 返回对象中的 messages。
18. 不修改数据库中以前的消息。

六、读取历史方法

在 SessionAgentService 中实现：

get_history(
    user_id: str,
    session_id: str,
    limit: int | None = None
) -> list[MessageRecord]

规则：

1. Session 必须存在。
2. limit 规则与 SQLiteStore.list_messages 一致。
3. 只返回当前 user_id + session_id 的消息。
4. 按旧到新返回。
5. 不允许读取其他用户相同 session_id 的内容。

七、清空对话方法

实现：

clear_history(
    user_id: str,
    session_id: str
) -> int

规则：

1. Session 必须存在。
2. 只清除 messages。
3. 不删除 Session。
4. 不清除 Todo。
5. 返回删除的消息数量。
6. 不能影响其他用户或其他 Session。

八、Context 策略

必须遵守：

持久化并召回到下一轮 Context：

- user 的自然语言输入
- assistant 的最终自然语言回答

不召回到下一轮 Context：

- system Prompt
- 历史原始 tool_call JSON
- 历史工具结果消息
- 完整 Runtime messages
- reasoning_summary
- assistant metadata

本次 Runtime 内部仍然可以使用工具结果继续 Loop。

但 Runtime 结束后，下一轮只加载自然语言 user/assistant 历史。

原因：

1. 避免 Context 快速膨胀。
2. 避免旧工具结果影响新的工具决策。
3. 避免反复发送 Tool Schema 和 system Prompt。
4. 用户真正需要续聊的是自然语言对话状态。
5. Trace 信息应和对话 Context 分离。

九、Session 隔离

必须严格使用：

user_id + session_id

读取和保存历史。

以下情况必须完全隔离：

1. 同一用户的 window-1 和 window-2。
2. 不同用户使用相同 session_id。
3. Todo 工具也必须收到当前 Session 对应的 ToolContext。

不能只使用 session_id 查询数据库。

十、模块导出

更新 app/agent/__init__.py，导出：

- SessionAgentService
- SessionChatResult

保留已有所有导出。

十一、测试

新增：

tests/test_session_agent_service.py

测试中不能调用真实网络，也不能依赖真实 .env。

使用：

- tmp_path 创建 SQLite 数据库
- FakeLLMClient 或现有测试辅助
- 真实 AgentRuntime
- create_default_registry(todo_store=store)

至少覆盖以下内容。

初始化和校验：

1. 正常初始化。
2. runtime 类型错误失败。
3. store 类型错误失败。
4. history_limit=None 正常。
5. history_limit 为正整数正常。
6. history_limit=0 失败。
7. history_limit 为负数失败。
8. history_limit=True 失败。
9. user_id 为空失败。
10. session_id 为空失败。
11. user_input 为空失败。
12. Session 不存在时失败。
13. Session 不存在时不能自动创建。

第一次对话：

14. 第一次对话加载 0 条历史。
15. Fake LLM 第一次收到 system 和当前 user 消息。
16. 成功后数据库新增两条消息。
17. 第一条消息 role=user。
18. 第二条消息 role=assistant。
19. user 内容正确。
20. assistant 内容正确。
21. loaded_history_count 等于 0。
22. assistant metadata 保存调用次数。
23. assistant metadata 保存工具次数。
24. assistant metadata 不包含 system Prompt。
25. assistant metadata 不包含 API Key。
26. assistant metadata 不包含完整 Runtime messages。

纯对话追问：

27. 完成第一轮后进行第二轮。
28. 第二轮 loaded_history_count 等于 2。
29. 第二次 LLM 收到以前的 user 消息。
30. 第二次 LLM 收到以前的 assistant 消息。
31. 当前 user_input 位于历史之后。
32. system Prompt 只出现一次。
33. 第二轮结束后数据库共有四条消息。
34. 消息顺序为：
    - user
    - assistant
    - user
    - assistant

带工具追问：

35. 第一轮 calculator tool_call 后返回 final。
36. 数据库只保存当前 user 和最终 assistant。
37. calculator tool_call JSON 不作为单独消息持久化。
38. calculator 工具结果消息不作为单独消息持久化。
39. assistant metadata 中 used_tools 包含 calculator。
40. 下一轮历史不包含原始 tool_call JSON。
41. 下一轮历史不包含工具结果消息。
42. 下一轮仍能根据 assistant 最终回答进行自然语言追问。

Todo 与 Session Context：

43. window-1 添加 Todo。
44. window-2 添加不同 Todo。
45. window-1 list 只返回 window-1 的 Todo。
46. window-2 list 只返回 window-2 的 Todo。
47. ToolContext 使用正确 user_id。
48. ToolContext 使用正确 session_id。

窗口隔离：

49. 同一用户两个 Session 的历史互不影响。
50. window-1 的第二轮不包含 window-2 消息。
51. window-2 的第二轮不包含 window-1 消息。
52. clear_history(window-1) 不影响 window-2。
53. clear_history 不删除 Todo。

用户隔离：

54. 用户 A 和用户 B 使用相同 session_id。
55. 用户 A 无法读取用户 B 的历史。
56. 用户 B 无法读取用户 A 的历史。
57. 用户 A 的对话不会进入用户 B 的 LLM Context。

进程重建与持久化：

58. 创建 service-1 完成第一轮。
59. 重新创建 SQLiteStore。
60. 重新创建 AgentRuntime。
61. 重新创建 SessionAgentService。
62. service-2 能加载 service-1 保存的历史。
63. 历史顺序正确。
64. Todo 数据仍存在。

history_limit：

65. 创建多轮历史。
66. history_limit=2 时只加载最近两条。
67. 最近两条仍按旧到新传给 Runtime。
68. history_limit 不影响数据库中实际保存的消息数量。

错误与原子性：

69. Runtime 抛出 AgentLLMError 时不新增消息。
70. Runtime 抛出 AgentDecisionError 时不新增消息。
71. Runtime 抛出 AgentMaxStepsError 时不新增消息。
72. add_exchange 中 assistant 插入失败时 user 插入也回滚。
73. 成功的一轮总是新增恰好两条消息。
74. add_exchange 返回连续的消息记录。
75. add_exchange 更新 Session.updated_at。

结果：

76. SessionChatResult.to_dict 正确。
77. 返回的 session.updated_at 是最新值。
78. 返回的 user_message 正确。
79. 返回的 assistant_message 正确。
80. 返回的 agent_result 正确。
81. get_history 正常。
82. clear_history 返回正确数量。

要求：

1. 所有测试相互隔离。
2. 不依赖执行顺序。
3. 不调用真实 LLM API。
4. 不污染 data/agent.db。
5. 保留现有全部测试。
6. 修复全部失败。

十二、真实 Session 演示脚本

新增：

scripts/session_memory_demo.py

运行方式：

python -m scripts.session_memory_demo

使用真实 LLM API和独立演示数据库：

data/session-demo.db

脚本流程：

1. 启动时只清理 session-demo.db、session-demo.db-shm、session-demo.db-wal。
2. 不能删除 data/agent.db。
3. 从 .env 加载真实 LLM 配置。
4. 创建 SQLiteStore("data/session-demo.db")。
5. 创建两个 Session：

用户：

demo-user

窗口一：

session_id="weather-window"
title="天气窗口"

窗口二：

session_id="report-window"
title="周报窗口"

6. 创建：

create_default_registry(todo_store=store)

7. 创建 AgentRuntime。
8. 创建 SessionAgentService。

窗口一第一轮：

请使用 search 查询东京天气，并把“出门带伞”添加到当前会话的待办中。

窗口二第一轮：

请把“周五前完成周报”添加到当前会话的待办中。

9. 重新创建：
   - SQLiteStore
   - ToolRegistry
   - AgentRuntime
   - SessionAgentService

模拟程序重新启动。

10. 窗口一追问：

请列出当前窗口的待办，并告诉我刚才查询的是哪个城市。

11. 窗口二追问：

请列出当前窗口的待办。

12. 打印：

- 每个窗口每一轮的最终 answer
- loaded_history_count
- LLM calls
- Tool calls
- 当前窗口保存的消息
- 当前窗口保存的 Todo

13. 最后明确打印窗口隔离验证：

weather-window 中应包含“出门带伞”
report-window 中应包含“周五前完成周报”

14. 不打印 API Key。
15. 不打印 Authorization 请求头。
16. 错误时清晰退出并返回非零状态。
17. 正确关闭 LLM Client。
18. 脚本运行结束后可以保留 session-demo.db，方便人工查看，但它必须被 .gitignore 忽略。

十三、README

更新 README，增加：

1. SessionAgentService 的职责。
2. Runtime 与 SQLiteStore 为什么解耦。
3. Session 对话流程：

用户输入
  ↓
根据 user_id + session_id 加载历史
  ↓
转换为 user/assistant messages
  ↓
AgentRuntime Loop
  ↓
得到 final
  ↓
原子保存 user + assistant

4. Context 中保存和召回哪些内容。
5. 为什么不把历史工具结果反复放入 Context。
6. 如何运行：

python -m scripts.session_memory_demo

7. 当前已经支持：
   - 纯对话追问
   - 带工具追问
   - 多 Session 隔离
   - 多用户隔离
   - 程序重启后继续聊
   - Todo 持久化

8. 当前尚未实现：
   - Context 摘要压缩
   - HTTP Chat API
   - 网页多窗口界面
   - 独立 Trace 持久化

十四、开发文档

把本阶段完整提示词追加到：

docs/AI_PROMPTS.md

在 docs/PROBLEM_SOLVING.md 记录：

1. 为什么增加 SessionAgentService。
2. 为什么不让 AgentRuntime 直接操作 SQLite。
3. history 在什么时候召回。
4. user 消息为什么不能在 Runtime 成功前提前保存。
5. 为什么一轮对话需要原子保存。
6. 哪些信息进入下一轮 Context。
7. 哪些信息只放 metadata 或 Trace。
8. 为什么不召回历史工具结果。
9. 如何实现用户和窗口隔离。
10. 如何支持纯对话追问。
11. 如何支持带工具追问。
12. 如何模拟程序重启后继续对话。
13. history_limit 的作用。
14. 下一阶段如何加入 Context 压缩。

十五、限制

1. 不实现 FastAPI 路由。
2. 不实现网页。
3. 不实现摘要压缩。
4. 不实现独立 Trace 表。
5. 不修改现有 Agent Runtime 的公开行为。
6. 不修改已有工具 Schema。
7. 不使用 Agent 框架。
8. 不自动执行 git commit。
9. 不自动执行 git push。

十六、完成后

1. 运行完整测试。
2. 单独运行 Session 服务测试。
3. 修复全部失败。
4. 列出创建和修改文件。
5. 说明一轮 Session 对话如何执行。
6. 说明数据库保存哪些信息。
7. 说明下一轮 Context 召回哪些信息。
8. 给出真实 Session Demo 命令。
9. 不执行 git commit。
10. 不执行 git push。
```
