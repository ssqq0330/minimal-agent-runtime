# Known Limitations

1. `user_id` 只是演示隔离标识，不是登录、身份验证或授权系统。
2. Session 锁只在单个 Python 进程内有效；多 Worker 或多主机部署需要分布式协调。
3. Search 工具读取本地 Mock 知识库，不提供实时互联网信息。
4. Context 预算使用字符估算，不是模型专用的精确 Tokenizer。
5. 基础摘要是确定性的规则压缩，不是语义摘要，可能丢失细节。
6. SQLite 适合这个最小可用项目，不适合高并发分布式生产部署。
7. 不同 OpenAI-compatible 服务对 JSON 输出、错误和模型能力的兼容程度不同。
8. 前端只实现安全的轻量 Markdown 子集，不是完整 CommonMark 解析器。
9. 当前 Todo 面板以查看为主，修改操作由 Agent 工具完成。
10. 项目目标是展示一个自行实现的最小可用 Agent Runtime，不是生产级 Agent 平台。

自动测试和仓库检查用于降低已知回归风险，不等同于正式渗透测试、合规审计、容量规划或生产级安全认证。
