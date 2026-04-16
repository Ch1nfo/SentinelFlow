<div align="center">

# SentinelFlow

### AI-Powered Security Operations Platform — Multi-Agent SOC Automation

[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/Ch1nfo/SentinelFlow/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#)
[![Built with LangGraph](https://img.shields.io/badge/built%20with-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)

English | [中文](README_ZH.md)

</div>

---

## Why SentinelFlow?

Modern Security Operations Centers face an overwhelming volume of alerts — most teams spend hours triaging events that could be handled in seconds with proper automation. Existing SIEM platforms offer rules-based correlation, but lack the contextual reasoning needed to handle novel threats or complex multi-step investigations.

**SentinelFlow** is a full-stack SOC automation platform that combines a **LangGraph-powered multi-agent orchestration runtime** with a **React WebUI** for alert management. Instead of rigid playbooks, you get a flexible, extensible agent system where a Primary Supervisor Agent coordinates specialized Worker Sub-Agents — each equipped with pluggable Skills that can call external APIs, run enrichment scripts, close tickets, and more.

- **Multi-Agent Orchestration** — Supervisor + Worker SubGraph pattern via LangGraph; each worker is an isolated ReAct agent wrapped as a tool
- **Pluggable Skill System** — Drop a `SKILL.md` + `main.py` into the skills directory; agents discover and invoke them automatically, with granular per-agent permission control
- **Dual Entry Points** — Accepts both raw security alerts (JSON payloads from SIEM/SOAR) and free-form human commands via the WebUI chat interface
- **Agent Workflow Engine** — Define fixed multi-step workflows for high-frequency scenarios; the Primary Agent selects the best workflow or falls back to free ReAct
- **Dual Alert Source Types** — Connect to upstream APIs (REST/HTTP) or drive any custom data source via a Python script entrypoint
- **AI-Assisted Parser Generation** — Paste a sample alert payload and let the LLM auto-generate the field-mapping parser rule, with live preview
- **Continuous Auto-Execution** — Enable the auto-execute loop to process queued alerts automatically without human intervention
- **Fine-Grained Policy** — Per-agent skill allowlists/denylists, execution approval gates, audit logging, and cancellation support
- **Full-Stack** — FastAPI backend + React/Vite frontend, unified dev entrypoint, production-ready project layout

## Screenshots

|                        Security Overview Dashboard                        |                        Agent Chat Panel                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405225720016](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405225720053.png) | ![image-20260405231100920](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260406140803364.png) |

|                        Alert Triage                        |                        Skill Creation Panel                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405225903594](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405225903635.png)| ![image-20260405230107750](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230107788.png) |

|                        Sub-Agent Creation Panel                         |                        Agentsflow                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405230145352](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230145399.png) | ![image-20260405230315299](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230315341.png) |

## Features

### Multi-Agent Orchestration

- **Supervisor + Worker SubGraph** — Primary Agent uses LangGraph's `ToolNode` to delegate tasks to Worker Sub-Agents, each compiled as an isolated ReAct SubGraph wrapped as a `@tool`
- **Parallel Delegation** — Primary Agent can dispatch multiple independent sub-tasks to different workers simultaneously via `delegate_parallel`
- **Agent Workflow Engine** — Define reusable workflows for common scenarios (e.g., phishing triage, IP enrichment + block); Primary Agent selects the best workflow via LLM reasoning
- **Cancellation & Step Limits** — All graphs respect a `cancel_event` threading flag; `worker_max_steps` caps orchestration recursion depth

### Pluggable Skill System

- **SKILL.md-based discovery** — Each skill is a directory with a `SKILL.md` (YAML frontmatter + documentation body) and an optional `main.py` entrypoint
- **Two skill types**: `doc` (knowledge-only, read by agent) and `hybrid` (doc + executable subprocess)
- **Per-agent permission control** — `doc_skill_allowlist`, `exec_skill_allowlist`, `approval_required` flags per skill
- **Subprocess execution** — Skills run in isolated subprocesses with structured JSON I/O; audit logging built in
- **In-WebUI Skill Management** — Create, edit, delete, and debug skills directly from the Settings panel

### Alert Ingestion Pipeline

