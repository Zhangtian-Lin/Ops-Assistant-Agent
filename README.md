# 本地安全运维 Agent

一个本地优先、可审计、可扩展、默认只读的运维 Agent。它将自然语言请求路由到经过白名单、参数校验和风险控制的工具，并结合会话记忆与本地运维知识库提供有依据的结果和建议。

> LLM 可以理解意图和组织回答，但不能绕过安全策略、任意执行命令或自行决定权限。

## 项目目标

- 检查 CPU、内存、磁盘、服务和工作区文件。
- 分析指定磁盘根目录的一级内容分布。
- 审计本地 Skill 或目录的静态安全风险。
- 维护摘要、抽象、关键词索引、原始历史和向量检索组成的多层会话记忆。
- 导入并检索本地运维 SOP、故障手册和规范文档。
- 通过并行融合检索，将会话事实与知识库建议分别提供给回答层。
- 以可选 LLM 提升意图理解能力；模型不可用时回退到确定性规则路由。
- 破坏性操作（如清空记忆）走审批流程，批准后才执行。

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
意图识别层：LLM（可选）→ 失败回退规则路由（core/intent_parser.py）
        │
        ▼
路由与校验：工具路由、参数校验、风险分级（agent.py）
        │
        ├── 检索协调器（core/memory.py）：关键词 + 向量并行召回与融合
        │     ├── 会话摘要 summary / 抽象 abstract
        │     ├── 关键词索引 index
        │     ├── 会话向量 history（SQLite）
        │     └── 知识库向量 knowledge（SQLite）
        │
        ├── 工具执行器：系统检查 / 文件搜索 / 知识库检索 / Skill 审计
        │
        └── 审批流程：发起 → 挂起 → 批准 → 查表执行
```

## 项目结构

```text
my-agent/
├── agent.py                       # 入口、路由、工具注册与安全校验
├── core/
│   ├── memory.py                  # 多层记忆、检索协调、审批状态机
│   ├── vector_engine.py           # SQLite 向量存储与语义检索
│   ├── intent_parser.py           # LLM 意图解析 + 规则回退
│   └── security_scanner/          # Skill 静态安全审计（10 条规则）
├── scripts/
│   └── ingest_knowledge.py        # 知识文档切片与导入（导入前先安全审计）
├── data/
│   ├── knowledge_base/            # 静态 SOP 与手册
│   └── memory/                    # 运行时会话数据（Git 忽略）
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
| `query_memory` | 会话记忆查询（附带知识库结果） | 低，只读 |
| `query_knowledge` | 知识库语义检索 | 低，只读 |
| `audit_skill` | Skill/目录静态安全审计 | 低，只读 |
| `clear_memory` | 发起清空记忆审批 | 需审批 |
| `list_approvals` | 查看待审批请求 | 低，只读 |
| `approve_request_tool` | 批准并执行审批请求 | 需审批 |

## 会话记忆与知识库

会话记忆保存动态事实，知识库保存稳定资料；两者共用 SQLite 向量存储，按 `item_type` 隔离（`history` / `abstract` / `knowledge`）。

| 类型 | 内容 | 用途 |
|---|---|---|
| `summary` | 当前目标、近期主题、高层结论 | 快速理解上下文 |
| `abstract` | 多条历史事件的摘要 | 长会话压缩 |
| `index` | 关键词 → 事件映射 | 精确召回 |
| `history` | 原始问题、工具调用、执行结果 | 最终事实依据 |
| `knowledge` | SOP、规范、故障手册片段 | 提供处理建议 |

原始历史优先于摘要；知识库提供建议，不能被描述为当前系统的已验证事实。

### 知识库导入

首期支持 `.md` 与 `.txt` 文档。导入时按行切片（约 400 字），保存来源文件前缀；导入前先对知识库目录做安全审计（R1-R6），BLOCK 则拒绝入库。

```text
知识文档 → 前置安全审计 → 文本切片 → 向量化 → SQLite（item_type=knowledge）
```

## 检索并行融合

关键词精确召回与向量语义召回并行执行，结果加权融合排序，原始历史只负责按 id 取事实、不参与排序：

```text
关键词召回（精确，权重 1.0）
      ──┐
        ├── 融合评分（fused_scores）→ 排序 → top_k
      ──┘
向量召回（语义，权重 = 余弦相似度）
```

单个召回源失败不影响整体检索。最终返回 `memory_context`（历史事实）与 `knowledge_context`（静态知识）两类来源，分别标注。

## LLM 意图识别

LLM 是可选增强层，负责把自然语言解析为受约束的结构化意图（`core/intent_parser.py`）：

```json
{
  "action": "check",
  "object": "memory",
  "args": {"query": "内存占用"}
}
```

- `object` 必须命中白名单（cpu/memory/disk/.../approve 共 12 类），`action` 必须是 check/control/none。
- `args` 只保留各 object 声明过的字段（如 disk→path、service→service_name），多余字段丢弃。
- LLM 填的参数仍须过参数校验（路径存在性、服务名白名单）。
- 未配置模型、调用失败、输出非法、object 不在白名单时，回退到规则路由（`parse_action_and_object`）。

## 审批机制

破坏性操作（当前是"清空记忆"）不直接执行，而是走审批闭环：

```text
发起（存 action + 参数）→ 挂起 → 批准（只标记 approved）→ 查表分发 → 执行
```

- 发起：`clear_memory` 创建 pending 申请，返回 `request_id`。
- 查看：`list_approvals` 列出所有 `pending` 状态请求。
- 批准：`approve_request_tool` 调 `approve_request`（只做状态变更），再通过 `APPROVAL_EXECUTORS` 映射表找到执行函数并调用。
- 主动提示：启动时和每次交互后检查 pending，有则提示。

`memory` 层只管审批状态机，执行分发在 `agent` 层（避免循环依赖）。新增审批动作只需：映射表加一行 + 加一个发起函数。

## 网络功能设计（计划中，尚未实现）

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

1. **检索并行融合**：已完成。
2. **知识库正式接入**：已完成。
3. **LLM 意图识别**：已完成。
4. **审批机制**：已完成。
5. **独立网络只读模块**：计划中，先实现本机状态，再实现白名单 DNS/TCP/TLS 检查。
6. **control 工具（重启/停止服务）**：计划中。

## 安全与验收要求

- 单个检索源失败不影响总体检索。
- LLM 不可用时规则路由正常工作。
- LLM 不可调用未注册工具或绕过审批。
- 非白名单服务名不能自动操作。
- 高风险操作必须生成可追溯的待审批请求。
- 会话历史、审计日志必须脱敏，并遵循最小留存原则。

## 快速开始

```powershell
# 创建本地环境并安装依赖（首次运行）
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 直接提问
.\.venv\Scripts\python.exe agent.py "帮我检查 CPU"

# 交互模式
.\.venv\Scripts\python.exe agent.py
```
