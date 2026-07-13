# 最终提交清单

checkbox 默认保留未勾选状态，由提交人在发布与录屏现场逐项确认。自动脚本通过不代表 GitHub 可访问、录屏合格或工作区已提交。

## 代码

- [ ] GitHub 仓库可访问
- [ ] main 分支为最新代码
- [ ] 工作区无未提交修改
- [ ] 不包含 `.env`
- [ ] 不包含 `.venv`
- [ ] 不包含数据库文件
- [ ] 不包含真实 API Key
- [ ] 不依赖 Agent 框架

## 功能

- [ ] 真实 LLM API 可调用
- [ ] calculator 正常
- [ ] search 正常并明确为 Mock
- [ ] todo 正常
- [ ] 直接回答正常
- [ ] 单工具调用正常
- [ ] 多工具调用正常
- [ ] 多步 Loop 正常
- [ ] `max_steps` 正常
- [ ] 多 Session 隔离
- [ ] 多用户隔离
- [ ] 历史恢复
- [ ] Context 压缩
- [ ] Trace 日志
- [ ] Web UI

## 测试

- [ ] `python -m pytest -q`
- [ ] `python -m scripts.repository_audit`
- [ ] `python -m scripts.documentation_audit`
- [ ] `python -m scripts.final_acceptance`

## 文档

- [ ] `README.md`
- [ ] `docs/SYSTEM_DESIGN.md`
- [ ] `docs/MEMORY_DESIGN.md`
- [ ] `docs/API_REFERENCE.md`
- [ ] `docs/AI_PROMPTS.md`
- [ ] `docs/PROBLEM_SOLVING.md`
- [ ] `docs/TEST_PLAN.md`
- [ ] `docs/KNOWN_LIMITATIONS.md`
- [ ] `docs/WEB_UI_CHECKLIST.md`
- [ ] `docs/RECORDING_SCRIPT.md`
- [ ] `docs/SUBMISSION_CHECKLIST.md`
- [ ] `docs/FINAL_PROJECT_REPORT.md`

## 录屏

- [ ] 不展示 API Key
- [ ] 展示两个 Session
- [ ] 展示工具调用
- [ ] 展示 Trace
- [ ] 展示持久化
- [ ] 展示 Context 压缩
- [ ] 展示测试结果
- [ ] 展示 GitHub 仓库

## 发布前人工复核

- [ ] README 中的命令已在全新环境验证
- [ ] `.env.example` 只有空值或占位符
- [ ] 真实 LLM 的 base URL、model 与服务商配置匹配
- [ ] 录屏中的 Search 被明确称为 Mock
- [ ] user id 被明确称为演示标识
- [ ] 已检查 `git diff`，没有误改 Runtime 协议
- [ ] 已确认未由自动化脚本执行 commit 或 push
