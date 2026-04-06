from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class BrandingConfig:
    product_name: str
    console_title: str
    api_title: str
    workflow_engine_label: str
    notification_title_prefix: str
    skill_label: str
    workflow_label: str
    created_by: str


def load_branding_config() -> BrandingConfig:
    product_name = os.getenv("SENTINELFLOW_PRODUCT_NAME", "SentinelFlow").strip() or "SentinelFlow"
    console_title = os.getenv("SENTINELFLOW_CONSOLE_TITLE", f"{product_name} 控制台").strip() or f"{product_name} 控制台"
    api_title = os.getenv("SENTINELFLOW_API_TITLE", f"{product_name} API").strip() or f"{product_name} API"
    workflow_engine_label = os.getenv("SENTINELFLOW_WORKFLOW_ENGINE_LABEL", "SentinelFlow Agent Workflow").strip() or "SentinelFlow Agent Workflow"
    notification_title_prefix = (
        os.getenv("SENTINELFLOW_NOTIFICATION_PREFIX", f"{product_name} 告警通知").strip() or f"{product_name} 告警通知"
    )
    skill_label = os.getenv("SENTINELFLOW_SKILL_LABEL", f"{product_name} Skill").strip() or f"{product_name} Skill"
    workflow_label = os.getenv("SENTINELFLOW_WORKFLOW_LABEL", f"{product_name} workflow").strip() or f"{product_name} workflow"
    created_by = os.getenv("SENTINELFLOW_CREATED_BY", product_name).strip() or product_name
    return BrandingConfig(
        product_name=product_name,
        console_title=console_title,
        api_title=api_title,
        workflow_engine_label=workflow_engine_label,
        notification_title_prefix=notification_title_prefix,
        skill_label=skill_label,
        workflow_label=workflow_label,
        created_by=created_by,
    )
