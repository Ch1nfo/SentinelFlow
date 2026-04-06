"""
SentinelFlow API Application Entry Point

All service singletons are initialized here and re-exported via deps.py.
Route handlers live in separate router modules (routers/).
"""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI

from sentinelflow.alerts.client import SOCAlertApiClient
from sentinelflow.alerts.dedup import AlertDedupStore
from sentinelflow.alerts.parser_generator import AlertParserGenerator
from sentinelflow.alerts.poller import AlertPollingService
from sentinelflow.agent.service import SentinelFlowAgentService
from sentinelflow.config.branding import load_branding_config
from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.dispatch_service import AlertDispatchService
from sentinelflow.services.triage_service import TriageService
from sentinelflow.skills.adapters import SentinelFlowSkillRuntime
from sentinelflow.workflows.agent_workflow_runner import SentinelFlowAgentWorkflowRunner

# ── Path roots ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLATFORM_ROOT = PROJECT_ROOT.parent if (PROJECT_ROOT.parent / ".sentinelflow").is_dir() else PROJECT_ROOT
SKILL_ROOT = PROJECT_ROOT / ".sentinelflow" / "plugins" / "skills"
WORKFLOW_ROOT = PROJECT_ROOT / ".sentinelflow" / "plugins" / "workflows"
AGENT_ROOT = PROJECT_ROOT / ".sentinelflow" / "plugins" / "agents"
PLATFORM_PLUGIN_ROOT = PLATFORM_ROOT / ".sentinelflow" / "plugins"

# ── Branding & App ───────────────────────────────────────────────────────────
branding = load_branding_config()
app = FastAPI(title=branding.api_title, version="0.1.0")

# ── Service singletons ───────────────────────────────────────────────────────
skill_runtime = SentinelFlowSkillRuntime(SKILL_ROOT)
audit_service = AuditService()
agent_service = SentinelFlowAgentService(
    project_root=PROJECT_ROOT,
    skill_runtime=skill_runtime,
)


async def _workflow_selector(alert):
    return await agent_service.resolve_alert_workflow(alert, WORKFLOW_ROOT)


triage_service = TriageService(
    workflow_root=WORKFLOW_ROOT,
    workflow_selector=_workflow_selector,
)
agent_workflow_runner = SentinelFlowAgentWorkflowRunner(
    agent_service=agent_service,
    audit_service=audit_service,
)
dispatch_service = AlertDispatchService(
    dedup=AlertDedupStore(),
    triage_service=triage_service,
    audit_service=audit_service,
)
polling_service = AlertPollingService(
    client=SOCAlertApiClient(),
    dedup=dispatch_service.dedup,
    dispatch_service=dispatch_service,
)
alert_parser_generator = AlertParserGenerator()

# ── Router registration ──────────────────────────────────────────────────────
from sentinelflow.api.routers import system, plugins, alerts  # noqa: E402

app.include_router(system.router)
app.include_router(plugins.router)
app.include_router(alerts.router)
