# 测试分层

测试仍由 `scripts/run_verification.py` 统一发现和产生证据 JSON；本表定义其职责分层，避免“全部测试混在一起”而无法解释覆盖范围。

| 分组 | 文件 | 目的 |
|---|---|---|
| Unit | `test_approvals.py`、`test_llm_client.py`、`test_tool_engineering.py`、`test_rag.py` | 状态机、Provider 契约、工具 schema、切块与检索原语 |
| Integration | `test_runtime.py`、`test_llm_setup.py` | Runtime 状态流转和配置/Provider 连接方式 |
| Security | `test_audit.py`、`test_network_policy.py`、`test_routing_security.py`、`test_skill_scanner.py` | 审计脱敏、网络白名单、越权路由和静态扫描 |
| Eval | `tests/fixtures/intent_eval.jsonl`、`eval/rag_cases.jsonl` | 标注数据；由独立 Eval 脚本生成指标，不伪装成单元测试 |

本地命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_verification.py
.\.venv\Scripts\python.exe scripts\run_intent_eval.py
.\.venv\Scripts\python.exe scripts\run_rag_eval.py
```
