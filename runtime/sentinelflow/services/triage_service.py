from __future__ import annotations

import ipaddress
import uuid

from sentinelflow.domain.models import AlertHandlingTask, JudgmentResult
from sentinelflow.domain.enums import AlertDisposition


class TriageService:
    """Builds queued alert-handling tasks for downstream main-agent execution."""

    async def build_task(self, alert: dict) -> AlertHandlingTask:
        event_ids = str(alert.get("eventIds", "")).strip()
        alert_name = str(alert.get("alert_name", "未知告警")).strip() or "未知告警"
        task_id = f"sentinelflow-task-{uuid.uuid4().hex[:12]}"
        return AlertHandlingTask(
            task_id=task_id,
            event_ids=event_ids,
            workflow_name="agent_react",
            title=alert_name,
            description=f"Handle alert {event_ids} through workflow agent_react.",
            alert_time=str(alert.get("alert_time", "")).strip(),
            payload={"alert_data": alert},
        )

    def analyze_alert(self, alert: dict) -> JudgmentResult:
        current = str(alert.get("current_judgment", "")).strip()
        history = str(alert.get("history_judgment", "")).strip()
        alert_name = str(alert.get("alert_name", "未知告警")).strip() or "未知告警"
        combined = f"{current},{history},{alert_name}"

        if any(keyword in combined for keyword in ("攻击", "恶意", "C2", "封禁", "暴力破解", "下线")):
            disposition = AlertDisposition.TRUE_ATTACK
            summary = f"{alert_name} 研判为真实攻击"
            evidence = [value for value in (current, history) if value]
            return JudgmentResult(disposition=disposition, summary=summary, evidence=evidence)

        if any(keyword in current for keyword in ("误报", "规则误报")):
            disposition = AlertDisposition.FALSE_POSITIVE
            summary = f"{alert_name} 研判为误报"
            evidence = [current] if current else []
            return JudgmentResult(disposition=disposition, summary=summary, evidence=evidence)

        if any(keyword in f"{current},{history}" for keyword in ("业务", "测试", "正常")):
            disposition = AlertDisposition.BUSINESS_TRIGGER
            summary = f"{alert_name} 研判为测试或业务触发"
            evidence = [value for value in (current, history) if value]
            return JudgmentResult(disposition=disposition, summary=summary, evidence=evidence)

        disposition = AlertDisposition.BUSINESS_TRIGGER
        summary = f"{alert_name} 默认按测试或业务触发结单"
        evidence = [value for value in (current, history) if value]
        return JudgmentResult(disposition=disposition, summary=summary, evidence=evidence)

    def build_closure_request(self, alert: dict, judgment: JudgmentResult) -> dict:
        status = "4" if judgment.disposition == AlertDisposition.FALSE_POSITIVE else "6"
        detail_msg = "规则误报" if status == "4" else "测试/业务触发"
        memo = self.build_memo(judgment.summary)
        return {
            "eventIds": str(alert.get("eventIds", "")).strip(),
            "status": status,
            "memo": memo,
            "detailMsg": detail_msg,
        }

    def pick_enrichment_ip(self, alert: dict) -> str | None:
        for key in ("sip", "dip"):
            ip = str(alert.get(key, "")).strip()
            if not ip:
                continue
            try:
                if ipaddress.ip_address(ip).is_private:
                    return ip
            except ValueError:
                continue
        return None

    def build_memo(self, summary: str) -> str:
        compact = summary.replace("研判为", "").replace("默认按", "").replace("结单", "")
        compact = compact.strip()
        if len(compact) > 20:
            compact = compact[:20]
        return compact or "测试触发"

    def build_disposal_reason(self, judgment: JudgmentResult) -> str:
        text = judgment.summary.replace("研判为", "").replace("真实攻击", "").strip()
        if "C2" in judgment.summary:
            return "恶意C2"
        if "暴力" in judgment.summary:
            return "暴力破解"
        if "扫描" in judgment.summary:
            return "恶意扫描"
        return (text[:12] if text else "恶意攻击")
