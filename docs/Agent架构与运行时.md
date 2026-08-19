# Agent 架构与运行时

## 为什么要有 Runtime

`agent.py` 原先能完成请求，但一次请求的“路由来源、是否被拒绝、工具是否执行、耗时和最终状态”分散在函数调用与临时变量里。`core/runtime.py` 新增的 `AgentRuntime` 为每个请求创建 `TaskState`，将过程变成可追溯状态，而不改变权限逻辑。

```text
created
  → routed
  → policy_evaluating → tool_completed → completed
  └→ policy_rejected → completed
```

工具超时或失败也只会使当前 Task 进入 `failed`，不会让 Agent 进程整体崩溃。

## 职责边界

| 组件 | 负责什么 | 不负责什么 |
|---|---|---|
| `AgentRuntime` | 编排一次请求、持有 TaskState、写入脱敏 trace | 授权或执行任意系统动作 |
| Router | LLM/规则生成候选工具请求 | 最终权限判断 |
| ToolExecutor | schema、参数、权限、风险与超时检查 | 绕过注册表执行命令 |
| Tool | 返回受限的事实结果 | 决定自身是否越权 |
| Broker | 通过 Named Pipe 处理审批与高风险执行 | 信任客户端自报角色 |
| Memory / RAG | 提供历史事实或知识材料 | 授权工具或审批 |

## 证据

`tests/test_runtime.py` 验证：允许请求有完整阶段链；策略拒绝不调用执行器；工具超时只失败当前任务。运行 `scripts/run_verification.py` 后可在 `reports/latest_verification.json` 看到每条输入、预期和实际观察。

生产运行时的本机 trace 在 `data/runtime/task_traces.jsonl`，每行一条 TaskState，包含输入哈希与脱敏预览，不包含 API Key。它用于调试，不应被当作“Windows Event Log 或跨身份安全审计已完成”的证据。
