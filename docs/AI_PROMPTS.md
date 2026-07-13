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
