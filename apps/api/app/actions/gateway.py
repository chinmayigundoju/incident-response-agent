import httpx

from app.core.errors import ApplicationError

EXECUTABLE_DEMO_ACTIONS = {
    "ROLLBACK_CHECKOUT_DEMO": "/demo/actions/rollback-checkout",
    "RESET_PAYMENT_FAULT": "/demo/actions/reset-payment-fault",
    "RESET_DB_POOL_FAULT": "/demo/actions/reset-db-pool-fault",
}


class ControlledDemoActionGateway:
    """Executes only named simulator mutations; never shell or infrastructure commands."""

    def __init__(self, base_url: str, timeout: float):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def execute(self, action_type: str) -> dict[str, object]:
        route = EXECUTABLE_DEMO_ACTIONS.get(action_type)
        if route is None:
            raise ApplicationError(
                "ACTION_NOT_EXECUTABLE", "Recommendation is not a demo mutation", 409
            )
        try:
            response = await self._client.post(route)
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApplicationError(
                "ACTION_EXECUTION_FAILED", "Controlled demo action failed", 502
            ) from exc
        if not isinstance(result, dict):
            raise ApplicationError(
                "ACTION_EXECUTION_FAILED", "Controlled demo action returned invalid data", 502
            )
        return result
