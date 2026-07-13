# 终端与网页操作录屏脚本

建议总时长：6～10 分钟。录制前完成 [提交清单](SUBMISSION_CHECKLIST.md) 中的密钥检查，关闭包含 `.env`、API Key、Authorization 或敏感终端历史的窗口。Search 是本地 Mock，演示时必须明确说明。

## 录制前准备

1. 配置真实 OpenAI-Compatible LLM，并预先运行一次 `python -m scripts.llm_smoke_test`。
2. 确认 `python -m pytest -q`、两个审计脚本已通过。
3. 为录屏准备干净的演示数据库；不要展示或编辑 `.env`。
4. 打开 README、GitHub 仓库页和浏览器 `http://127.0.0.1:8000/`。

## 第一部分：项目介绍（约 30 秒）

画面：README 顶部和题目要求对照表。

口播：

> 这是 Minimal Agent Runtime。项目不使用现有 Agent 框架，从零实现 LLM JSON 决策、Tool Schema、自研多步 Runtime、SQLite Session Memory、Context 压缩和 Trace。后端连接真实 OpenAI-Compatible API，前端支持多个 Session 窗口。

## 第二部分：启动服务（约 30 秒）

终端输入：

```bash
cd ~/Desktop/minimal-agent-runtime
source .venv/bin/activate
python -m uvicorn app.main:app --reload
```

浏览器打开 `http://127.0.0.1:8000/`，短暂展示服务状态。不要展示 `.env`，不要输入会展开密钥的命令，不要打开包含密钥的终端历史。

## 第三部分：创建两个窗口（约 1 分钟）

1. 使用演示标识 `demo-user`。
2. 创建 `weather-window`，标题可设为“东京天气”。
3. 创建 `report-window`，标题可设为“周报”。
4. 在侧栏切换两次，说明 Session 由 `user_id + session_id` 隔离。

## 第四部分：多工具调用（约 1～2 分钟）

在 `weather-window` 输入：

```text
请查询东京天气，并把“出门带伞”添加到当前会话的待办中。
```

展示：

- assistant 最终回答；
- 消息下方 LLM 调用次数、工具调用次数；
- Todo Inspector 出现“出门带伞”；
- 最新 Trace 依次包含 `llm_decision`、search/todo 的 `tool_call` 与 `tool_result`、`final`、`run_completed`；
- search 结果的 `source` 为 `mock`，说明不代表实时天气。

## 第五部分：Session 隔离（约 1 分钟）

切换到 `report-window` 输入：

```text
请把“周五前完成周报”添加到当前会话的待办中。
```

在两个窗口之间切换，依次展示：

- 消息互不出现；
- weather 只有“出门带伞”，report 只有“周五前完成周报”；
- Trace 列表也只显示当前 Session 的 Runs。

## 第六部分：追问与历史恢复（约 1 分钟）

回到 `weather-window` 输入：

```text
刚才查询的是哪个城市？当前有哪些待办？
```

展示模型根据历史回答“东京”和 Todo。随后刷新浏览器；时间允许时停止并重新启动 Uvicorn。重新选择该窗口，展示消息与 Todo 仍存在，说明状态来自 SQLite 而非前端内存。

## 第七部分：计算器与 Runtime Loop（约 1 分钟）

创建 `calculator-window`，输入：

```text
请计算 12 * (3 + 2)。
```

打开最新 Trace，展示：

```text
llm_decision(tool_call)
→ calculator tool_call
→ calculator tool_result(result=60)
→ llm_decision(final)
→ run_completed
```

说明 calculator 使用 AST 白名单，不使用 `eval`。

## 第八部分：Context 压缩与测试（约 1 分钟）

二选一或都展示：

```bash
python -m scripts.context_compression_demo
python -m scripts.final_acceptance
```

重点停留在：

```text
context compressed: True
Database contains Context summary: False
Overall: PASS
```

如果录制环境不适合再次消耗真实 API，可预先运行并展示完整、未编辑的本次终端结果；同时展示离线命令：

```bash
python -m pytest -q
python -m scripts.repository_audit
python -m scripts.documentation_audit
```

## 第九部分：总结（约 30 秒）

依次展示：

- GitHub 仓库；
- README 的架构与启动说明；
- `tests/`；
- `docs/AI_PROMPTS.md`；
- `docs/PROBLEM_SOLVING.md`；
- `docs/FINAL_PROJECT_REPORT.md`。

结尾明确说明：

> Search 使用本地 Mock 数据；user id 是演示隔离标识而非正式鉴权；这是展示核心机制的最小可用 Agent，不是生产级 Agent 平台。

## 录屏验收

- 画面和声音可辨认，总时长 6～10 分钟；
- 终端和网页都完成真实操作，不只展示静态文档；
- 至少展示多工具、两个 Session、追问、持久化、Trace 和测试结果；
- 全程不出现 `.env` 内容、API Key、Authorization 或个人敏感信息；
- GitHub 链接和最终提交对应同一份代码。
