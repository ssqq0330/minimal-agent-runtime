# 问题解决记录

本文件统一使用“现象、原因、解决过程、最终方案、验证方式”格式。环境与迁移类事项来自项目 Stage 11 交接清单；仓库未保留其完整终端日志，因此这里只记录已确认的问题类别和最终处理方式，不虚构具体错误堆栈、机器信息或凭据。

## pydantic-core 缺失

现象：
安装 FastAPI/Pydantic 依赖后，运行或导入时提示 `pydantic-core` 不可用，项目无法启动。

原因：
原环境的 Python/平台与已下载的二进制包不匹配，或安装过程未完整完成。`pydantic-core` 包含平台相关构建产物，不能把另一套系统中的虚拟环境直接当作可移植目录。

解决过程：
不在损坏环境中手工复制单个包；确认 Python 版本后删除并重建虚拟环境，再从 `requirements.txt` 安装，让 pip 选择当前系统兼容的 wheel。仓库没有固定或提交任何本机 wheel。

最终方案：
使用 Python 3.11 新建本机 `.venv`，执行 `python -m pip install -r requirements.txt`；代码保持 Python 3.10 兼容。

验证方式：
运行 `python -c "import pydantic_core, fastapi"`，随后运行 `python -m pytest -q` 和 Uvicorn 健康检查。

## pytest 临时目录权限

现象：
测试在创建 `tmp_path` 或临时 SQLite 文件时出现权限失败，业务断言尚未执行测试就中止。

原因：
pytest 选择的系统临时目录不可写，或迁移后的目录继承了不合适的所有者/权限。这是测试运行环境问题，不是 Store SQL 逻辑失败。

解决过程：
确认项目目录与系统临时目录可写；在受限环境中将临时根指向当前用户可写目录。测试继续使用 pytest `tmp_path`，不改成写入 `data/agent.db`，避免污染真实数据。

最终方案：
为测试提供可写临时目录并保持每个测试独立数据库；不在仓库提交临时数据库。

验证方式：
运行 `python -m pytest -q`，确认所有 `tmp_path`、SQLite 集成和并发用例通过，且 `data/` 没有新增被跟踪数据库。

## Python 3.9 到 3.11

现象：
旧环境使用 Python 3.9，而阶段需求和依赖安装以较新的 Python 为目标，类型标注和依赖 wheel 兼容性不一致。

原因：
Python 解释器属于虚拟环境的一部分，升级代码目录不会自动升级解释器；不同依赖版本对 Python ABI 的支持范围也不同。

解决过程：
用 Python 3.11 创建全新环境，不在原 3.9 环境上覆盖安装。代码中继续使用 `typing.Optional/List/Dict` 等兼容写法，避免无必要地把运行下限提高到 3.11。

最终方案：
README 推荐 Python 3.11，声明实现保持 Python 3.10 兼容，不支持继续复用 Python 3.9 虚拟环境。

验证方式：
在 3.11 环境运行完整测试、两个审计脚本和服务启动；检查源代码未引入只为 3.11 才存在且无替代的核心语法。

## Windows 到 Mac 虚拟环境迁移

现象：
从 Windows 拷贝到 Mac 后，原 `.venv` 的激活脚本、解释器路径和二进制依赖不能工作。

原因：
虚拟环境包含操作系统路径、启动脚本和平台相关二进制，不是跨平台发布物。Windows 的 `Scripts` 与 Mac/Linux 的 `bin` 布局也不同。

解决过程：
只迁移 Git 跟踪的源代码和文档，保持 `.venv` 在 `.gitignore` 中；在 Mac 使用本机 Python 重建环境，并从 requirements 安装。

最终方案：
任何平台都执行“clone → 创建本机 `.venv` → 安装 requirements”，README 分别给出 Mac/Linux 与 Windows CMD 命令。

验证方式：
运行 `git check-ignore .venv/audit-placeholder`、仓库审计和全量测试；确认 Git 跟踪列表不含虚拟环境文件。

## GitHub HTTPS 密码认证失败

现象：
使用 GitHub 账户密码进行 HTTPS push 时认证失败。

原因：
GitHub 的 Git HTTPS 操作不接受账户密码作为远端认证方式，应使用 Personal Access Token、SSH key 或已登录的凭据管理器。

