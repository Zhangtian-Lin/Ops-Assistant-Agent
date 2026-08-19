# Tool 与 Skill 工程说明

## 目标

Tool 是受控能力，不是允许 LLM 直接调用的普通 Python 函数。规则路由和 LLM 只能产生 `ToolRequest`；注册、参数、权限、风险、超时、执行和结果验证由同一条可信执行链处理。

```text
规则 / LLM
  → ToolRequest（tool、arguments、trace_id）
  → ToolRegistry 查询
  → 输入 Schema
  → 语义安全校验
  → Windows SID 角色权限
  → 风险与审批模式
  → 限时执行
  → 输出 Schema
  → ToolResult
```

## 核心文件

- `core/tools/models.py`：`ToolDefinition`、`ToolRequest`、`ToolResult` 与稳定错误码。
- `core/tools/registry.py`：拒绝重复、缺字段和危险策略组合的注册表。
- `core/tools/catalog.py`：内置工具处理函数、Schema、风险、权限和超时的唯一组合点。
- `core/tools/executor.py`：所有工具共用的执行边界。
- `core/tools/schema.py`：项目所需的严格 JSON Schema 子集。
- `core/skills/lifecycle.py`：Skill 四阶段生命周期。

旧的 `TOOL_FUNCS` 与 `TOOL_POLICIES` 已移除。批准后执行的业务动作仍由 `ACTION_POLICIES` 管理，因为它属于 Broker 安全边界，而不是普通 Tool 元数据。

## 固定错误码

| 错误码 | 含义 |
|---|---|
| `TOOL_UNKNOWN` | 工具未注册 |
| `ARG_SCHEMA_INVALID` | 参数结构、类型或额外字段非法 |
| `ARG_SECURITY_REJECTED` | 路径、服务名、网络目标等语义安全校验失败 |
| `POLICY_DENIED` | 执行模式不被策略允许 |
| `PERMISSION_DENIED` | 当前 OS 身份对应角色缺少权限 |
| `APPROVAL_REQUIRED` | 请求必须进入审批流程 |
| `TOOL_TIMEOUT` | 超过工具声明的时间限制 |
| `TOOL_EXECUTION_FAILED` | 工具异常，内部细节不向模型暴露 |
| `RESULT_SCHEMA_INVALID` | 工具返回值不符合声明 |

## Skill 生命周期

```text
discovered → scanned → confirmed → installed
```

1. `discover` 将本地候选复制到 `data/skills/staging`，拒绝符号链接、超大目录和缺少 `SKILL.md` 的候选。
2. `scan` 调用现有 Security Scanner，并记录内容 SHA-256。
3. `confirm` 只接受绑定随机候选 ID 与摘要前缀的完整确认短语；`BLOCK` 候选不能确认。
4. `install` 再次校验摘要，并原子复制到 `data/skills/installed`。

安装不会自动加载代码，也没有提供给 LLM 的自动确认入口。未来如需把已安装 Skill 注册为 Tool，仍须经过独立的清单验证和 Agent 重启。

## 已知边界

- 通用执行器用守护线程保证调用方按时返回，但 Python 无法安全强杀线程。现有 PowerShell、网络套接字等工具还应保留自身超时；未来高风险外部执行器应使用 Restricted Token 与 Job Object，由 Broker 管理进程生命周期。
- 输出 Schema 当前先保证顶层对象类型；应在后续逐个工具收紧必填字段和数值范围。
- Skill 生命周期当前处理本地候选目录。联网发现和下载仍未开放，未来必须接入网络白名单、来源签名、下载大小限制和用户确认。

## 运行证据测试

```powershell
.\.venv\Scripts\python.exe scripts\run_tool_engineering_tests.py
```

独立证据写入 `reports/tool_engineering_latest.json`。完整回归执行：

```powershell
.\.venv\Scripts\python.exe scripts\run_verification.py
```

报告逐条保存测试输入、预期、实际结果、错误码、策略结论、`trace_id` 和耗时，不保存 Key。
