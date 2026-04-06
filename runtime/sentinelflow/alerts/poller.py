from sentinelflow.alerts.client import SOCAlertApiClient
from sentinelflow.alerts.dedup import AlertDedupStore
from sentinelflow.domain.models import PollingDispatchResult
from sentinelflow.services.dispatch_service import AlertDispatchService


class AlertPollingService:
    def __init__(
        self,
        client: SOCAlertApiClient,
        dedup: AlertDedupStore,
        dispatch_service: AlertDispatchService,
    ) -> None:
        self.client = client
        self.dedup = dedup
        self.dispatch_service = dispatch_service

    async def poll_once(self) -> PollingDispatchResult:
        response = self.client.fetch_open_alerts()
        if "error" in response:
            return PollingDispatchResult(
                fetched_count=0,
                queued_count=0,
                skipped_count=0,
                failed_count=1,
                errors=[str(response.get("error", "Unknown polling error"))],
            )

        alerts = response.get("alerts", [])
        if not isinstance(alerts, list):
            return PollingDispatchResult(
                fetched_count=0,
                queued_count=0,
                skipped_count=0,
                failed_count=1,
                errors=["Polling response has invalid alerts structure."],
            )

        if response.get("demo_mode") and not alerts and not response.get("fallback_triggered"):
            self.dispatch_service.clear_demo_tasks()

        queued_tasks, skipped, errors = await self.dispatch_service.dispatch(alerts)
        
        fallback_errors = []
        if response.get("fallback_triggered") and response.get("fallback_reason"):
            fallback_errors.append(f"由于告警源故障触发降级回退：{response['fallback_reason']}")
            
        combined_errors = fallback_errors + errors
        
        return PollingDispatchResult(
            fetched_count=len(alerts),
            queued_count=len(queued_tasks),
            skipped_count=skipped,
            failed_count=len(combined_errors),
            tasks=self.dispatch_service.list_tasks(),
            errors=combined_errors,
        )
