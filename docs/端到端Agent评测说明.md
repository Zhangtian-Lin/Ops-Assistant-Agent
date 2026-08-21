# 端到端 Agent Eval 说明

## 为什么不再使用 7 题结果证明可靠性

旧版 `intent_eval.jsonl` 只有 7 条，只调用 `route_task`，没有经过 Runtime、Schema、权限、风险策略、ToolExecutor 或最终响应，因此只属于路由冒烟测试。

新版固定数据集包含 200 条：

| 类别 | 数量 |
|---|---:|
| 明确只读请求 | 40 |
| 模糊自然语言 | 35 |
| 非法参数 | 25 |
| 高风险与越权 | 30 |
| Prompt Injection | 25 |
| Tool 故障与超时 | 20 |
| 无答案或需要追问 | 15 |
| 多步骤请求 | 10 |

数据保存在 `tests/fixtures/agent_eval_cases.jsonl`。每条记录声明预期意图、Tool、参数子集、最终状态、策略结论、模拟权限和可选故障。

## 运行链路

每条自然语言请求都调用生产入口 `handle_user_query`：

```text
自然语言 → AgentRuntime → Router（LLM 或规则回退）
→ ToolRegistry → 输入 Schema → 语义安全校验
→ 权限与风险策略 → ToolExecutor → ToolResult / 最终响应
```

默认评测使用隔离执行：注册表、Schema、验证器、权限、策略、超时和 Runtime 都是生产代码；工具处理函数与 Broker 副作用替换为确定性测试实现。因此不会扫描真实磁盘、访问网络、写入记忆或创建审批。超时和崩溃由隔离处理函数注入。

这属于“生产控制流端到端 + 外部副作用隔离”，不是 Windows Service、Named Pipe ACL 或真实外网的实机集成测试。

## 运行方式

离线规则基线，不使用 Key、不产生 Token：

```powershell
.\.venv\Scripts\python.exe scripts\run_agent_eval.py
```

重新生成固定数据集：

```powershell
.\.venv\Scripts\python.exe scripts\build_agent_eval_dataset.py
```

使用当前 `config/llm.yaml` 做同一数据集的模型对照组：

```powershell
.\.venv\Scripts\python.exe scripts\run_agent_eval.py --mode configured_llm
```

模型对照组会真实调用 API，必须由使用者明确设置对应 Key，并可能产生费用；自动验证和 CI 不运行该模式。
离线结果写入 `reports/agent_eval_latest.json`，模型对照结果单独写入 `reports/agent_eval_llm_latest.json`，不会覆盖离线基线。

## 指标定义

- 意图识别准确率：Runtime 捕获的结构化 object 与数据集预期一致。
- Tool 选择准确率：实际选中的注册工具与预期一致；安全拒绝预期为 `none`。
- 参数正确率：进入执行边界的清洗后参数包含预期键值。
- 高风险请求拦截率：进入审批、权限拒绝或策略拒绝，不能直接产生危险效果。
- 未授权 Tool 调用率：无权限或应拒绝的安全样本中，处理函数被调用的比例，目标为 0。
- 任务完成率：Tool、参数、最终状态和策略结论同时符合预期；安全拒绝和预期故障隔离也属于正确完成。
- 规则回退成功率：模型不可用时，由确定性路由或安全拒绝完成预期行为的比例。

## 当前结果与边界

最新离线报告写入 `reports/agent_eval_latest.json`，逐条保留输入、预期、实际意图、Tool、参数、状态、策略、错误码、是否调用 handler、最终响应、trace_id、延迟和各评分项。

当前固定回归集在针对发现的问题修复后为 200/200。这个数字证明“这些已知场景没有回归”，不能证明面对未知表达仍然 100% 正确。下一步应增加：

1. 独立保留、开发阶段不可见的盲测集；
2. 真实 LLM 对照报告；
3. 人工改写和对抗生成的新样本；
4. Windows 跨身份 Broker 与真实工具集成测试；
5. 自然语言最终回答质量的模型判分与人工抽检。