解决过程：
停止重复输入账户密码；改用受支持的 Token/SSH/credential manager，并确保 Token 不写入 remote URL、README、终端录屏或仓库文件。

最终方案：
项目文档只保留无凭据的公开仓库 URL；提交与 push 由维护者在本机已配置凭据的环境中人工执行。

验证方式：
使用 `git remote -v` 检查 URL 不含凭据，运行 repository audit 检查明显密钥；本阶段明确不自动 commit 或 push。

## LLM JSON 输出解析

现象：
兼容模型可能返回纯 JSON、Markdown 代码块、JSON 前后说明文字，或字段结构不符合 `final/tool_call` 协议。

原因：
Prompt 只能约束概率模型，不能保证字节级输出稳定；简单正则也无法可靠处理嵌套对象、转义字符串和字符串内大括号。

解决过程：
使用 `json.JSONDecoder.raw_decode()` 扫描第一个可解码对象，再逐字段验证 type、answer、reasoning_summary、tool_calls、唯一 id 与互斥关系。错误信息不回显完整模型输出。

最终方案：
Parser 接受常见包装但不放宽业务协议；真实验收仅对 malformed decision 做有限重试，Runtime 不猜测无效字段。

验证方式：
`tests/test_agent_parser.py` 覆盖纯 JSON、fence、嵌套、无效字段和重复 id；`llm_smoke_test` 与 `final_acceptance` 验证真实 Provider。

## 工具参数安全

现象：
模型可能生成缺字段、错误类型、越界数字或额外参数；工具内部异常也不应使整个进程暴露堆栈。

原因：
LLM 输出是不可信输入，只在 Parser 验证 arguments 是对象并不足以保证每个工具的业务约束。

解决过程：
`BaseTool.validate_arguments()` 实现 required、类型、enum、minimum/maximum 与 `additionalProperties=false`。各工具再做内容和动作相关校验，Registry 捕获未预期异常并清洗消息。

最终方案：
形成 Parser 结构校验 → BaseTool Schema 校验 → 工具业务校验 → Registry 异常边界的分层防护。

验证方式：
`tests/test_tools.py` 与 `tests/test_error_hardening.py` 覆盖无效参数、未知工具、内部异常与敏感字符串过滤。

## calculator 禁止 eval

现象：
直接对模型提供的表达式使用 `eval` 会允许函数调用、属性访问、导入或任意代码执行。

原因：
计算表达式来自不可信用户/LLM，字符串过滤无法完整限制 Python 语法。

解决过程：
使用 `ast.parse(..., mode="eval")`，只递归解释数字常量、允许的二元/一元运算；拒绝 Name、Call、Attribute、Subscript 等节点，并限制长度、指数和有限结果。

最终方案：
Calculator 只执行 AST 白名单语义，完全不调用 `eval` 或 `exec`。

验证方式：
测试正常括号运算、除零、import、函数、变量、过长表达式、过大指数、额外参数；仓库搜索确认 calculator 不含动态执行调用。

## Session 隔离

现象：
同一用户多窗口或不同用户使用相同 `session_id` 时，若只按 session id 查询，会出现消息、Todo 或 Trace 串线。

原因：
`session_id` 只要求在一个用户范围内唯一，不能作为全局所有权标识。

解决过程：
数据库以 `(user_id, session_id)` 为联合主/外键，所有 Store/Tool/API 调用都携带两个字段；Trace 详情额外检查 user ownership，前端响应也检查 user/session 快照。

最终方案：
Session、Message、Todo、Trace 与 Session Lock 共用同一二元隔离边界。

验证方式：
Memory、API、端到端和多用户测试让不同用户使用相同 session id，分别验证读、写、删和级联边界。

## Todo 持久化

现象：
早期 Todo 使用内存字典，进程重启后丢失；并发新增还可能分配重复或复用 id。

原因：
内存状态不满足 Session 恢复，简单“最大 id + 1”在并发和删除后也不稳定。

解决过程：
SQLite 增加 todos 与 todo_counters；在 `BEGIN IMMEDIATE` 事务和 Store `RLock` 下分配 Session 内递增 id。TodoTool 允许注入 Store，同时保留默认内存模式用于独立测试。

最终方案：
生产服务的默认 Registry 注入 SQLite Store；Todo 按二元 Session 范围持久化且不隐式创建 Session。

