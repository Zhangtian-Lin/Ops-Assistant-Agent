# 配置分层

项目将配置和运行数据分为三层。不要把密钥或本机策略提交到 Git。

| 层级 | 位置 | 是否提交 | 内容 |
|---|---|---|---|
| Example | `config/*.example.yaml` | 是 | 可复制的无密钥模板 |
| Local | `config/*.yaml` | 否 | 当前机器的 LLM、网络、身份与安全模式配置 |
| Runtime | `data/runtime/` | 否 | 审批 SQLite、Broker 就绪文件、审计 outbox、Task trace、HMAC key |

当前代码为兼容启动器，Local 配置保留在 `config/` 根目录，而不是另建目录。创建本机文件时，只能从同名 `.example.yaml` 复制：

```powershell
Copy-Item .\config\llm.example.yaml .\config\llm.yaml
Copy-Item .\config\network_policy.example.yaml .\config\network_policy.yaml
```

密钥只放在环境变量，例如 `OPS_AGENT_LLM_API_KEY`；不要放入 YAML、报告、Issue 或截图。
