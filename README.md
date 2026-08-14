# 本地安全运维 Agent

一个本地优先、可审计、可扩展、默认只读的运维 Agent。它将自然语言请求路由到经过白名单、参数校验和风险控制的工具，并结合会话记忆与本地运维知识库提供有依据的结果和建议。

> LLM 可以理解意图和组织回答，但不能绕过安全策略、任意执行命令或自行决定权限。

## 项目目标

- 检查 CPU、内存、磁盘、服务和工作区文件。
- 分析指定磁盘根目录的一级内容分布。
- 审计本地 Skill 或目录的静态安全风险。
- 维护摘要、关键词索引、原始历史和向量检索组成的会话记忆。
- 导入并检索本地运维 SOP、故障手册和规范文档。
- 通过并行融合检索，将会话事实与知识库建议分别提供给回答层。
- 以可选 LLM 提升意图理解能力；模型不可用时回退到确定性规则路由。
- 以独立、只读的网络模块检查本机网络状态及受授权目标的连通性。

## 非目标与安全边界

首期不支持任意 Shell 命令执行、自动重启或停止服务、删除文件、修改 DNS/路由/代理/防火墙、任意网段扫描、端口扫描、抓包，以及自动下载或执行外部 Skill。

- 工具只能来自注册表与白名单。
- 所有路径、服务名、主机名和端口均须通过校验。
- 高风险操作只能创建待审批请求，不能自动执行。
- 外部文档、知识库文本和 LLM 输出都不是权限授权来源。
- 运行时记忆、向量库、网络观测数据和敏感配置不得提交到 Git。

## 总体架构

```text
用户自然语言请求
        │
        ▼
意图识别层：LLM（可选）+ 规则路由回退
        │
        ▼
工具策略层：白名单、参数校验、风险分级、审批、超时、审计
        │
        ├── 检索协调器：并行召回与融合
        │     ├── 会话摘要 / 抽象摘要
        │     ├── 关键词历史
        │     ├── 会话向量
        │     └── 知识库向量
        │
        └── 工具执行器：系统检查 / 网络检查 / Skill 审计
                 │
                 ▼
回答、只读检查结果、待审批请求、审计记录、会话记忆更新
```

## 项目结构

```text
my-agent/
├── agent.py                       # 入口、路由、工具注册与安全校验
├── core/
│   ├── memory.py                  # 会话记忆、摘要、索引、检索协调
│   ├── vector_engine.py           # SQLite 向量存储与语义检索
│   ├── network/                   # 计划中的独立网络检查模块
│   │   ├── local_status.py        # 网卡、IP、路由、端口、连接
│   │   ├── connectivity.py        # DNS、TCP、TLS 连通性
│   │   ├── policy.py              # 网络白名单与限制
│   │   └── audit.py               # 网络检查审计
│   └── security_scanner/          # Skill 静态安全审计
├── scripts/
│   └── ingest_knowledge.py        # 知识文档切片与导入
├── config/
│   └── network_policy.yaml        # 计划中的网络策略文件
├── data/
│   ├── knowledge_base/            # 静态 SOP 与手册
│   ├── memory/                    # 运行时会话数据（Git 忽略）
│   └── runtime/                   # 可选网络快照（Git 忽略）
├── docs/
│   └── PROJECT_CONCEPT.md
├── requirements.txt
└── README.md
```

`core/network/` 和 `config/network_policy.yaml` 是后续网络功能的目标布局，当前尚未实现。

## 当前工具

| 工具 | 功能 | 风险 |
|---|---|---|
| `check_cpu` | CPU 使用率 | 低，只读 |
| `check_memory` | 内存使用情况 | 低，只读 |
| `check_disk` | 磁盘容量与剩余空间 | 低，只读 |
| `analyze_disk_distribution` | 磁盘根目录一级内容分布 | 低，只读 |
| `check_service` | 白名单服务状态 | 低，只读 |
| `search_files` | 工作区文件搜索 | 低，只读 |
| `query_memory` | 会话记忆查询 | 低，只读 |
| `audit_skill` | Skill/目录静态安全审计 | 低，只读 |

## 会话记忆与知识库

