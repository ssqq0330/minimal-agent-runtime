# Minimal Agent Runtime 最终项目报告

## 1. 项目背景

许多 Agent 框架把模型决策、工具调度和 Memory 隐藏在封装内，Demo 容易运行，却难以回答一轮请求如何结束、历史何时召回、工具错误怎样反馈。本项目从零实现最小 Runtime，用可读代码展示真实 LLM、工具、多轮 Session、Context、Trace、API 和 Web UI 的完整边界。目标是教学与验收，不是复刻生产平台。

## 2. 需求分析

需求分为四类：Agent 需要自主选择直接回答或工具调用，支持多工具和多步循环；状态需要多用户、多 Session、历史恢复和 Todo；运行需要 JSON 校验、最大步数、Context 压缩、异常与并发保护；交付需要真实 API、Trace、网页、测试、Prompt 与问题记录。正式鉴权、实时搜索、向量 Memory 和分布式集群不在范围内。

## 3. 技术选型

FastAPI/Pydantic 提供 HTTP 校验和 OpenAPI；httpx 直接调用 OpenAI-Compatible Chat Completions，不使用 OpenAI SDK 或 Agent 框架；SQLite 以事务和联合键支持单机持久化；原生 ES Modules、HTML、CSS 无需前端构建。pytest、Fake LLM 和 MockTransport 保证离线测试确定，真实模型只用于 Demo 与最终验收。

## 4. 核心架构

FastAPI 的 `ApplicationServices` 是组合根；无 LLM 配置时使用降级服务，使健康检查、页面和数据库接口仍可用。`SessionAgentService` 编排有状态 Chat，`BasicContextManager` 处理历史，`AgentRuntime` 只负责 LLM/工具循环，`SQLiteStore` 和 `SQLiteTraceRecorder` 分别负责业务状态与执行证据。Runtime 不依赖 SQLite，因此易于 Fake 测试和替换存储。

## 5. Agent Runtime 实现

Runtime 组合 system Prompt、Tool Schema、历史和当前输入。模型只能返回 `final` 或 `tool_call` JSON。Parser 用 `JSONDecoder.raw_decode` 兼容纯 JSON、代码块和少量说明，再严格校验字段、互斥关系与调用 id。工具按列表顺序执行，真实结果带 call id 回传；失败结果允许模型修正。默认 `max_steps=8` 防止无限循环。

## 6. Tool Schema 与自主决策

`BaseTool` 统一名称、描述、参数 Schema 和校验，Registry 汇总 Schema 交给 LLM，因此工具选择不是关键词路由。calculator 用 AST 白名单且禁止 `eval`；search 读取本地知识库并标记 `source=mock`；todo 支持增删查改并在生产服务注入 SQLite。参数经过结构、类型、枚举、范围和业务规则多层校验。

## 7. Session 与 Memory

Session、Message、Todo、Trace 都以 `user_id + session_id` 隔离。每次 Chat 先验证并召回当前 Session 的自然语言历史；只有 Runtime 返回 final，当前 user 与 assistant 才由 `add_exchange` 同事务保存，失败不产生半轮消息。历史不召回旧工具 JSON、Trace 或 reasoning。user id 只是演示标识，不是身份认证。

## 8. Context 压缩

SQLite 保留完整对话，但模型请求按 `history_limit` 和 Context 配置控制。历史超过消息数或字符阈值时，较早内容生成确定性摘要，最近消息尽量保留，仍超限则先缩摘要再缩较旧消息。字符估算便于跨 Provider 离线测试，但不等于精确 Token。摘要不写回消息或 metadata，避免递归和事实污染。

## 9. Trace

每轮 Chat 分配 run id。Run 保存状态、范围、边界化输入/答案、统计与时间；Event 以 sequence 保存 Context、LLM 决策、工具调用/结果和终态。Trace 只保留短 `reasoning_summary`，递归过滤敏感 key、Bearer、系统 Prompt、原始响应和长文本。它面向调试和 UI，从不进入下一轮 Context。

## 10. API 与 Web UI

API 覆盖健康检查、Session CRUD、消息、Todo 查询、Chat 和 Trace 查询/删除，错误使用稳定 code/message；LLM 未配置为 503，Provider/决策错误为 502，最大步数为 508。原生 Web UI 支持多 Session、Todo 和 Trace Inspector。请求版本、AbortController 与归属快照避免旧响应串线，动态内容使用文本节点而非 `innerHTML`，降低 XSS 风险。

## 11. 测试策略

测试分为单元、集成、API、端到端、并发、安全和 Web 静态检查。MockTransport 验证 LLM HTTP，Fake LLM 验证 Runtime，临时 SQLite 验证事务、隔离、恢复和 Trace，TestClient 验证 API。Repository Audit 扫描依赖、忽略规则、数据库、CDN 和密钥；Documentation Audit 检查材料、命令、Stage、个人路径与 Mermaid；`final_acceptance` 单独验证真实模型旅程。

## 12. 主要问题及解决方法

迁移阶段记录了 pydantic-core 安装异常、pytest 临时目录权限、Python 3.9 到 3.11、Windows 虚拟环境不能迁到 Mac、GitHub HTTPS 密码认证失败。最终采用本机 Python 3.11 重建 `.venv`、重新安装 requirements、使用可写临时目录和受支持的 Token/SSH；仓库不保存凭据或安装日志。

实现阶段通过 JSONDecoder 与严格协议处理 LLM JSON 波动；通过规则摘要控制 Context；通过联合键隔离 Session；通过进程内 Session 锁串行并发 Chat；通过文本 DOM 和请求版本解决 XSS 与 Inspector 竞态；Trace 与 Context 分离以防调试数据影响模型。细节与验证见 `PROBLEM_SOLVING.md`，无原始日志的环境问题不虚构具体堆栈。

## 13. 项目创新点

项目把框架常隐藏的边界显式化：模型决策是可验证 union，工具结果带稳定 call id，完整数据库历史与请求级 Context 分离，Session Memory 与运行 Trace 分离，真实模型验收与 Fake 回归分离。Web Inspector 又把回答、Context 统计和事件时间线关联起来，使用户能从最终结果追溯 Runtime 行为。

## 14. 已知限制

Search 是 Mock；user id 不是真实鉴权；Session 锁只在单进程有效；Context 使用字符估算与规则摘要；SQLite 不适合分布式高并发；不同 Provider 可能不完全遵循 JSON；Web 仅支持轻量 Markdown，Todo HTTP 面板以读取为主。测试和审计降低回归风险，但不等同于生产安全认证。

## 15. 后续改进

后续可加入认证授权、实时 Search、精确 Token 预算、语义摘要、向量 Memory、工具副作用补偿、跨进程锁、PostgreSQL、流式响应与指标。工具扩展还需要权限、幂等、超时、取消和人工确认；生产部署则需密钥管理、速率限制、容量测试与正式安全评估，同时保持当前 Runtime 协议清晰可测。
