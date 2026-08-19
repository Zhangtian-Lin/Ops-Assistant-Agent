# LLM 工程化调用说明

## 目标

LLM 只做“自然语言 → 受限意图”的辅助解析，不是系统权限主体，也不是工具执行器。没有模型或模型出错时，本地 Agent 仍以规则路由工作。

```text
用户输入
  → 策略覆盖文本预拒绝
  → LLMClient（可选）
  → 严格 JSON Schema + 置信度阈值
  → object / args 白名单
  → Agent 参数校验 + 风险策略
  → 已注册工具或审批 Broker
```

## 配置与隐私

首次运行统一启动器时，如果尚无 `config/llm.yaml`，会调用 `scripts/configure_llm.py` 选择本地 Ollama、OpenAI、Groq 或纯规则模式。本机配置文件被 Git 忽略。

推荐交付模式是 Ollama：只允许连接本机 `127.0.0.1/localhost:11434`，不需要 API Key；示例模型 `qwen3:4b` 约 2.5 GB，只有用户明确输入 `y` 才会下载。云端模式的密钥只从 `api_key_env` 指定的环境变量读取。

云端实现使用 OpenAI-compatible Chat Completions 与严格 `json_schema`；Ollama 使用其兼容接口的 JSON Object 模式，结果仍接受同一套本地字段过滤和参数校验。当前未在项目中写死任何供应商 Key。[Ollama OpenAI 兼容说明](https://docs.ollama.com/api/openai-compatibility)

## 运行保护

- `timeout_seconds`：单次 HTTP 调用的超时上限。
- `max_retries`：仅有限重试，并以短暂指数退避避免阻塞交互。
- `max_output_tokens`：限制意图输出开销。
- 输出必须满足 schema；低于 0.60 的 `confidence`、HTTP/超时和无效 JSON 均走规则回退。
- 调用结果仅返回耗时、次数、模型名和 token 用量；不记录 API Key、原始输入或原始输出。
- Ollama 未安装、服务未启动或模型不存在时只影响语义增强，规则路由和确定性工具继续工作。

## 验证证据

`tests/test_llm_client.py` 是不联网的 Mock 测试，验证云端结构化输出、Ollama 无 Key、本地端点限制、token 指标不泄露 Key、超时回退和额外参数过滤。`tests/test_llm_setup.py` 验证首次配置不自动下载模型，也不把 Key 写入配置。

`scripts/run_intent_eval.py` 读取 `tests/fixtures/intent_eval.jsonl`，产生 `reports/intent_eval_latest.json`。当前基准只代表有限的离线规则样本，不能作为真实模型准确率。下一阶段应增加 100–200 条人工标注样本，运行同一数据集的“规则基线”和“真实模型模式”，分别报告工具选择、参数正确率、拒绝率、P50/P95 延迟与 token 成本。