- **Dual alert source types** — `api` mode polls any REST endpoint (configurable method, headers, query, body); `script` mode runs a custom Python script and reads its stdout as the alert payload
- **AI-powered parser generation** — Paste a raw sample payload; the LLM auto-generates a `field_mapping` parser rule with live preview and one-click apply
- **Flexible field mapping** — Point-path-based rules map arbitrary JSON structures to SentinelFlow's canonical alert schema (`eventIds`, `alert_name`, `sip`, `dip`, `alert_time`, etc.)
- **Deduplication & idempotency** — SQLite-backed dedup store prevents re-queueing already-active alerts; concurrent dispatch is guarded at the DB layer
- **Polling scheduler** — Configurable poll interval; supports immediate manual poll trigger from the UI
- **Fallback & retry** — Failed tasks can be retried manually or automatically on the next poll cycle

### Task Queue & Execution

- **SQLite-backed task queue** — All alert handling tasks are persisted to `.sentinelflow/sys_queue.db`; survives process restarts
- **Continuous auto-execution** — Enable the auto-executor loop to process all queued tasks sequentially without human action
- **Manual handling** — Trigger single-task execution from the alert workbench at any time
- **Task lifecycle** — `queued → running → succeeded / failed`; tasks disappeared from the source are automatically closed as "handled manually"
- **Full execution trace** — Every task stores a structured `execution_trace` covering alert receipt, agent analysis, skill calls, closure result, and final status

### Security Operations WebUI

- **Alert Workbench** — Browse, filter, and manually trigger alert tasks; inspect full agent reasoning traces
- **Agent Chat** — Free-form command interface; send human instructions directly to the Primary Agent with streaming response
- **Configuration Center** — Unified settings page for LLM credentials, alert source connection, parser rules, polling schedule, and auto-execution toggle — all persisted without restarting the server
- **Skill Management** — Create, view, edit, and delete skills; run debug executions with custom arguments
- **Agent Management** — Configure Primary Agent and Worker Sub-Agents: prompts (default / alert / command / synthesis variants), LLM overrides, skill permissions
- **Workflow Management** — Create and edit Agent Workflows; run test executions from the UI

### Platform & Architecture

- **FastAPI backend** — Async Python runtime with structured JSON API; uvicorn server
- **React + Vite frontend** — TypeScript, TailwindCSS, component-based architecture
- **Unified dev entrypoint** — `python scripts/dev.py dev` starts the full stack in one command
- **Clean project layout** — Strict separation of `runtime/`, `webui/`, `examples/`, `scripts/`; no `PYTHONPATH`-based startup hacks

## Architecture Overview

<details>
<summary><strong>System Architecture Diagram</strong></summary>

