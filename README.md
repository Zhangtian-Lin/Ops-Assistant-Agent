# Ops Assistant Agent

[English](README.md) | [简体中文](README.zh-CN.md)

A local-first, security-aware Windows operations agent. It routes natural-language requests only to allowlisted tools, validates parameters before execution, separates high-risk actions through a Named Pipe Broker and approval workflow, and ships reproducible tests and evaluation evidence.

> An LLM may suggest a structured intent, but it cannot authorize an operation, execute arbitrary commands, or bypass policy and approval controls.

## Why this project

Most agent demos focus on calling a model and a tool. This project focuses on the engineering boundary around that call:

- Default read-only system, disk, service, network, and security checks.
- Optional LLM intent parsing with schema validation, timeout/retry limits, and deterministic rule fallback.
- A registered Tool / Skill contract: input schema, output schema, risk level, permission requirements, timeout, and classified error codes.
- A Windows Named Pipe Broker prototype for approvals; it derives the caller SID from the pipe rather than trusting a client-supplied role.
- SQLite approval state machine: `pending → approved → executing → executed / failed`, with expiry, immutable parameter snapshots, audit events, and single-winner execution claims.
- Structured `trace_id` task lifecycle, redacted audit outbox, and optional Windows Event Log delivery.
- Local knowledge retrieval and RAG source-retrieval evaluation.

## Architecture

```text
User request
  → Agent Runtime / TaskState
  → Router (optional LLM, otherwise rules)
  → ToolExecutor (schema + permission + policy + timeout)
  ├─ Registered read-only tool → result
  └─ High-risk request → Named Pipe Broker → approval state machine

Memory / RAG provide context; they never grant authorization.
```

For the request sequence diagrams and explicit component boundaries, see [Agent Runtime and Architecture](docs/Agent架构与运行时.md). The visual Chinese project map is available in [项目地图.md](docs/项目地图.md).

## Capabilities

| Area | Current capabilities |
|---|---|
| Host checks | CPU, memory, disk capacity, disk health, GPU, processes, event logs, drivers, scheduled tasks, sessions, and power state |
| Network | Local network state plus allowlisted DNS, TCP, and TLS checks; no arbitrary scanning or configuration changes |
| Knowledge | Local SOP retrieval, keyword/vector/hybrid retrieval, source-aware RAG evaluation |
| LLM | OpenAI-compatible, Ollama, Groq, and Volcengine-compatible configuration paths; optional and fail-safe |
| Safety | Tool registry, schemas, permissions, policy checks, approval workflow, skill static scanning, redacted traces |
| Engineering | Unit/integration/security test groups, intent and RAG evals, CI artifacts, release gate, issue templates |

## Security boundary and honest limitations

The agent does **not** support arbitrary shell commands, automatic file deletion, service restart/stop, firewall/DNS/routing changes, packet capture, port scanning, or automatic external Skill installation.

The Broker design is implemented as a local development prototype. It is **not yet** a production Windows Service with an independent service account, filesystem ACL enforcement, Named Pipe ACL enforcement, Restricted Token execution, or cross-account attack validation. Those claims are intentionally not made by this repository.

## Evidence

The repository contains machine-readable verification evidence:

- [Regression and security verification](reports/latest_verification.json)
- [Intent-routing evaluation](reports/intent_eval_latest.json)
- [RAG source-retrieval evaluation](reports/rag_eval_latest.json)
- [RAG evaluation notes and limitations](docs/RAG工程与评测.md)

The current suite is run locally and in GitHub Actions on Windows. CI uploads its JSON reports as artifacts for 30 days.

## Quick start

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\start_local.ps1
```

The first run offers a local security-mode setup. Without a configured mode, high-risk actions remain unavailable.

To enable optional LLM intent parsing, copy a template and keep the secret only in the environment:

```powershell
Copy-Item .\config\llm.example.yaml .\config\llm.yaml
$env:OPS_AGENT_LLM_API_KEY = "your-local-key"
```

Do not commit `config/*.yaml`, `data/runtime/`, or API keys. See [configuration layers](config/README.md).

## Verification and release workflow

```powershell
.\.venv\Scripts\python.exe scripts\run_verification.py
.\.venv\Scripts\python.exe scripts\run_intent_eval.py
.\.venv\Scripts\python.exe scripts\run_rag_eval.py
.\.venv\Scripts\python.exe scripts\check_release.py --tag v0.4.0
```

Pushes and pull requests to `main` run the same verification path in [GitHub Actions](.github/workflows/verify.yml). Releases are manual and are only created after the release workflow reruns tests and evals; see [release process](docs/发布流程.md).

## Documentation map

- [Chinese README](README.zh-CN.md): complete local setup and feature documentation.
- [LLM engineering](docs/LLM工程化调用说明.md)
- [Tool and Skill engineering](docs/Tool与Skill工程说明.md)
- [Agent Runtime](docs/Agent架构与运行时.md)
- [RAG engineering](docs/RAG工程与评测.md)
- [Audit tracing](docs/审计追踪实施说明.md)
- [Learning and optimization roadmap](docs/学习与优化路线.md)

## License and contribution

This repository currently has no license file. Before accepting external contributions or distributing it broadly, choose and add an appropriate license. Please use the Bug and Feature issue templates and never include secrets, approval databases, raw private documents, Windows SIDs, or full user paths in issues.
