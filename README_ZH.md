<div align="center">

# SentinelFlow

### AI 驱动的安全运营平台 — 多 Agent SOC 自动化分析引擎

[![版本](https://img.shields.io/badge/版本-0.3.0-blue.svg)](https://github.com/Ch1nfo/SentinelFlow/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![许可证](https://img.shields.io/badge/许可证-MIT-green.svg)](LICENSE)
[![平台](https://img.shields.io/badge/平台-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#)
[![基于 LangGraph](https://img.shields.io/badge/基于-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)

[English](README.md) | 中文

</div>

---

## 为什么选择 SentinelFlow？

现代安全运营中心（SOC）每天要面对海量告警——大多数团队需要花费数小时进行研判，而这些工作本可以在秒级完成。现有的 SIEM 平台提供基于规则的关联分析，但缺乏处理新型威胁或复杂多步骤调查所需的上下文推理能力。

**SentinelFlow** 是一个全栈 SOC 自动化平台，将 **基于 LangGraph 的多 Agent 编排运行时**与**面向运营协同的 React WebUI** 深度结合。不同于固化的剧本，你将拥有一套灵活、可扩展的 Agent 体系——主 Agent（Supervisor）统一调度各专项子 Agent（Worker），每个子 Agent 均可装配可热插拔的 Skill，实现外部 API 调用、情报富化脚本、工单闭合等任意安全运营动作。

- **多 Agent 编排** — 基于 LangGraph 的 Supervisor + Worker SubGraph 模式，每个 Worker 是以 `@tool` 形式封装的独立 ReAct SubGraph
- **可插拔 Skill 系统** — 在 skills 目录下放入 `SKILL.md` + `main.py` 即可，Agent 自动发现并调用，支持细粒度的按 Agent 权限控制
- **双入口处理** — 同时接受原始安全告警（SIEM/SOAR 的 JSON 告警）和 WebUI 聊天界面的自由文本人工指令
- **Agent Workflow 引擎** — 定义高频场景的固定多步骤工作流，主 Agent 智能选择最优 Workflow 或回退到自由 ReAct
- **双模式告警接入** — 支持通过 HTTP API 轮询拉取告警，或运行自定义 Python 脚本接入任意告警源
- **AI 辅助解析规则生成** — 粘贴告警样本，大模型自动生成字段映射解析规则，并实时预览解析结果
- **持续自动执行** — 开启自动执行循环，无需人工干预即可自动处置队列中的告警任务
- **审批与断点恢复** — `approval_required` Skill 在对话与手动单告警场景下会暂停图执行，在 UI 中显示审批卡，并在批准/拒绝后从 checkpoint 恢复
- **细粒度权限策略** — 按 Agent 配置 Skill 白/黑名单、执行审批门控、审计日志和任务取消支持
- **全栈交付** — FastAPI 后端 + React/Vite 前端，统一开发入口，生产级项目布局

## 界面预览

|                        态势总览仪表盘                        |                        Agent 对话指挥台                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405225720016](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405225720053.png) | ![image-20260405231100920](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260406140803364.png) |

|                        告警工作台                        |                        Skill 管理面板                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405225903594](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405225903635.png)| ![image-20260405230107750](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230107788.png) |

|                        Agent 管理面板                         |                        Workflow 管理面板                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405230145352](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230145399.png) | ![image-20260405230315299](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230315341.png) |

## 功能特性

### 多 Agent 编排

- **Supervisor + Worker SubGraph** — 主 Agent 通过 LangGraph 的 `ToolNode` 将任务委托给子 Agent，每个子 Agent 以独立 ReAct SubGraph 编译后封装为 `@tool`
- **并行委派** — 主 Agent 可通过 `delegate_parallel` 同时将多个独立子任务分发给不同 Worker 并行执行
- **Agent Workflow 引擎** — 定义可复用的固定多步骤工作流，用于高频场景；主 Agent 通过 LLM 推理选择最优工作流
- **取消与步骤上限** — 所有编排图均尊重 `cancel_event` 线程标志；`worker_max_steps` 限制编排递归深度，防止失控

### 可插拔 Skill 系统

- **基于 SKILL.md 的自动发现** — 每个 Skill 是一个目录，包含带 YAML 头部的 `SKILL.md`（供 Agent 阅读）和可选的 `main.py` 执行入口
- **两种 Skill 类型**：`doc`（纯知识型，供 Agent 阅读）和 `hybrid`（文档 + 可执行子进程）
- **按 Agent 权限控制** — `doc_skill_allowlist`、`exec_skill_allowlist`、每个 Skill 的 `approval_required` 标志；`approval_required` 仅对对话与手动单告警生效，且每次执行都需要单独审批，自动执行 / 自动重试 / 调试会绕过审批
- **子进程隔离执行** — Skill 在隔离子进程中运行，结构化 JSON 输入/输出，内置审计日志
- **WebUI 内 Skill 管理** — 直接在配置中心创建、编辑、删除 Skill，并支持在线调试执行

### 告警接入流水线

- **双模式告警源** — `api` 模式轮询任意 REST 端点（支持自定义 Method、Header、Query、Body）；`script` 模式运行自定义 Python 脚本，读取其 stdout 作为告警数据，适用于无 API 的自定义数据源
- **AI 辅助解析规则生成** — 粘贴原始告警样本，大模型自动生成 `field_mapping` 解析规则并实时预览；大模型不可用时自动降级为启发式规则推断
- **灵活字段映射** — 基于点路径表达式，将任意 JSON 结构映射到 SentinelFlow 标准字段（`eventIds`、`alert_name`、`sip`、`dip`、`alert_time` 等）
- **去重与幂等** — SQLite 支撑的去重存储，防止活跃告警被重复入队
- **轮询调度器** — 可配置轮询间隔；支持在 UI 中手动触发立即轮询
- **容错与重试** — 失败任务可手动重试，或在下次轮询时自动重新处理

### 任务队列与执行

- **SQLite 任务队列持久化** — 默认将告警处置任务与审批记录持久化到 `runtime/.sentinelflow/sys_queue.db`，进程重启后自动恢复
- **持续自动执行** — 开启自动执行循环后，无需人工干预即可自动顺序处理所有排队任务
- **手动单任务触发** — 随时从告警工作台触发单条任务的 Agent 处置
- **完整任务生命周期** — `queued → running → awaiting_approval / pending_closure / succeeded / failed / completed`；手动审批可在不丢失断点状态的情况下暂停任务
- **结构化执行链路** — 每个任务存储完整 `execution_trace`，涵盖告警接收、Agent 研判、Skill 调用、结单结果和最终状态

### 安全运营 WebUI

- **告警工作台** — 浏览、过滤告警任务，手动触发 Agent 处置，查看完整执行链路追踪
- **Agent 对话** — 自由文本指令界面，向主 Agent 发送人工指令，支持流式响应输出
- **配置中心** — 统一配置页面，涵盖 LLM 凭据、告警源连接、解析规则、轮询参数、自动执行开关——所有配置实时持久化，无需重启服务
- **Skill 管理** — 创建、查看、编辑、删除 Skill；支持携带自定义参数进行在线调试执行
- **Agent 管理** — 配置主 Agent 和子 Agent：提示词（默认/告警/指令/汇总 四种变体）、LLM 参数覆盖、Skill 权限
- **Workflow 管理** — 创建、编辑 Agent Workflow；支持从 UI 直接发起测试运行

### 平台与架构

- **FastAPI 后端** — 异步 Python 运行时，结构化 JSON API，uvicorn 服务器
- **React + Vite 前端** — TypeScript、TailwindCSS、组件化架构
- **统一开发入口** — `python scripts/dev.py dev` 一条命令启动全部服务
- **源码优先的本地布局** — 运行时代码位于 `runtime/`，WebUI 位于 `webui/`，辅助脚本位于 `scripts/`，本地插件与运行时状态默认保存在 `runtime/.sentinelflow/`

## 架构总览

<details>
<summary><strong>系统架构图</strong></summary>

```
┌─────────────────────────────────────────────────────────────────┐
│                   React WebUI (Vite + TS)                       │
│  ┌──────────────┐  ┌─────────────────┐  ┌───────────────────┐   │
│  │  告警管理面板  │  │  Agent 对话界面  │  │    配置管理中心    │   │
│  └──────────────┘  └─────────────────┘  └───────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │  REST API（FastAPI）
┌──────────────────────────▼──────────────────────────────────────┐
│              SentinelFlow 运行时（Python / FastAPI）             │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                   多 Agent 编排器                           │  │
│  │   ┌──────────────────────────────────────────────────┐    │  │
│  │   │  主 Agent（Supervisor）                           │    │  │
│  │   │  LangGraph StateGraph + ToolNode                  │    │  │
│  │   │    ↓ 顺序 / 并行委派子 Agent                      │    │  │
│  │   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │    │  │
│  │   │  │  子 Agent A│  │  子 Agent B│  │  子 Agent C│  │    │  │
│  │   │  │ ReAct Sub- │  │ ReAct Sub- │  │ ReAct Sub- │  │    │  │
│  │   │  │   Graph    │  │   Graph    │  │   Graph    │  │    │  │
│  │   │  └────────────┘  └────────────┘  └────────────┘  │    │  │
│  │   └──────────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                      Skill 运行时                           │  │
│  │   loader → executor → 子进程隔离 → 审计日志                 │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              告警接入 & SQLite 任务队列                      │  │
│  │  API/脚本轮询 → 解析器 → 去重 → SQLite 任务队列              │  │
│  │  自动执行循环 → 任务执行器 → Agent / Workflow                 │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**核心设计模式**

- **Supervisor + Worker SubGraph** — 子 Agent 以编译后的 ReAct SubGraph 形式封装为 `@tool`，只有 `final_response` 作为 `ToolMessage` 返回给主 Agent
- **SKILL.md 自动发现** — Skill 是文件系统插件；无需修改代码即可添加新能力
- **双入口类型** — `alert`（来自 SIEM 的 JSON 告警）和 `conversation`（人工指令）；均通过同一 Agent 运行时路由
- **SQLite 任务持久化** — 告警任务跨进程重启持久化；原子状态转换防止重复执行
- **原子化结果序列化** — 所有执行结果均经 `_serialize_alert_result` 统一处理，产出结构一致的执行链路追踪

**核心组件**

- **`SentinelFlowAgentService`** — 顶层服务，负责路由到编排器或单 Agent 图，并序列化执行结果
- **`build_orchestrator_graph()`** — 编译 Supervisor + Worker 多 Agent LangGraph
- **`build_agent_graph()`** — 构建单 Agent ReAct SubGraph（同时用于子 Agent 和独立 Agent）
- **`AlertDispatchService`** — SQLite 支撑的任务队列；负责任务创建、去重、状态转换和闭合
- **`AlertAutoExecutionService`** — 基于 asyncio 的持续自动执行循环，无需人工干预处理排队任务
- **`AlertParserGenerator`** — 大模型辅助 + 启发式 JSON 告警字段映射规则生成器
- **`SentinelFlowSkillRuntime`** — 管理 Skill 生命周期，将 Skill 适配为 LangChain 工具供 Agent 使用
- **`AgentWorkflowRegistry`** — 列举和解析固定多步骤 Agent Workflow 定义

</details>

<details>
<summary><strong>项目结构</strong></summary>

```
.
├── pyproject.toml                      # Python 包元数据与 CLI 入口
├── scripts/
│   ├── dev.py                          # 统一本地开发入口
│   └── serve_webui.py                  # 生产环境 WebUI 静态文件服务
├── runtime/
│   ├── .sentinelflow/                  # 本地插件、runtime.json、SQLite 队列（运行时生成）
│   └── sentinelflow/
│       ├── agent/
│       │   ├── service.py              # 顶层 Agent 服务（编排核心逻辑）
│       │   ├── orchestrator_graph.py   # Supervisor + Worker SubGraph 构建器
│       │   ├── graph.py                # 单 Agent ReAct 图构建器
│       │   ├── registry.py             # Agent 定义加载器（agent.yaml）
│       │   ├── prompts.py              # 系统提示词与附录模板
│       │   ├── policy.py               # 按 Agent Skill 权限解析器
│       │   ├── nodes.py                # LangGraph 节点实现
│       │   ├── tools.py                # Agent 侧工具定义
│       │   └── state.py                # Agent 图状态 Schema
│       ├── skills/
│       │   ├── loader.py               # SKILL.md 发现与校验
│       │   ├── executor.py             # Skill 子进程执行器
│       │   ├── adapters.py             # Skill → LangChain 工具适配器
│       │   └── models.py               # Skill 数据模型
│       ├── alerts/
│       │   ├── client.py               # 告警源 HTTP / 脚本客户端
│       │   ├── poller.py               # 定时轮询服务
│       │   ├── parser_runtime.py       # 字段映射解析引擎
│       │   ├── parser_generator.py     # 大模型 + 启发式解析规则生成器
│       │   └── dedup.py                # 告警去重存储
│       ├── services/
│       │   ├── dispatch_service.py     # SQLite 任务队列与生命周期管理
│       │   ├── task_runner_service.py  # 任务执行编排
│       │   ├── auto_execution_service.py # 持续自动执行循环
│       │   ├── skill_approval_service.py # Skill 审批记录与 checkpoint 持久化
│       │   ├── triage_service.py       # 基于规则的处置结论兜底
│       │   └── audit_service.py        # 审计事件日志
│       ├── workflows/                  # Agent Workflow 注册表与执行器
│       ├── api/                        # FastAPI 路由处理器
│       ├── config/                     # 运行时配置加载器（.env + 持久化 JSON）
│       └── domain/                     # 共享枚举、模型、错误类型
│   └── tests/                          # Runtime 回归测试
├── webui/
│   └── src/
│       ├── components/                 # React UI 组件
│       ├── pages/                      # 页面级视图
│       ├── api/                        # API 客户端（fetch 封装）
│       ├── hooks/                      # 自定义 React Hooks
│       └── styles/                     # 全局样式与 Tailwind 配置
```

</details>

<details>
<summary><strong>开发指南</strong></summary>

### 环境要求

- Python 3.11+
- Node.js 18+ / pnpm 8+
- （可选）兼容 OpenAI ChatCompletions 格式的 LLM API Key

### 开发命令

```bash
# 克隆并初始化 Python 环境
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 安装 WebUI 依赖
cd webui && pnpm install && cd ..

# 启动完整开发环境（后端 + 前端）
python scripts/dev.py dev

# 仅启动后端
python scripts/dev.py backend

# 仅启动 WebUI 开发服务器
python scripts/dev.py webui-dev

# 构建生产版 WebUI
python scripts/dev.py webui-build

# 启动构建后的 WebUI 静态服务
python scripts/dev.py webui-serve
```

通过 editable install 安装后，也可直接使用 CLI：

```bash
sentinelflow dev
sentinelflow backend
```

### 配置方式

**推荐方式**：直接在 WebUI 的 **配置中心** 填写配置，所有参数默认实时持久化到 `runtime/.sentinelflow/runtime.json`，无需重启服务。

**备选方式**：将 `.env.example` 复制为 `.env` 并填写环境变量（所有参数均以 `SENTINELFLOW_` 为前缀）：

```bash
cp .env.example .env
```

核心环境变量：

```ini
# LLM 配置（OpenAI 兼容格式）
SENTINELFLOW_LLM_API_KEY=sk-...
SENTINELFLOW_LLM_API_BASE_URL=https://api.openai.com/v1
SENTINELFLOW_LLM_MODEL=gpt-4o

# 告警源
SENTINELFLOW_ALERT_SOURCE_ENABLED=false
SENTINELFLOW_ALERT_SOURCE_TYPE=api          # "api" 或 "script"
SENTINELFLOW_ALERT_SOURCE_URL=https://your-siem/api/alerts
SENTINELFLOW_POLL_INTERVAL_SECONDS=60

# 自动执行
SENTINELFLOW_AUTO_EXECUTE_ENABLED=false

# 运行时
SENTINELFLOW_AGENT_ENABLED=true
```

### 技术栈

**后端**：Python 3.11 · FastAPI · uvicorn · LangGraph · LangChain · Pydantic v2 · python-dotenv · SQLite

**前端**：React 18 · TypeScript · Vite · TailwindCSS · react-hook-form

**AI 运行时**：LangGraph（StateGraph + ToolNode）· LangChain Core · langchain-openai

</details>

## 快速开始

### 1. 安装 Python 依赖

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

### 2. 安装 WebUI 依赖

```bash
cd webui
pnpm install
cd ..
```

### 3. 启动全栈开发环境

```bash
python scripts/dev.py dev
```

默认启动：
- **后端 API**：`http://127.0.0.1:8001`
- **WebUI**：`http://127.0.0.1:5173`

如果想本地模拟生产态预览，可先构建前端再启动静态服务：

```bash
python scripts/dev.py webui-build
python scripts/dev.py webui-serve
```

### 4. 通过 WebUI 完成配置

打开 WebUI，进入 **配置中心**，配置 LLM 接入地址、告警源连接参数等——所有配置实时生效，无需重启服务。

也可以通过 `.env` 文件设置环境变量作为默认值：

```bash
cp .env.example .env
# 编辑 .env，填写 SENTINELFLOW_LLM_API_KEY、SENTINELFLOW_LLM_API_BASE_URL 等
```

### 5. 添加你的第一个 Skill（可选）

在 `runtime/.sentinelflow/plugins/skills/`（默认源码树工作区）下创建目录并添加 `SKILL.md`，或直接在 WebUI 的 **Skill 管理** 面板中在线创建：

```markdown
---
name: get-ip-info
description: 查询指定 IP 的地理位置与威胁情报
type: hybrid
mode: subprocess
entry: main.py
execute_policy:
  enabled: true
  approval_required: false
  audit: true
---

# get-ip-info

通过外部威胁情报 API 查询 IP 信誉、ASN 和地理位置信息。

## 输入

- `ip`：待查询的 IP 地址

## 输出

返回包含 `country`、`asn`、`reputation`、`is_malicious` 字段的 JSON 对象。
```

Agent 将自动发现并在适当时调用此 Skill。

`approval_required` 仅对 **Agent 对话** 与 **手动单告警 / 手动重试** 两类入口生效；在这两类入口下，每次实际执行都需要重新审批。开启自动执行时，即使配置了 `approval_required: true`，Skill 也会直接执行。

## 常见问题

<details>
<summary><strong>SentinelFlow 支持哪些 LLM 服务商？</strong></summary>

SentinelFlow 使用 OpenAI 兼容 API 接口（`langchain-openai`）。所有支持 OpenAI Chat Completions API 格式的服务商均可接入，包括 OpenAI、Anthropic（通过代理）、DeepSeek、通义千问、本地模型（Ollama/LM Studio）以及各类 API 中转服务。

在 WebUI 配置中心填写，或通过环境变量配置：
```ini
SENTINELFLOW_LLM_API_BASE_URL=https://your-provider/v1
SENTINELFLOW_LLM_API_KEY=your-key
SENTINELFLOW_LLM_MODEL=model-name
```

</details>

<details>
<summary><strong>支持哪些告警源接入方式？</strong></summary>

SentinelFlow 支持两种告警源模式，可在配置中心切换：

- **API 模式**（`api`）：轮询任意 REST/HTTP 端点，支持 GET/POST，可自定义 Header、Query 参数、请求体，适用于提供 REST API 的 SIEM/SOAR 平台。
- **脚本模式**（`script`）：直接在 UI 中编写 Python 脚本，脚本将告警数据以 JSON 格式打印到 stdout（需包含 `count` 和 `alerts` 字段）。适用于无 REST API 的自定义数据源、本地日志文件或任何特殊集成场景。

</details>

<details>
<summary><strong>AI 解析规则生成是如何工作的？</strong></summary>

在配置中心粘贴一段原始告警 JSON 样本，点击 **生成解析规则**。SentinelFlow 将样本发送给你配置的大模型，模型返回一份 `field_mapping` 规则，将你的字段映射到 SentinelFlow 标准字段（`eventIds`、`alert_name`、`sip`、`dip` 等）。实时预览展示规则对样本的解析效果。若大模型调用失败或未配置，将自动降级为基于样本结构的启发式规则推断。

</details>

<details>
<summary><strong>如何定义一个子 Agent（Worker）？</strong></summary>

在 `runtime/.sentinelflow/plugins/agents/`（默认源码树工作区）下创建目录，包含 `agent.yaml` 和可选的提示词文件，或直接使用 WebUI 的 **Agent 管理** 面板：

```yaml
# agent.yaml
name: ip-enrichment-worker
description: 专注于 IP 情报富化与威胁查询的专项子 Agent
role: worker
enabled: true
exec_skill_allowlist:
  - get-ip-info
  - virustotal-lookup
worker_max_steps: 3
```

主 Agent 将自动发现并在适当时委托给该子 Agent。

</details>

<details>
<summary><strong>主 Agent 如何决定是否使用子 Agent？</strong></summary>

主 Agent（Supervisor）通过 LangGraph 的 `ToolNode` 将所有可用子 Agent SubGraph 绑定为工具。在每个推理步骤，LLM 自主决策：顺序或并行调用子 Agent 工具、调用预设 Workflow，或直接结束编排返回结论。`worker_max_steps` 参数限制委托总次数，防止编排失控。

</details>

<details>
<summary><strong>自动执行模式是什么？</strong></summary>

开启后（通过配置中心或 `SENTINELFLOW_AUTO_EXECUTE_ENABLED=true`），SentinelFlow 启动一个 asyncio 后台循环，持续拾取 `queued` 状态的任务并通过 Agent 流水线自动处置——无需任何人工干预。可随时在 UI 中停止。

</details>

<details>
<summary><strong>没有 LLM API Key 也能运行 SentinelFlow 吗？</strong></summary>

WebUI 和告警接入流水线不依赖 LLM Key 即可正常运行。但 AI Agent 功能（多 Agent 编排、Skill 调用、LLM 辅助研判、解析规则生成）需要配置 LLM 端点。当 Agent 未配置时，`TriageService` 会提供基于规则的兜底处置结论。

</details>

<details>
<summary><strong>项目数据存储在哪里？</strong></summary>

- **Agent 定义**：默认位于 `runtime/.sentinelflow/plugins/agents/`
- **Skill 插件**：默认位于 `runtime/.sentinelflow/plugins/skills/`
- **Workflow 定义**：默认位于 `runtime/.sentinelflow/plugins/workflows/`
- **运行时配置**（WebUI 持久化）：默认位于 `runtime/.sentinelflow/runtime.json`
- **任务队列 / 审批记录**：`runtime/.sentinelflow/sys_queue.db`（SQLite）
- **环境变量默认值**：项目根目录 `.env`（可选）

如果 SentinelFlow 运行在另一个已经提供项目根 `.sentinelflow/` 的平台工作区中，运行时会优先使用那个外部插件根目录；在普通源码仓库下，实际生效的本地工作区是 `runtime/.sentinelflow/`。

</details>

<details>
<summary><strong>如何定义固定多步骤 Agent Workflow？</strong></summary>

在 `runtime/.sentinelflow/plugins/workflows/<workflow-id>/`（默认源码树工作区）下创建 `workflow.json`，或使用 WebUI 的 **Workflow 管理** 面板。主 Agent 通过结构化 LLM 推理为来袭告警选择最优工作流，若无匹配则回退到自由 ReAct。

```json
{
  "id": "phishing-triage-v1",
  "name": "钓鱼告警研判工作流",
  "description": "标准钓鱼告警研判流程，含 URL 分析和发件人核查",
  "enabled": true,
  "scenarios": ["phishing", "suspicious_email"],
  "selection_keywords": ["钓鱼", "恶意链接", "可疑发件人"],
  "steps": [
    { "agent": "url-analysis-worker", "name": "URL 分析", "task_prompt": "分析告警中的 URL，识别恶意指标。" },
    { "agent": "sender-reputation-worker", "name": "发件人核查", "task_prompt": "核查发件人信誉和域名年龄。" },
    { "agent": "closure-worker", "name": "结单", "task_prompt": "根据以上研判结果，完成告警结单处置。" }
  ]
}
```

</details>

## 文档

各功能的详细使用文档，请参阅规划中的 **[用户手册](docs/user-manual/zh/README.md)** — 涵盖 Agent 配置、Skill 开发、Workflow 编写、API 参考以及部署指南。

> 📝 **注意**：完整文档正在积极建设中，欢迎社区贡献！

## 贡献

欢迎提交 Issue 反馈问题和建议！

提交 PR 前请确保：

- Python：`python -m pytest runtime/tests/` 全部通过
- Runtime 导入保持 `sentinelflow.*` 包路径形式
- 用户创建的 Skill、Agent 与 Workflow 应放在本地 `.sentinelflow/plugins/` 工作区，而不是写进包源码模块

新功能开发前，建议先开 Issue 讨论方案，不适合项目定位的功能性 PR 可能被关闭。

## 许可证

MIT License © SentinelFlow 贡献者

## 联系方式

- 📧 Email: ch1nfo@foxmail.com

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个 Star！⭐**

</div>