```
┌─────────────────────────────────────────────────────────────────┐
│                   React WebUI (Vite + TS)                       │
│  ┌──────────────┐  ┌─────────────────┐  ┌───────────────────┐   │
│  │ Alert Panel  │  │  Agent Chat UI  │  │  Config Manager   │   │
│  └──────────────┘  └─────────────────┘  └───────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │  REST API (FastAPI)
┌──────────────────────────▼──────────────────────────────────────┐
│              SentinelFlow Runtime (Python / FastAPI)            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │               Multi-Agent Orchestrator                     │  │
│  │   ┌──────────────────────────────────────────────────┐    │  │
│  │   │  Primary Agent (Supervisor)                       │    │  │
│  │   │  LangGraph StateGraph + ToolNode                  │    │  │
│  │   │    ↓ sequential / parallel worker delegation      │    │  │
│  │   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │    │  │
│  │   │  │  Worker A  │  │  Worker B  │  │  Worker C  │  │    │  │
│  │   │  │ ReAct Sub- │  │ ReAct Sub- │  │ ReAct Sub- │  │    │  │
│  │   │  │   Graph    │  │   Graph    │  │   Graph    │  │    │  │
│  │   │  └────────────┘  └────────────┘  └────────────┘  │    │  │
│  │   └──────────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    Skill Runtime                           │  │
│  │    loader → executor → subprocess isolation → audit log    │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Alert Ingestion & Task Queue                  │  │
│  │  API/Script Poller → Parser → Dedup → SQLite Task Queue    │  │
│  │  Auto-Executor Loop → Task Runner → Agent/Workflow         │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Core Design Patterns**

- **Supervisor + Worker SubGraph** — Workers are compiled ReAct SubGraphs, wrapped as `@tool` functions; only `final_response` surfaces back to the Supervisor as a `ToolMessage`
- **SKILL.md discovery** — Skills are file-system plugins; no code changes needed to add new capabilities
- **Dual entry types** — `alert` (JSON from SIEM) and `conversation` (human command); both routed through the same agent runtime
- **SQLite task persistence** — Alert tasks survive restarts; atomic status transitions prevent duplicate execution
- **Atomic result serialization** — All graph results pass through `_serialize_alert_result` for a consistent, structured execution trace

**Key Components**

- **`SentinelFlowAgentService`** — Top-level service; routes to orchestrator or single-agent graph; serializes results
- **`build_orchestrator_graph()`** — Compiles the Supervisor + Worker multi-agent LangGraph
- **`build_agent_graph()`** — Builds a single-agent ReAct SubGraph (used for both workers and standalone agents)
- **`AlertDispatchService`** — SQLite-backed task queue; handles create, dedup, status transition, and finalization
- **`AlertAutoExecutionService`** — Asyncio-based continuous executor loop; processes queued tasks without human action
- **`AlertParserGenerator`** — LLM-assisted + heuristic field-mapping rule generator for arbitrary JSON alert payloads
- **`SentinelFlowSkillRuntime`** — Manages skill lifecycle; adapts skills as LangChain tools for agent use
- **`AgentWorkflowRegistry`** — Lists and resolves workflow definitions for multi-step Agent Workflows

</details>

<details>
<summary><strong>Project Structure</strong></summary>

```
.
├── pyproject.toml                      # Python package & CLI metadata
├── scripts/
│   ├── dev.py                          # Unified local dev entrypoint
│   └── serve_webui.py                  # Production WebUI static file server
├── runtime/
│   └── sentinelflow/
│       ├── agent/
│       │   ├── service.py              # Top-level agent service (orchestration logic)
│       │   ├── orchestrator_graph.py   # Supervisor + Worker SubGraph builder
│       │   ├── graph.py                # Single-agent ReAct graph builder
│       │   ├── registry.py             # Agent definition loader (agent.yaml)
│       │   ├── prompts.py              # System prompts & appendix templates
│       │   ├── policy.py               # Per-agent skill permission resolver
│       │   ├── nodes.py                # LangGraph node implementations
│       │   ├── tools.py                # Agent-facing tool definitions
│       │   └── state.py                # Agent graph state schema
│       ├── skills/
│       │   ├── loader.py               # SKILL.md discovery & validation
│       │   ├── executor.py             # Skill subprocess execution
│       │   ├── adapters.py             # Skill → LangChain tool adapters
│       │   └── models.py               # Skill data models
│       ├── alerts/
│       │   ├── client.py               # Alert source HTTP/script client
│       │   ├── poller.py               # Scheduled polling service
│       │   ├── parser_runtime.py       # Field-mapping parser engine
│       │   ├── parser_generator.py     # LLM + heuristic parser rule generator
│       │   └── dedup.py                # Alert deduplication store
│       ├── services/
│       │   ├── dispatch_service.py     # SQLite-backed task queue & lifecycle
│       │   ├── task_runner_service.py  # Task execution orchestration
│       │   ├── auto_execution_service.py # Continuous auto-executor loop
│       │   ├── triage_service.py       # Rule-based alert disposition fallback
│       │   └── audit_service.py        # Audit event log
│       ├── workflows/                  # Agent workflow registry & runner
│       ├── api/                        # FastAPI route handlers
│       ├── config/                     # Runtime config loader (.env + persisted JSON)
│       └── domain/                     # Shared enums, models, errors
├── webui/
│   └── src/
│       ├── components/                 # React UI components
│       ├── pages/                      # Page-level views
│       ├── api/                        # API client (fetch wrappers)
│       ├── hooks/                      # Custom React hooks
│       └── styles/                     # Global styles & Tailwind config
└── examples/
    ├── skills/                         # Example skill plugins
    ├── agents/                         # Example agent definitions
    ├── tasks/                          # Example alert payloads
    └── workflows/                      # Example agent workflows
```

</details>

<details>
<summary><strong>Development Guide</strong></summary>

### Environment Requirements

- Python 3.11+
- Node.js 18+ / pnpm 8+
- (Optional) A LangGraph-compatible LLM API key (OpenAI-compatible endpoint)

### Development Commands

```bash
# Clone and set up Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Install WebUI dependencies
cd webui && pnpm install && cd ..

# Start the full dev stack (backend + frontend)
python scripts/dev.py dev

# Start backend only
python scripts/dev.py backend

# Start WebUI dev server only
python scripts/dev.py webui-dev

