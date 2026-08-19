# LLM 交付模式

## 面向最终用户

项目不捆绑大模型，也不共享开发者的云端 Key。首次运行时用户自己选择：

```text
1. Ollama：免费、本地、首次下载约 2.5 GB 模型
2. OpenAI：用户自带 Key
3. Groq：用户自带 Key，受地区限制
4. 火山方舟：国内云 API，用户自带 Key
5. 纯规则：不使用 LLM
```

无论选择哪一种，LLM 都只负责意图解析。系统工具注册表、参数校验、风险策略和 Broker 审批不接受模型授权。

## Ollama 安装策略

`scripts/configure_llm.py` 只检测安装、服务和模型状态。没有获得用户明确确认时不会运行 `ollama pull`。推荐模型为 `qwen3:4b`，官方模型库当前标注约 2.5 GB；模型保存在用户自己的 Ollama 目录，不提交 Git，也不随项目压缩包复制。

管理员或用户可以显式运行：

```powershell
.\.venv\Scripts\python.exe scripts\configure_llm.py --mode ollama
# 确认安装和磁盘空间后，才使用：
.\.venv\Scripts\python.exe scripts\configure_llm.py --mode ollama --pull
```

如果 Ollama 不可用，`scripts/check_llm.py` 会报告本地连接错误；Agent 随后使用规则路由，而不是阻止 CPU、内存、磁盘、网络或 Broker 功能启动。

## 交付包内容

交付包包含 Provider 配置模板、检测脚本、测试和文档，但不包含模型文件、API Key 或第三方安装程序。这样避免模型许可证、安装包更新、压缩包体积和密钥泄露问题。
