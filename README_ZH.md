<div align="center">

# SentinelFlow

### AI 驱动的安全运营平台 — 多 Agent SOC 自动化分析引擎

[![版本](https://img.shields.io/badge/版本-0.1.0-blue.svg)](https://github.com/your-org/sentinelflow/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![许可证](https://img.shields.io/badge/许可证-Apache%202.0-green.svg)](LICENSE)
[![平台](https://img.shields.io/badge/平台-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#)
[![基于 LangGraph](https://img.shields.io/badge/基于-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)

[English](README.md) | 中文

</div>

---

## 为什么选择 SentinelFlow？

现代安全运营中心（SOC）每天要面对海量告警——大多数团队需要花费数小时进行研判，而这些工作本可以在秒级完成。现有的 SIEM 平台提供基于规则的关联分析，但缺乏处理新型威胁或复杂多步骤调查所需的上下文推理能力。

**SentinelFlow** 是一个全栈 SOC 自动化平台，将 **基于 LangGraph 的多 Agent 编排运行时**与**告警管理 React WebUI** 深度结合。不同于固化的剧本，你将拥有一套灵活、可扩展的 Agent 体系——主 Agent（Supervisor）统一调度各专项子 Agent（Worker），每个子 Agent 均可装配可热插拔的 Skill，实现外部 API 调用、情报富化脚本、工单闭合等任意安全运营动作。

- **多 Agent 编排** — 基于 LangGraph 的 Supervisor + Worker SubGraph 模式，每个 Worker 是以 `@tool` 形式封装的独立 ReAct SubGraph
- **可插拔 Skill 系统** — 在 skills 目录下放入 `SKILL.md` + `main.py` 即可，Agent 自动发现并调用，支持细粒度的按 Agent 权限控制
- **双入口处理** — 同时接受原始安全告警（SIEM/SOAR 的 JSON 告警）和 WebUI 聊天界面的自由文本人工指令
- **Agent Workflow 引擎** — 用 `agent.yaml` 定义高频场景的固定多步骤工作流，主 Agent 智能选择最优 Workflow 或回退到自由 ReAct
- **细粒度权限策略** — 按 Agent 配置 Skill 白/黑名单、执行审批门控、审计日志和任务取消支持
- **全栈交付** — FastAPI 后端 + React/Vite 前端，统一开发入口，生产级项目布局

## 界面预览

|                        态势总览仪表盘                        |                        Agent 对话面板                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405225720016](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405225720053.png) | ![image-20260405231100920](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260406140803364.png) |

|                        告警工作台                        |                        Skills新建面板                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405225903594](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405225903635.png)| ![image-20260405230107750](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230107788.png) |

|                        子Agent新建面板                         |                        Agentsflow                        |
| :----------------------------------------------------------: | :----------------------------------------------------------: |
| ![image-20260405230145352](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230145399.png) | ![image-20260405230315299](https://raw.githubusercontent.com/Ch1nfo/picbed/main/img/20260405230315341.png) |

## 功能特性

### 多 Agent 编排

- **Supervisor + Worker SubGraph** — 主 Agent 通过 LangGraph 的 `ToolNode` 将任务委托给子 Agent，每个子 Agent 以独立 ReAct SubGraph 编译后封装为 `@tool`
- **自由 ReAct & 结构化 Planner** — 主 Agent 可根据任务复杂度自主选择：自行处理、委托子 Agent、调用预设 Workflow，或直接回复
- **Agent Workflow 引擎** — 定义可复用的 `agent.yaml` 工作流，用于高频场景（如钓鱼研判、IP 情报富化 + 封锁）；主 Agent 通过 LLM 推理选择最优工作流
- **取消与步骤上限** — 所有编排图均尊重 `cancel_event` 线程标志；`worker_max_steps` 限制编排递归深度，防止失控

### 可插拔 Skill 系统

- **基于 SKILL.md 的自动发现** — 每个 Skill 是一个目录，包含带 YAML 头部的 `SKILL.md`（供 Agent 阅读）和可选的 `main.py` 执行入口
- **两种 Skill 类型**：`doc`（纯知识型，供 Agent 阅读）和 `hybrid`（文档 + 可执行子进程）
- **按 Agent 权限控制** — `doc_skill_allowlist`、`exec_skill_allowlist`、每个 Skill 的 `approval_required` 标志
- **子进程隔离执行** — Skill 在隔离子进程中运行，结构化 JSON 输入/输出，内置审计日志

### 告警处理流水线

- **研判服务** — 基于规则和 LLM 辅助的处置结论推断（真阳性 / 误报 / 升级）
- **证据自动提取** — Agent 从最终响应文本中自动提取结构化证据字段
- **闭合集成** — Skill 可将闭合字段（memo、detailMsg、status）回传至上游 SIEM/SOAR
- **情报富化动作** — 通过可插拔 Skill 实现 IP 信息查询、威胁情报、主机上下文等

### 安全运营 WebUI

- **告警管理** — 浏览、过滤、研判告警；查看 Agent 推理链路
- **Agent 对话** — 自由文本指令界面，直接向主 Agent 发送人工指令
- **Agent 配置** — 管理 Agent 定义、提示词、Skill 权限和 LLM 参数
- **Skill 管理** — 浏览已安装 Skill，查看 SKILL.md 文档，按 Agent 切换访问权限

### 平台与架构

- **FastAPI 后端** — 异步 Python 运行时，结构化 JSON API，uvicorn 服务器
- **React + Vite 前端** — TypeScript、TailwindCSS、组件化架构
- **统一开发入口** — `python scripts/dev.py dev` 一条命令启动全部服务
- **清晰项目布局** — `runtime/`、`webui/`、`examples/`、`scripts/` 严格分层；无 `PYTHONPATH` hack

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
│  │   │         ↓ tool_calls（委托子 Agent）               │    │  │
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
└─────────────────────────────────────────────────────────────────┘
```

**核心设计模式**

- **Supervisor + Worker SubGraph** — 子 Agent 以编译后的 ReAct SubGraph 形式封装为 `@tool`，只有 `final_response` 作为 `ToolMessage` 返回给主 Agent
- **SKILL.md 自动发现** — Skill 是文件系统插件；无需修改代码即可添加新能力
- **双入口类型** — `alert`（来自 SIEM 的 JSON 告警）和 `conversation`（人工指令）；均通过同一 Agent 运行时路由
- **结构化 Planner** — 需要严格路由决策时，可使用 Pydantic 结构化输出模型 `PlannerResult`
- **原子化结果序列化** — 所有图执行结果均经 `_serialize_graph_result` / `_serialize_alert_result` 统一处理，保证上层 API 结构一致

**核心组件**

- **`SentinelFlowAgentService`** — 顶层服务，负责路由到编排器或单 Agent 图，并序列化执行结果
- **`build_orchestrator_graph()`** — 编译 Supervisor + Worker 多 Agent LangGraph
- **`build_agent_graph()`** — 构建单 Agent ReAct SubGraph（同时用于子 Agent 和独立 Agent）
- **`SentinelFlowSkillLoader`** — 从插件目录发现和验证 Skill
- **`SentinelFlowSkillRuntime`** — 管理 Skill 生命周期，将 Skill 适配为 LangChain 工具供 Agent 使用
- **`TriageService`** — 基于规则的告警处置推断，作为 Agent 无法研判时的兜底
- **`AgentWorkflowRegistry`** — 列举和解析 `agent.yaml` 定义的多步骤工作流

</details>

<details>
<summary><strong>项目结构</strong></summary>

```
.
├── pyproject.toml                      # Python 包配置与 CLI 入口
├── scripts/
│   └── dev.py                          # 统一本地开发入口
├── runtime/
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
│       ├── api/                        # FastAPI 路由处理器
│       ├── services/                   # 业务逻辑（研判、富化等）
│       ├── workflows/                  # Agent 工作流注册表
│       ├── config/                     # 运行时配置加载器（.env）
│       ├── domain/                     # 共享枚举、模型、错误类型
│       └── alerts/                     # 告警接入与规范化
├── webui/
│   └── src/
│       ├── components/                 # React UI 组件
│       ├── pages/                      # 页面级视图
│       ├── api/                        # API 客户端（fetch 封装）
│       ├── hooks/                      # 自定义 React Hooks
│       └── styles/                     # 全局样式与 Tailwind 配置
└── examples/
    ├── skills/                         # 示例 Skill 插件
    ├── agents/                         # 示例 Agent 定义
    ├── tasks/                          # 示例告警载荷
    ├── tools/                          # 示例工具配置
    └── workflows/                      # 示例 Agent 工作流
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
```

通过 editable install 安装后，也可直接使用 CLI：

```bash
sentinelflow dev
sentinelflow backend
```

### 环境变量配置

将 `.env.example` 复制为 `.env` 并填写 LLM 配置：

```bash
cp .env.example .env
```

关键配置项：

```ini
# LLM 配置（OpenAI 兼容格式）
LLM_API_KEY=sk-...
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# 运行时
AGENT_ENABLED=true
```

### 运行测试

```bash
# 运行全部 Python 测试
pytest runtime/tests/

# 带详情输出
pytest runtime/tests/ -v
```

### 技术栈

**后端**：Python 3.11 · FastAPI · uvicorn · LangGraph · LangChain · Pydantic v2 · python-dotenv

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

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写 LLM API Key、API 地址和模型名称
# 或在WebUI中配置
```

### 4. 启动全栈开发环境

```bash
python scripts/dev.py dev
```

默认启动：
- **后端 API**：`http://127.0.0.1:8001`
- **WebUI**：`http://127.0.0.1:5173`

### 5. 添加你的第一个 Skill（可选）

在 `.sentinelflow/plugins/skills/` 下创建一个新目录，并添加 `SKILL.md`：

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

## 常见问题

<details>
<summary><strong>SentinelFlow 支持哪些 LLM 服务商？</strong></summary>

SentinelFlow 使用 OpenAI 兼容 API 接口（`langchain-openai`）。所有支持 OpenAI Chat Completions API 格式的服务商均可接入，包括 OpenAI、Anthropic（通过代理）、DeepSeek、通义千问、本地模型（Ollama/LM Studio）以及各类 API 中转服务。

通过 `.env` 配置端点：
```ini
LLM_API_BASE_URL=https://your-provider/v1
LLM_API_KEY=your-key
LLM_MODEL=model-name
```

</details>

<details>
<summary><strong>如何定义一个子 Agent（Worker）？</strong></summary>

在 `.sentinelflow/plugins/agents/` 下创建目录，包含 `agent.yaml` 和可选的 `prompt.md`：

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

主 Agent（Supervisor）通过 LangGraph 的 `ToolNode` 将所有可用子 Agent SubGraph 绑定为工具。在每个推理步骤，LLM 自主决策：调用某个子 Agent 工具、再委托下一个子 Agent，或直接结束编排返回最终结论。`worker_max_steps` 参数限制委托总次数，防止编排失控。

</details>

<details>
<summary><strong>没有 LLM API Key 也能运行 SentinelFlow 吗？</strong></summary>

WebUI 和告警接入流水线不依赖 LLM Key 即可正常运行。但 AI Agent 功能（多 Agent 编排、Skill 调用、LLM 辅助研判）需要配置 LLM 端点。当 Agent 未配置时，`TriageService` 会提供基于规则的兜底处置结论。

</details>

<details>
<summary><strong>项目数据存储在哪里？</strong></summary>

- **Agent 定义**：`.sentinelflow/plugins/agents/`
- **Skill 插件**：`.sentinelflow/plugins/skills/`
- **运行时配置**：项目根目录 `.env`
- **运行时生成状态**：已加入 `.gitignore`，不进入版本库

</details>

<details>
<summary><strong>如何定义固定多步骤 Agent Workflow？</strong></summary>

在 `.sentinelflow/plugins/workflows/`（或 `examples/workflows/`）下创建 YAML 文件。主 Agent 通过结构化 LLM 推理为来袭告警选择最优工作流，若无匹配则回退到自由 ReAct。

```yaml
id: phishing-triage-v1
name: 钓鱼告警研判工作流
description: 标准钓鱼告警研判流程，含 URL 分析和发件人核查
enabled: true
scenarios:
  - phishing
  - suspicious_email
selection_keywords:
  - 钓鱼
  - 恶意链接
  - 可疑发件人
steps:
  - agent: url-analysis-worker
  - agent: sender-reputation-worker
  - agent: closure-worker
```

</details>

## 文档

各功能的详细使用文档，请参阅规划中的 **[用户手册](docs/user-manual/zh/README.md)** — 涵盖 Agent 配置、Skill 开发、Workflow 编写、API 参考以及部署指南。

> 📝 **注意**：完整文档正在积极建设中，欢迎社区贡献！

## 贡献

欢迎提交 Issue 反馈问题和建议！

提交 PR 前请确保：

- Python：`pytest runtime/tests/` 全部通过
- 不引入基于 `PYTHONPATH` 的 hack；使用规范的包导入
- 新 Skill 示例放入 `examples/skills/`，不要混入 `runtime/`
- 新 Agent 示例放入 `examples/agents/`

新功能开发前，建议先开 Issue 讨论方案，不适合项目定位的功能性 PR 可能被关闭。

## 许可证

Apache License 2.0 © SentinelFlow 贡献者

## 联系方式

- 📧 Email: ch1nfo@foxmail.com

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个 Star！⭐**

</div>