# Build WebUI for production
python scripts/dev.py webui-build
```

After editable install, you can also use the CLI directly:

```bash
sentinelflow dev
sentinelflow backend
```

### Environment Configuration

The preferred way to configure SentinelFlow is through the **WebUI Settings panel** — all settings are persisted to `.sentinelflow/runtime.json` without requiring a server restart.

Alternatively, copy `.env.example` to `.env` for environment-level defaults:

```bash
cp .env.example .env
```

Key environment variables (all prefixed with `SENTINELFLOW_`):

```ini
# LLM Configuration (OpenAI-compatible)
SENTINELFLOW_LLM_API_KEY=sk-...
SENTINELFLOW_LLM_API_BASE_URL=https://api.openai.com/v1
SENTINELFLOW_LLM_MODEL=gpt-4o

# Alert Source
SENTINELFLOW_ALERT_SOURCE_ENABLED=false
SENTINELFLOW_ALERT_SOURCE_TYPE=api          # "api" or "script"
SENTINELFLOW_ALERT_SOURCE_URL=https://your-siem/api/alerts
SENTINELFLOW_POLL_INTERVAL_SECONDS=60

# Auto-execution
SENTINELFLOW_AUTO_EXECUTE_ENABLED=false

# Runtime
SENTINELFLOW_AGENT_ENABLED=true
```

### Tech Stack

**Backend**: Python 3.11 · FastAPI · uvicorn · LangGraph · LangChain · Pydantic v2 · python-dotenv · SQLite

**Frontend**: React 18 · TypeScript · Vite · TailwindCSS · react-hook-form

**AI Runtime**: LangGraph (StateGraph + ToolNode) · LangChain Core · langchain-openai

</details>

## Quick Start

### 1. Install Python Dependencies

```bash
# Linux/Mac
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Windows CMD
python -m venv .venv
.venv\Scripts\activate.bat
pip install -e ".[dev]"
```

### 2. Install WebUI Dependencies

```bash
cd webui
pnpm install
cd ..
```

### 3. Start the Full Stack

```bash
python scripts/dev.py dev
```

This starts:
- **Backend API** on `http://127.0.0.1:8001`
- **WebUI** on `http://127.0.0.1:5173`

### 4. Configure via WebUI

Open the WebUI and navigate to **Settings**. Configure your LLM endpoint and connect your alert source — all settings are persisted immediately without a restart.

Alternatively, create a `.env` file for environment-level defaults:

```bash
cp .env.example .env
# Edit .env with your SENTINELFLOW_LLM_API_KEY, SENTINELFLOW_LLM_API_BASE_URL, etc.
```

### 5. Add Your First Skill (Optional)

Create a new directory under `.sentinelflow/plugins/skills/` with a `SKILL.md`, or use the **Skill Management** panel in the WebUI to create one directly:

```markdown
---
name: get-ip-info
description: Query IP geolocation and threat intelligence for a given IP address
type: hybrid
mode: subprocess
entry: main.py
execute_policy:
  enabled: true
  approval_required: false
  audit: true
---

# get-ip-info

Query IP reputation, ASN, and geolocation using external threat intel APIs.

## Input

- `ip`: The IP address to look up

## Output

Returns a JSON object with `country`, `asn`, `reputation`, `is_malicious`.
```

The agent will automatically discover and invoke this skill when appropriate.

## FAQ

<details>
<summary><strong>What LLM providers does SentinelFlow support?</strong></summary>

SentinelFlow uses an OpenAI-compatible API interface (`langchain-openai`). Any provider that supports the OpenAI Chat Completions API format works — including OpenAI, Anthropic (via proxy), DeepSeek, Qwen, local models via Ollama/LM Studio, and API relay services.

Configure the endpoint in the WebUI Settings or via environment variables:
```ini
SENTINELFLOW_LLM_API_BASE_URL=https://your-provider/v1
SENTINELFLOW_LLM_API_KEY=your-key
SENTINELFLOW_LLM_MODEL=model-name
```

</details>

<details>
<summary><strong>What alert source types are supported?</strong></summary>

SentinelFlow supports two alert source modes, configurable from the Settings panel:

- **API mode** (`api`): Polls any REST/HTTP endpoint. Supports GET/POST, custom headers, query parameters, and request body. Ideal for SIEM/SOAR platforms with a REST API.
- **Script mode** (`script`): Runs a Python script you write directly in the UI. The script should print a JSON object to stdout containing `count` and `alerts`. Use this for custom data sources, local log files, or any integration that doesn't expose a REST endpoint.

</details>

<details>
<summary><strong>How does the AI parser generation work?</strong></summary>

