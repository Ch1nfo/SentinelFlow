<div align="center">

# SentinelFlow

### AI-Powered Security Operations Platform — Multi-Agent SOC Automation

[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/your-org/sentinelflow/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#)
[![Built with LangGraph](https://img.shields.io/badge/built%20with-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)

[English](README.md) | [中文](README_ZH.md)

</div>

---

## Why SentinelFlow?

Modern Security Operations Centers face an overwhelming volume of alerts — most teams spend hours triaging events that could be handled in seconds with proper automation. Existing SIEM platforms offer rules-based correlation, but lack the contextual reasoning needed to handle novel threats or complex multi-step investigations.

**SentinelFlow** is a full-stack SOC automation platform that combines a **LangGraph-powered multi-agent orchestration runtime** with a **React WebUI** for alert management. Instead of rigid playbooks, you get a flexible, extensible agent system where a Primary Supervisor Agent coordinates specialized Worker Sub-Agents — each equipped with pluggable Skills that can call external APIs, run enrichment scripts, close tickets, and more.

- **Multi-Agent Orchestration** — Supervisor + Worker SubGraph pattern via LangGraph; each worker is an isolated ReAct agent wrapped as a tool
- **Pluggable Skill System** — Drop a `SKILL.md` + `main.py` into the skills directory; agents discover and invoke them automatically, with granular per-agent permission control
- **Dual Entry Points** — Accepts both raw security alerts (JSON payloads from SIEM/SOAR) and free-form human commands via the WebUI chat interface
- **Agent Workflow Engine** — Define fixed multi-step `agent.yaml` workflows for high-frequency scenarios; the Primary Agent selects the best workflow or falls back to free ReAct
- **Fine-Grained Policy** — Per-agent skill allowlists/denylists, execution approval gates, audit logging, and cancellation support
- **Full-Stack** — FastAPI backend + React/Vite frontend, unified dev entrypoint, production-ready project layout

## Screenshots

|                    Alert Triage Dashboard                    |                   Agent Conversation Panel                   |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405225903594](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260406140931256.png) | ![image-20260405231100920](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260406140908416.png) |

## Features

### Multi-Agent Orchestration

- **Supervisor + Worker SubGraph** — Primary Agent uses LangGraph's `ToolNode` to delegate tasks to Worker Sub-Agents, each compiled as an isolated ReAct SubGraph wrapped as a `@tool`
- **Free ReAct & Structured Planner** — Primary Agent can self-handle, delegate to a worker, invoke a preset workflow, or respond directly depending on task complexity
- **Agent Workflow Engine** — Define reusable `agent.yaml` workflows for common scenarios (e.g., phishing triage, IP enrichment + block); Primary Agent selects the best workflow via LLM reasoning
- **Cancellation & Step Limits** — All graphs respect a `cancel_event` threading flag; `worker_max_steps` caps orchestration recursion depth

### Pluggable Skill System

- **SKILL.md-based discovery** — Each skill is a directory with a `SKILL.md` (YAML frontmatter + documentation body) and an optional `main.py` entrypoint
- **Two skill types**: `doc` (knowledge-only, read by agent) and `hybrid` (doc + executable subprocess)
- **Per-agent permission control** — `doc_skill_allowlist`, `exec_skill_allowlist`, `approval_required` flags per skill
- **Subprocess execution** — Skills run in isolated subprocesses with structured JSON I/O; audit logging built in

### Alert Processing Pipeline

- **Triage Service** — Rule-based and LLM-assisted disposition inference (true-positive / false-positive / escalate)
- **Evidence extraction** — Agent automatically extracts structured evidence from final response text
- **Closure integration** — Skills can submit closure fields (memo, detailMsg, status) back to upstream SIEM/SOAR
- **Enrichment Actions** — IP info, threat intel, host context, and more via pluggable skills

### Security Operations WebUI

- **Alert Management** — Browse, filter, and triage alerts; view agent reasoning traces
- **Agent Chat** — Free-form command interface; send human instructions directly to the Primary Agent
- **Agent Configuration** — Manage agent definitions, prompts, skill permissions, and LLM settings
- **Skill Management** — Browse installed skills, view SKILL.md documentation, toggle per-agent access

### Platform & Architecture

- **FastAPI backend** — Async Python runtime with structured JSON API; uvicorn server
- **React + Vite frontend** — TypeScript, TailwindCSS, component-based architecture
- **Unified dev entrypoint** — `python scripts/dev.py dev` starts the full stack in one command
- **Clean project layout** — Strict separation of `runtime/`, `webui/`, `examples/`, `scripts/`; no `PYTHONPATH`-based startup

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
│  │   │         ↓ tool_calls (worker delegation)          │    │  │
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
└─────────────────────────────────────────────────────────────────┘
```

**Core Design Patterns**

- **Supervisor + Worker SubGraph** — Workers are compiled ReAct SubGraphs, wrapped as `@tool` functions; only `final_response` surfaces back to the Supervisor as a `ToolMessage`
- **SKILL.md discovery** — Skills are file-system plugins; no code changes needed to add new capabilities
- **Dual entry types** — `alert` (JSON from SIEM) and `conversation` (human command); both routed through the same agent runtime
- **Structured planner** — Optional `PlannerResult` Pydantic model for structured LLM output when strict routing is needed
- **Atomic result serialization** — All graph results go through `_serialize_graph_result` / `_serialize_alert_result` for consistent upstream API shape

**Key Components**

- **`SentinelFlowAgentService`** — Top-level service; routes to orchestrator or single-agent graph; serializes results
- **`build_orchestrator_graph()`** — Compiles the Supervisor + Worker multi-agent LangGraph
- **`build_agent_graph()`** — Builds a single-agent ReAct SubGraph (used for both workers and standalone agents)
- **`SentinelFlowSkillLoader`** — Discovers and validates skills from the plugin directory
- **`SentinelFlowSkillRuntime`** — Manages skill lifecycle; adapts skills as LangChain tools for agent use
- **`TriageService`** — Rule-based alert disposition inference as a fallback when the agent cannot determine a verdict
- **`AgentWorkflowRegistry`** — Lists and resolves `agent.yaml`-defined multi-step workflows

</details>

<details>
<summary><strong>Project Structure</strong></summary>

```
.
├── pyproject.toml                      # Python package & CLI metadata
├── scripts/
│   └── dev.py                          # Unified local dev entrypoint
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
│       ├── api/                        # FastAPI route handlers
│       ├── services/                   # Business logic (triage, etc.)
│       ├── workflows/                  # Agent workflow registry
│       ├── config/                     # Runtime config loader (.env)
│       ├── domain/                     # Shared enums, models, errors
│       └── alerts/                     # Alert ingestion & normalization
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
    ├── tools/                          # Example tool configs
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

Copy `.env.example` to `.env` and fill in your LLM credentials:

```bash
cp .env.example .env
```

Key settings:

```ini
# LLM Configuration (OpenAI-compatible)
LLM_API_KEY=sk-...
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# Runtime
AGENT_ENABLED=true
```

### Running Tests

```bash
# Run all Python tests
pytest runtime/tests/

# Run with verbose output
pytest runtime/tests/ -v
```

### Tech Stack

**Backend**: Python 3.11 · FastAPI · uvicorn · LangGraph · LangChain · Pydantic v2 · python-dotenv

**Frontend**: React 18 · TypeScript · Vite · TailwindCSS · react-hook-form

**AI Runtime**: LangGraph (StateGraph + ToolNode) · LangChain Core · langchain-openai

</details>

## Quick Start

### 1. Install Python Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Install WebUI Dependencies

```bash
cd webui
pnpm install
cd ..
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your LLM API key, base URL, and model name
```

### 4. Start the Full Stack

```bash
python scripts/dev.py dev
```

This starts:
- **Backend API** on `http://127.0.0.1:8001`
- **WebUI** on `http://127.0.0.1:5173`

### 5. Add Your First Skill (Optional)

Create a new directory under `.sentinelflow/plugins/skills/` (or `examples/skills/`) with a `SKILL.md`:

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

Configure the endpoint via `.env`:
```ini
LLM_API_BASE_URL=https://your-provider/v1
LLM_API_KEY=your-key
LLM_MODEL=model-name
```

</details>

<details>
<summary><strong>How do I define a Worker Sub-Agent?</strong></summary>

Create a directory under `.sentinelflow/plugins/agents/` with an `agent.yaml` and optional `prompt.md`:

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

The Primary Agent (Supervisor) is bound with all available Worker Sub-Graphs as tools via LangGraph's `ToolNode`. On each reasoning step, the LLM decides whether to call a worker tool, call another worker, or finish. The `worker_max_steps` setting caps the total number of delegation steps to prevent runaway orchestration.

</details>

<details>
<summary><strong>Can I run SentinelFlow without an LLM API key?</strong></summary>

The WebUI and alert ingestion pipeline work without an LLM key. However, the AI agent features (multi-agent orchestration, skill invocation, LLM-based triage) require a configured LLM endpoint. The `TriageService` provides rule-based fallback disposition for alerts when the agent is not configured.

</details>

<details>
<summary><strong>Where is project state stored?</strong></summary>

- **Agent definitions**: `.sentinelflow/plugins/agents/`
- **Skills**: `.sentinelflow/plugins/skills/`
- **Runtime config**: `.env` at project root
- **Generated runtime state**: excluded from version control (see `.gitignore`)

</details>

<details>
<summary><strong>How do I define a fixed multi-step Agent Workflow?</strong></summary>

Create a YAML file under `.sentinelflow/plugins/workflows/` (or `examples/workflows/`). The Primary Agent uses structured LLM reasoning to select the best workflow for incoming alerts, or falls back to free ReAct if no workflow matches.

```yaml
id: phishing-triage-v1
name: Phishing Alert Triage Workflow
description: Standard phishing alert triage with URL analysis and sender verification
enabled: true
scenarios:
  - phishing
  - suspicious_email
selection_keywords:
  - phishing
  - malicious_url
  - suspicious_sender
steps:
  - agent: url-analysis-worker
  - agent: sender-reputation-worker
  - agent: closure-worker
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

Apache License 2.0 © SentinelFlow contributors
