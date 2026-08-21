# CI、Artifact 与分支保护

## 自动验证

`.github/workflows/verification.yml` 在以下情况运行：

- push 到 `main`；
- 向 `main` 发起或更新 Pull Request；
- 在 Actions 页面手动运行。

Windows Runner 使用 Python 3.12 安装 `requirements.txt`，检查补丁空白错误，然后执行：

```powershell
python scripts/run_ci_verification.py
```

该脚本依次运行完整回归、7题意图冒烟、RAG Eval、Tool/Skill Eval 和200条端到端 Agent Eval。某一组失败后仍继续运行其他组，最终只要存在失败或缺少报告就返回非零退出码。

## Artifact 证据

Workflow 的上传步骤带有 `if: always()`，因此测试失败时仍会上传已经产生的证据。Artifact 名称包含 `run_id` 与 `run_attempt`，保留30天，包括：

- `ci_verification_latest.json`：各验证目标的退出码、耗时、报告文件和 SHA-256；
- `latest_verification.json`：完整 unittest 逐条证据；
- `intent_eval_latest.json`；
- `rag_eval_latest.json`；
- `tool_engineering_latest.json`；
- `agent_eval_latest.json`：200条逐项结果。

在 GitHub 仓库进入 **Actions → Verification → 某次运行 → Artifacts** 下载。Artifact 是某次CI运行的证据，不能用仓库里旧的静态报告替代。

## 启用 main 分支保护

只有 Workflow 不会自动阻止合并。必须在 GitHub 远端启用 Branch protection：

1. 先把 `verification.yml` 推送到 GitHub，并让它至少成功运行一次。
2. 进入仓库 **Settings → Branches → Add branch protection rule**。
3. Branch name pattern 填 `main`。
4. 勾选 **Require a pull request before merging**。
5. 个人仓库可将批准数设为0；有协作者后建议改为至少1个批准，并勾选提交新 commit 后取消旧批准。
6. 勾选 **Require status checks to pass before merging**。
7. 勾选 **Require branches to be up to date before merging**。
8. 必需检查选择 `Required verification`。
9. 勾选 **Require conversation resolution before merging**。
10. 勾选 **Do not allow bypassing the above settings**（若当前套餐/UI提供）。
11. 禁止 force push 与 branch deletion，然后保存。

也可以在本机使用 API 配置脚本。先在当前 PowerShell 临时设置具有仓库 `Administration: write` 权限的 Token，然后运行：

```powershell
$env:GH_TOKEN = "你的临时GitHub Token"
.\scripts\configure_branch_protection.ps1
Remove-Item Env:GH_TOKEN
```

不要把 Token 写进脚本、YAML、README、终端截图或 Git。脚本要求的必需检查名称固定为 `Required verification`。

## 如何证明门禁生效

创建测试分支，故意让一项测试失败并发起 Pull Request。正确结果应同时满足：

- PR 页面显示 `Required verification` 红叉；
- 合并按钮被禁用；
- Actions 页面仍可下载失败运行的 Artifact；
- 修复并 push 后检查转绿，合并按钮才恢复。

远端分支保护属于 GitHub 仓库状态，不能通过提交一个文件自行生效。必须在 Settings 或 GitHub API 中完成一次配置。
