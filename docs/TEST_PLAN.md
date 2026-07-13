# Test Plan

## 测试层次

1. 单元测试验证 Parser、Prompt、Context、工具、错误净化和 Session 锁等纯组件。
2. 集成测试使用临时 SQLite，把 Store、Runtime、Context、Trace 与 Session 服务组合起来。
3. API 测试通过 FastAPI `TestClient` 验证状态码、响应 Schema、资源隔离与级联删除。
4. 端到端测试使用真实 ToolRegistry、AgentRuntime、SessionAgentService、TraceRecorder 和 Fake LLM，覆盖多窗口主流程。
5. 手动 UI 测试验证真实浏览器中的布局、键盘、离线恢复、抽屉、XSS 与长内容体验。
6. 真实 LLM 验收使用 `.env` 中的兼容 API，验证模型选择工具、历史召回、压缩、Trace 与重启持久性。
7. 文档测试与 Documentation Audit 验证必需材料、README 命令、Stage 记录、问题格式、API 路由、凭据、个人路径和 Mermaid fence。

## 覆盖范围

- `tests/test_end_to_end.py`：双 Session、工具、追问、压缩、Trace、错误、隔离、SQL 风格文本、XSS 与级联。
- `tests/test_concurrency.py`：锁作用域、异常释放、同 Session 串行、不同作用域并行、Todo ID 与 Trace sequence。
- `tests/test_error_hardening.py`：敏感字段净化、统一 500、Provider HTTP 错误和仓库密钥扫描。
- `tests/test_web_hardening.py`：请求取消、响应归属、输入限制、友好错误、安全 DOM 和 localStorage 边界。
- 现有测试继续覆盖各层细节和回归契约。

Fake LLM 测试完全离线、确定且适合 CI，重点验证应用逻辑；真实 LLM 验收依赖网络、服务商兼容性与模型行为，只用于发布前 smoke test，不能替代确定性测试。

## 运行命令

完整测试：

```bash
python -m pytest -q
```

最终真实验收：

```bash
python -m scripts.final_acceptance
```

仓库检查：

```bash
python -m scripts.repository_audit
```

文档检查：

```bash
python -m scripts.documentation_audit
```

并发测试使用线程事件、Barrier 和有限超时；任何等待都必须在数秒内结束，防止测试死锁。真实网络超时、浏览器视觉细节、不同兼容模型的非确定措辞和操作系统级 SQLite 调度无法稳定地完全自动化，需结合真实验收和 `docs/WEB_UI_CHECKLIST.md`。
