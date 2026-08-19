# Changelog

本项目遵循语义化版本：`MAJOR.MINOR.PATCH`。发布版本必须通过 CI 验证；未发布的改动先写在 `Unreleased`。

## [Unreleased]

### Added

- 软件工程化：GitHub Actions、发布门槛、配置分层说明、测试分层说明和 Issue 模板。

## [0.4.0] - 2026-08-19

### Added

- 显式 Agent Runtime / TaskState 与请求时序图。
- LLM Provider 调用层、离线 Eval 与安全降级测试。
- Tool Registry / ToolExecutor 统一契约与工程测试。
- RAG Demo 知识库、30 条来源召回基准与 Recall@K 报告。
- Broker 审计 outbox、trace_id 与 Windows Event Log 来源注册脚本。
