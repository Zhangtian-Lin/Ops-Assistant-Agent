# 本地安全运维 Agent

> 第一次阅读或重新回到项目时，先看 [`docs/项目地图.md`](docs/项目地图.md)。

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
        └── 审批流程：pending → approved → executing → executed / failed
```

## 项目结构

```text
my-agent/
├── agent.py                       # 入口、路由、工具注册与安全校验
├── core/
│   ├── memory.py                  # 多层记忆、检索协调
│   ├── vector_engine.py           # SQLite 向量存储与语义检索
│   ├── intent_parser.py           # LLM 意图解析 + 规则回退
│   ├── approvals.py               # SQLite 审批状态机、迁移与审计事件
│   ├── action_policy.py           # 工具风险与审批要求的唯一策略表
│   └── security_scanner/          # Skill 静态安全审计（10 条规则）
├── scripts/
│   └── ingest_knowledge.py        # 知识文档切片与导入（导入前先安全审计）
├── data/
│   ├── knowledge_base/            # 静态 SOP 与手册
│   ├── memory/                    # 运行时会话数据（Git 忽略）
│   └── runtime/                   # 审批数据库与审计记录（Git 忽略）
├── docs/
│   └── PROJECT_CONCEPT.md
├── requirements.txt
└── README.md
```

`core/network/` 已实现为独立只读模块：本机状态查询始终可用；外部 DNS、TCP、TLS 查询则默认拒绝，必须由本地 `config/network_policy.yaml` 明确白名单授权。

## 当前工具

| 工具 | 功能 | 风险 |
|---|---|---|
| `check_cpu` | CPU 使用率 | 低，只读 |
| `check_memory` | 内存使用情况 | 低，只读 |
| `check_disk` | 磁盘容量与剩余空间 | 低，只读 |
| `analyze_disk_distribution` | 磁盘根目录一级内容分布 | 低，只读 |
| `check_service` | 白名单服务状态 | 低，只读 |
| `check_network` | 本机网络状态、白名单 DNS/TCP/TLS 检查 | 低，只读 |
| `check_system` | GPU、磁盘健康、进程、系统盘点、安全基线、日志、驱动、任务、会话、电源 | 低，只读 |
| `search_files` | 工作区文件搜索 | 低，只读 |
| `query_memory` | 会话记忆查询（附带知识库结果） | 低，只读 |
| `query_knowledge` | 知识库语义检索 | 低，只读 |
| `audit_skill` | Skill/目录静态安全审计 | 低，只读 |
| `clear_memory` | 发起清空记忆审批 | 需审批 |
| `list_approvals` | 查看待审批请求 | 低，只读 |
| `approve_request_tool` | 批准并执行审批请求 | 需审批 |
| `cancel_request_tool` | 取消尚未执行的审批请求 | 需审批 |

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

- `object` 必须命中白名单（包括 approve、cancel、list_approvals 在内共 13 类），`action` 必须是 check/control/none。
- `args` 只保留各 object 声明过的字段（如 disk→path、service→service_name），多余字段丢弃。
- LLM 填的参数仍须过参数校验（路径存在性、服务名白名单）。
- 未配置模型、调用失败、输出非法、object 不在白名单时，回退到规则路由（`parse_action_and_object`）。

## 审批机制

破坏性操作（当前是“清空记忆”）不直接执行，而是走持久化审批状态机：

交互界面将待审批项显示为短编号（`1`、`2`……），可输入“批准 1”或“取消 1”。短编号只在当前待处理列表中解析；提交给 Broker 的仍是随机、不可预测的完整请求 ID，因此不降低请求绑定与防猜测保护。

```text
pending → approved → executing → executed
                         └→ failed
pending → cancelled / expired
```

- 存储：`data/runtime/approvals.db` 使用 SQLite 的事务、WAL 与锁处理并发；不提交到 Git。
- 发起：`clear_memory` 创建随机、不可预测的 `apr-...` 请求，默认有效期为 10 分钟。
- 批准：仅 `pending` 且未过期的请求可进入 `approved`；批准后 Agent 原子领取为 `executing`。
- 执行：执行器成功时写入 `executed`，异常时写入 `failed`；重复批准、重复执行和过期批准均会拒绝。
- 取消：`cancel_request_tool` 可取消 `pending` 或 `approved` 请求。
- 审计：每次创建、批准、领取、完成、失败、取消或过期都会写入独立审计事件；执行前校验参数快照摘要。
- 迁移：旧 `pending_approvals.json` 会被导入；因缺少安全有效期，旧请求统一标记为 `expired`，不会被执行。

所有工具的风险等级、执行模式与审批要求集中定义在 `core/action_policy.py`。未注册工具默认拒绝；新增高风险动作必须同时声明策略与执行器。

## 安全运行模式与 Windows Named Pipe Broker

身份与职责分离通过 Windows Named Pipe Broker 实现。Broker 独占审批数据库和执行器；客户端只提交操作意图，Broker 从 Named Pipe 连接模拟客户端并读取其 Windows SID，不信任客户端自报的用户名或角色。

首次以交互模式启动时，若尚未配置，Agent 会询问选择单用户或多用户模式；按回车会跳过配置，并保持高风险操作不可用。也可由管理员通过初始化脚本选择并写入本地 `config/security_mode.yaml` 与 `config/identity_policy.yaml`：

| 模式 | 使用场景 | 高风险操作行为 |
|---|---|---|
| 单用户受控模式 | 个人开发与本机测试 | 同一 Windows SID 可发起和批准，但需明确二次确认，并在审计中标记为单人审批 |
| 多用户职责分离模式 | 正式或多人使用 | 请求人与审批人必须是不同 Windows SID；仅 `operator` 可发起、仅 `approver` 可批准 |

安全模式不是每次对话都可自由选择的角色。模式只能由管理员切换；切换时必须取消或失效全部 `pending`/`approved` 请求，避免在较低安全模式创建的请求被较高或较低安全模式继续执行。

多用户模式的运行流程：

```text
Operator（Windows SID A）创建请求
  → Named Pipe Broker 校验 operator 权限
  → pending