Paste a sample alert JSON payload in the Settings panel and click **Generate Parser**. SentinelFlow sends the sample to your configured LLM, which returns a `field_mapping` rule that maps your schema's fields to SentinelFlow's canonical alert fields (`eventIds`, `alert_name`, `sip`, `dip`, etc.). A live preview shows how the rule would parse your sample. If the LLM call fails or is unavailable, a heuristic fallback rule is generated instead.

</details>

<details>
<summary><strong>How do I define a Worker Sub-Agent?</strong></summary>

Create a directory under `.sentinelflow/plugins/agents/` with an `agent.yaml` and optional prompt files, or use the **Agent Management** panel in the WebUI:

```yaml
# agent.yaml
name: ip-enrichment-worker
description: Specialized worker for IP enrichment and threat intel queries
role: worker
enabled: true
exec_skill_allowlist:
  - get-ip-info
  - virustotal-lookup
worker_max_steps: 3
```

The Primary Agent will automatically discover and delegate to this worker when appropriate.

</details>

<details>
<summary><strong>How does the Primary Agent decide to use a Worker?</strong></summary>

The Primary Agent (Supervisor) is bound with all available Worker Sub-Graphs as tools via LangGraph's `ToolNode`. On each reasoning step, the LLM decides whether to call a worker tool (sequentially or in parallel), invoke a preset workflow, or finish. The `worker_max_steps` setting caps the total number of delegation steps to prevent runaway orchestration.

</details>

<details>
<summary><strong>What is auto-execution mode?</strong></summary>

When enabled (via the Settings panel or `SENTINELFLOW_AUTO_EXECUTE_ENABLED=true`), SentinelFlow runs a background asyncio loop that continuously picks up `queued` tasks and executes them through the agent pipeline — without requiring any manual intervention. You can stop it at any time from the UI.

</details>

<details>
<summary><strong>Can I run SentinelFlow without an LLM API key?</strong></summary>

The WebUI and alert ingestion pipeline work without an LLM key. However, the AI agent features (multi-agent orchestration, skill invocation, LLM-based triage, parser generation) require a configured LLM endpoint. The `TriageService` provides rule-based fallback disposition for alerts when the agent is not configured.

</details>

<details>
<summary><strong>Where is project state stored?</strong></summary>

- **Agent definitions**: `.sentinelflow/plugins/agents/`
- **Skills**: `.sentinelflow/plugins/skills/`
- **Workflows**: `.sentinelflow/plugins/workflows/`
- **Runtime config** (persisted from WebUI): `.sentinelflow/runtime.json`
- **Task queue**: `.sentinelflow/sys_queue.db` (SQLite)
- **Environment defaults**: `.env` at project root (optional)

</details>

<details>
<summary><strong>How do I define a fixed multi-step Agent Workflow?</strong></summary>

Create a `workflow.json` file under `.sentinelflow/plugins/workflows/<workflow-id>/`, or use the **Workflow Management** panel in the WebUI. The Primary Agent uses structured LLM reasoning to select the best workflow for incoming alerts, or falls back to free ReAct if no workflow matches.

```json
{
  "id": "phishing-triage-v1",
  "name": "Phishing Alert Triage Workflow",
  "description": "Standard phishing alert triage with URL analysis and sender verification",
  "enabled": true,
  "scenarios": ["phishing", "suspicious_email"],
  "selection_keywords": ["phishing", "malicious_url", "suspicious_sender"],
  "steps": [
    { "agent": "url-analysis-worker", "name": "URL Analysis", "task_prompt": "Analyze the URLs in this alert for malicious indicators." },
    { "agent": "sender-reputation-worker", "name": "Sender Check", "task_prompt": "Check the sender reputation and domain age." },
    { "agent": "closure-worker", "name": "Close Alert", "task_prompt": "Based on the above findings, close the alert with appropriate disposition." }
  ]
}
```

</details>

## Documentation

For detailed guides on each feature, see the planned **[User Manual](docs/user-manual/en/README.md)** — covering agent configuration, skill development, workflow authoring, API reference, and deployment.

> 📝 **Note**: Full documentation is under active development. Contributions welcome!

## Contributing

Issues and suggestions are welcome!

Before submitting PRs, please ensure:

- Python: `pytest runtime/tests/` passes
- No `PYTHONPATH`-based hacks; use proper package imports
- New skills belong in `examples/skills/`, not mixed into `runtime/`
- New agent examples belong in `examples/agents/`

For new features, please open an Issue for discussion before submitting a PR.

## License

MIT License © SentinelFlow contributors

## Contact

- 📧 Email: ch1nfo@foxmail.com

---

<div align="center">

**⭐ If this project is helpful to you, please give it a Star! ⭐**

</div>