会话记忆保存动态事实，知识库保存稳定资料；两者可共用 SQLite 向量存储，但必须按类型隔离。

| 类型 | 内容 | 用途 |
|---|---|---|
| `summary` | 当前目标、近期主题、高层结论 | 快速理解上下文 |
| `abstract` | 多条历史事件的摘要 | 长会话压缩 |
| `history` | 原始问题、工具调用、执行结果 | 最终事实依据 |
| `knowledge` | SOP、规范、故障手册片段 | 提供处理建议 |

原始历史优先于摘要；知识库提供建议，不能被描述为当前系统的已验证事实。

### 知识库导入

首期支持 `.md` 与 `.txt` 文档。导入时按标题或长度切片，并保存来源文件、片段序号和导入时间等元数据。

```text
知识文档 → 文本清洗 → 切片 → 元数据 → 向量化 → SQLite
```

## 检索并行融合

后续检索层将并行执行：摘要召回、关键词历史召回、会话向量召回和知识库向量召回。结果统一标准化、去重、过滤和排序，然后返回两类上下文：

```text
memory_context     # 用户历史与工具产生的动态事实
knowledge_context  # SOP、手册和静态知识建议
```

每个结果应包含来源、文本、相似度、关键词得分、时间得分和最终得分。查询“当前状态”时优先历史与时间；查询“怎么处理”时提高知识库权重。单个召回器失败不得影响其余检索源。

## LLM 意图识别

LLM 是可选增强层，负责理解请求、提取候选工具和参数，并返回受约束的 JSON：

```json
{
  "intent": "system_check",
  "tool": "check_memory",
  "arguments": {},
  "retrieval_needed": true,
  "needs_confirmation": false,
  "confidence": 0.93
}
```

输出必须依次通过 JSON Schema、工具白名单、参数安全校验和风险判断。未配置模型、模型调用失败、输出非法、工具未注册或置信度过低时，系统回退到现有规则路由。

## 网络功能设计

网络功能将作为独立模块加入，不影响现有记忆、知识库、系统检查或安全扫描功能。

```text
检查 CPU
  → 不加载网络模块
  → 网络模块故障不会影响结果

检查网络
  → 按需加载 core/network/
  → 独立超时与异常处理
  → 故障仅返回 network_error
```

第一阶段仅提供只读能力：

```text
本机：网卡、IP、DNS、路由、监听端口、活动连接、防火墙状态
受控目标：DNS 解析、TCP 端口连通性、TLS 证书检查
```

网络检查只能访问策略文件允许的目标和端口，例如：

```yaml
network:
  mode: local_readonly
  allowed_hosts:
    - api.internal.example
    - 10.0.2.15
  allowed_ports: [53, 443, 5432]
  timeout_seconds: 5
  allow_private_addresses: true
  allow_public_addresses: false
```

网络查询不会下载 Skill，也不会自动触发 Security Scanner。三条路径相互独立：

```text
检查网络       → core/network
审计本地 Skill → core/security_scanner
安装外部 Skill → 隔离下载 → Security Scanner → 用户确认 → 安装
```

## 实施路线

1. **检索并行融合**：拆分现有检索逻辑，建立统一结果结构、去重、排序和来源分组。
2. **知识库正式接入**：让知识库向量结果参与融合，并返回来源文件与片段证据。
3. **LLM 意图识别**：实现受约束 JSON 路由、工具白名单、低置信度与故障回退。
4. **独立网络只读模块**：按需加载，先实现本机状态，再实现白名单 DNS/TCP/TLS 检查。

## 安全与验收要求

- 网络模块异常或超时不影响其他功能。
- 单个检索源失败不影响总体检索。
- LLM 不可用时现有规则路由正常工作。
- LLM 不可调用未注册工具或绕过审批。
- 非白名单网络目标不能自动访问。
- 高风险操作必须生成可追溯的待审批请求。
- 会话历史、网络记录与审计日志必须脱敏，并遵循最小留存原则。

## 快速开始

```powershell
# 创建本地环境并安装依赖（首次运行）
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 直接提问
.\.venv\Scripts\python.exe agent.py "Please check my CPU usage"

# 交互模式
.\.venv\Scripts\python.exe agent.py
```