Approver（Windows SID B）连接 Broker 并批准
  → Broker 校验 approver 权限与 SID A != SID B
  → approved → executing → executed / failed
```

同一 Windows 身份在对话中声称自己是 `approver` 不会获得权限；角色必须来自 Broker 识别的 Windows SID 和受保护的身份策略。当前没有第二个 Windows 账户时，应使用单用户受控模式开发与测试，不将其误认为双人审批。

初始化单用户模式：

```powershell
.\.venv\Scripts\python.exe scripts\initialize_security.py --mode single_user_controlled
.\.venv\Scripts\python.exe scripts\run_broker.py
```

日常开发可直接使用统一启动器，它会在首次运行时用序号询问安全模式，后台启动 Broker、确认 Named Pipe 就绪后再启动 Agent；Agent 退出时会停止由该启动器创建的 Broker：

```powershell
.\scripts\start_local.ps1
```

若检测到已运行的 Broker，启动器会复用它，且不会在 Agent 退出时停止该既有进程。

多用户模式需要提供不同的 Windows SID：

```powershell
.\.venv\Scripts\python.exe scripts\initialize_security.py `
  --mode multi_user_separation `
  --operator-sid "S-1-5-21-..." `
  --approver-sid "S-1-5-21-..."
```

开发时 `run_broker.py` 可以作为当前用户进程运行。正式多用户部署时应将 Broker 注册为专用服务账户运行，并通过 Windows ACL 限制 `data/runtime/approvals.db`、配置文件和已部署代码只能由 Broker/管理员写入；否则不同本机用户仍可能绕过数据库边界。

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

### 网络模块使用

本机网络状态可直接询问“检查网络状态”。外部检查需要先创建本机策略文件：

```powershell
Copy-Item .\config\network_policy.example.yaml .\config\network_policy.yaml
```

随后仅可查询 `allowed_hosts` 和 `allowed_ports` 的组合，例如“检查 DNS api.internal.example”、“检查 TCP api.internal.example 443”或“检查 TLS api.internal.example”。策略默认禁止公网地址；网络模块不会下载 Skill、运行端口扫描或更改网络配置。

### Windows 常见系统检查

可直接使用自然语言，例如“现在电脑上有 GPU 吗”“检查磁盘健康”“查看内存占用最高的进程”“现在电脑上有几个系统”“检查安全基线”“查看近七天系统错误日志”“检查驱动异常”“查看正在运行的计划任务”“查看已登录用户”或“检查电池状态”。这些检查只读取 Windows 的本地状态，不执行修复、更新、清理或配置变更。

## 实施路线

1. **检索并行融合**：已完成。
2. **知识库正式接入**：已完成。
3. **LLM 意图识别**：已完成。
4. **审批机制**：已完成。
5. **独立网络只读模块**：已完成本机状态与白名单 DNS/TCP/TLS 检查；网络控制操作仍未实现。
6. **control 工具（重启/停止服务）**：计划中。

## 安全与验收要求

- 单个检索源失败不影响总体检索。
- LLM 不可用时规则路由正常工作。
- LLM 不可调用未注册工具或绕过审批。
- 非白名单服务名不能自动操作。
- 高风险操作必须生成可追溯的待审批请求。
- 会话历史、审计日志必须脱敏，并遵循最小留存原则。

## 可重复可靠性验证

运行以下命令会执行隔离的路由、安全、审批并发、网络策略与 Skill 扫描测试，并生成机器可读结果：

```powershell
.\.venv\Scripts\python.exe scripts\run_verification.py
```

最新结果写入 `reports/latest_verification.json`；测试范围、测量结果与尚未覆盖的边界见 [`docs/可靠性验证报告.md`](docs/可靠性验证报告.md)。每条 JSON 记录均包含测试输入、预期、实际观察、断言结果和耗时。

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
