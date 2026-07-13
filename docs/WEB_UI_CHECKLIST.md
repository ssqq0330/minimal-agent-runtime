# Web UI 手动验收清单

## 准备

1. 在项目根目录启动服务：

   ```bash
   python -m uvicorn app.main:app --reload
   ```

2. 打开 http://127.0.0.1:8000/，确认状态徽章显示后端、LLM 与数据库状态。
3. 使用 `demo-user`。注意：这里的用户 ID 只是演示隔离标识，不是真实登录鉴权。

## 双 Session 主流程

1. 点击“新建会话”，创建 `weather-window`，标题设为“天气窗口”。
2. 再创建 `report-window`，标题设为“周报窗口”。
3. 在 `weather-window` 发送：`查询东京天气并添加“出门带伞”。`
4. 在 `report-window` 发送：`添加“周五前完成周报”。`
5. 来回切换两个窗口，确认每个窗口只显示自己的用户与助手消息，没有串线。
6. 刷新页面，确认之前选中的窗口恢复，两个窗口的历史仍由后端加载。
7. 将“周报窗口”重命名为“本周周报”，确认侧栏和标题栏同步更新。
8. 删除一个窗口，确认对话框明确提示消息、Todo、Trace 会级联删除，并确认剩余窗口自动选中。

## 异常、安全与响应式

1. 停止后端，等待健康检查或刷新页面，确认出现“服务离线”与友好错误，发送操作不可用；恢复后端再验证状态恢复。
2. 打开窄屏或移动端尺寸，确认 Session 侧栏可收起、聊天区域占满宽度且无严重横向滚动。
3. 在输入框按 Enter，确认发送；按 Shift+Enter，确认只插入换行。
4. 发送 `<img src=x onerror=alert(1)>` 或 `<script>alert(1)</script>`，确认它们只作为文本显示，不执行 HTML 或脚本。
5. 快速点击发送按钮，确认同一消息不会重复提交；发送期间删除按钮不可用。
6. 在一次请求尚未返回时尝试切换 Session，确认响应不会显示到错误窗口。
7. 在服务端未配置 LLM 时发送消息，确认提示为“LLM 尚未配置，请检查服务端 .env。”，且不展示原始异常或堆栈。

## 录屏建议

1. 从空白用户开始，依次展示创建两个 Session。
2. 在天气窗口完成 search + todo 请求，再在周报窗口添加独立 Todo。
3. 快速切换两个 Session，展示消息隔离与助手消息下方的 Agent 统计。
4. 刷新页面，展示选中项和历史恢复。
5. 展示重命名、移动端侧栏收起，最后展示删除确认中的级联说明。

## Inspector、Todo 与 Trace

1. 打开 `weather-window`，切换到 Todo 标签，确认只出现“出门带伞”。
2. 打开 `report-window`，确认 Todo 立即清空再加载，最终只出现“周五前完成周报”。
3. 来回切换两个 Session，确认 Todo、Trace Run 和 Trace 详情都不串线。
4. 发起一次新 Chat，确认 assistant 回答先出现，Inspector 随后自动刷新。
5. 确认概览显示 Run ID、LLM/工具次数、Context 压缩、历史数量、状态和耗时。
6. 打开最新 Trace，确认事件按 sequence 从 `run_started` 到 `run_completed` 排列。
7. 展开 calculator、search 或 todo 的 arguments/output，确认 JSON 可读且工具调用与结果容易对应。
8. 检查 `context_built` 的消息数量、字符数量与压缩指标。
9. 删除选中 Trace，确认消息、Session 和 Todo 保持不变。
10. 发送包含 `**加粗**`、`` `行内代码` `` 和 `- 列表项` 的消息，确认轻量格式正常。
11. 输入 `<script>alert(1)</script>` 和 `<img src=x onerror=alert(1)>`，确认只显示文本且没有执行。
12. 将浏览器调到 1024px，确认 Inspector 默认可折叠、打开时作为右侧覆盖层。
13. 调到 768px 和移动端宽度，分别打开 Session 与 Inspector 抽屉，确认两者可独立关闭。
14. 确认聊天输入区始终可见、页面无横向滚动、Trace JSON 仅在自身区域横向滚动。
15. 检查顶部“应用”按钮始终单行，服务徽章不覆盖用户输入框。

## Inspector 录屏路径

1. 先展示双 Session Todo 隔离。
2. 发起 search + todo 请求，先停留在 assistant 回答，再打开自动选中的最新 Trace。
3. 展开 tool_call 与 tool_result JSON，展示完整事件时间线和概览指标。
4. 删除 Trace 后切回聊天与 Todo，证明业务数据不受影响。
5. 最后缩窄页面，展示 Session 和 Inspector 两个独立抽屉。