验证方式：
`tests/test_persistent_todo.py`、并发测试、Session demo 和最终验收检查隔离、重启恢复与 id 唯一性。

## Context 过长与压缩

现象：
长期 Session 若把全部消息持续发送给 LLM，请求大小、延迟和成本不断增加，最终可能超过 Provider Context 窗口。

原因：
数据库留存需求和单次模型输入需求不同；缺少召回窗口与压缩层会把两者错误绑定。

解决过程：
先应用 `history_limit`，再由 `BasicContextManager` 依据 `max_messages/max_chars` 压缩；较早消息形成规则摘要，最近消息尽量保留。只复制 role/content，摘要不写回数据库。

最终方案：
SQLite 保存完整自然语言历史，Context 每轮按字符近似预算重建，Trace 和 metadata 永不参与召回。

验证方式：
Context 单元/集成测试检查阈值、顺序、预算和不落库；`context_compression_demo` 与最终验收打印 compressed 状态。

## Trace 安全过滤与 Context 分离

现象：
Trace 需要足够信息定位工具与模型行为，但原始请求、响应、系统 Prompt、Token 或长 payload 不应持久化或重新送给模型。

原因：
可观测性和对话连续性用途不同；把 Trace 当 Memory 会扩大敏感面并让历史工具事件影响新决策。

解决过程：
Trace 只记录应用级事件、短 reasoning summary、工具参数/清洗结果和统计。递归过滤敏感 key、Bearer 与过长字符串；Context Manager 只接收 Message role/content。

最终方案：
Trace 存在独立表和 Recorder 路径，绝不参与 Session 历史召回；API 按 user 校验详情与删除。

验证方式：
Trace、安全、Session-Trace 集成和 API 测试检查序列、过滤、所有权、失败终态与不进入 Context。

## 同一 Session 并发 Chat

现象：
两个并发请求可能同时读取相同旧历史，然后以不可预测顺序调用 LLM 和保存，使第二轮看不到第一轮结果。

原因：
SQLite 单条事务只能保证写入原子性，不能自动串行化“读取历史 → LLM → 工具 → 写入”整段跨资源流程。

解决过程：
`SessionLockManager` 以 `(user_id, session_id)` 建立引用计数 `RLock`，`SessionAgentService.chat()` 在完整有状态流程外持锁；异常路径在 finally 中释放并清理闲置 entry。

最终方案：
单 Python 进程内，同 Session 串行，不同 Session/用户并行。多 Worker 分布式锁明确列为未实现。

验证方式：
`tests/test_concurrency.py` 使用 Event/Barrier 验证顺序、不同 scope 并行、异常释放和 lock entry 清理。

## 前端 XSS 安全渲染

现象：
用户输入、模型回答、Todo 与 Trace payload 都可能包含 `<script>`、事件属性或恶意 HTML。

原因：
动态内容若通过 `innerHTML` 或字符串模板插入，会被浏览器解释为可执行结构。

解决过程：
前端以 `createElement`、`createTextNode` 和 `textContent` 构建 DOM；轻量 Markdown 只解释加粗、行内代码、列表和换行，不解析 raw HTML 或链接。

最终方案：
所有后端动态内容走安全文本渲染，禁止 `innerHTML`、`eval`、`new Function` 和内联事件。

验证方式：
Web hardening、Inspector 与 UI 测试扫描危险 API 并验证恶意文本保持文本；人工清单要求在浏览器输入 XSS 样例。

## Inspector 请求竞态

现象：
快速切换 Session 或 Trace 时，较慢的旧请求可能晚于新请求返回，覆盖当前 Todo/Trace/消息视图。

原因：
Fetch 响应顺序不保证与发起顺序一致；只依赖当前 UI 选中项而不校验请求快照会发生串线。

解决过程：
历史、Todo、Trace 列表和详情分别使用 AbortController 与递增版本；响应落地前检查 request user、session、run 与当前选中状态。Chat 不强制取消，但同样验证归属和版本。

最终方案：
旧请求能取消则取消，不能取消的响应也因版本/ownership 不匹配而丢弃；Inspector 失败不回滚已成功 Chat。

验证方式：
`tests/test_web_hardening.py` 与 `tests/test_web_inspector.py` 检查取消、版本、归属快照和错误隔离；人工在慢网络下快速切换窗口复核。
