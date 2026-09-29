import os
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI, HTTPException, Query
from opentelemetry import trace
from shared.models import (
    ActionResult,
    CheckoutRequest,
    CheckoutResponse,
    DeploymentRecord,
    FaultState,
    Health,
)
from shared.observability import configure_observability

app = FastAPI(title="Demo Gateway")
tracer = trace.get_tracer(__name__)
checkout_version = "2.17"
checkout_deployed_at = datetime.now(UTC) - timedelta(days=4)


def checkout_url() -> str:
    return os.getenv("CHECKOUT_SERVICE_URL", "http://localhost:8101")


def payment_url() -> str:
    return os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8102")


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(service="demo-gateway")


@app.post("/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest) -> CheckoutResponse:
    with tracer.start_as_current_span("gateway forward"):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{checkout_url()}/internal/checkout",
                    json={
                        "customer_id": request.customer_id,
                        "amount": str(request.amount),
                    },
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail="Checkout service unavailable"
            ) from exc
        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code, detail="Checkout failed"
            )
        return CheckoutResponse.model_validate(response.json())


@app.get("/demo/faults", response_model=FaultState)
async def get_faults() -> FaultState:
    async with httpx.AsyncClient(timeout=2) as client:
        checkout_response = await client.get(f"{checkout_url()}/internal/fault")
        payment_response = await client.get(f"{payment_url()}/internal/fault")
    checkout_state = checkout_response.json()["state"]
    payment_state = payment_response.json()["state"]
    state = checkout_state if checkout_state != "NORMAL" else payment_state
    return FaultState(state=state)


async def set_modes(checkout_mode: str, payment_mode: str, result: str) -> FaultState:
    async with httpx.AsyncClient(timeout=2) as client:
        await client.post(f"{checkout_url()}/internal/fault/{checkout_mode}")
        await client.post(f"{payment_url()}/internal/fault/{payment_mode}")
    return FaultState(state=result)


@app.post("/demo/faults/db-pool-exhaustion", response_model=FaultState)
async def db_pool_exhaustion() -> FaultState:
    global checkout_version, checkout_deployed_at
    checkout_version = "2.18"
    checkout_deployed_at = datetime.now(UTC)
    return await set_modes("DB_POOL_EXHAUSTION", "NORMAL", "DB_POOL_EXHAUSTION")


@app.post("/demo/faults/payment-latency", response_model=FaultState)
async def payment_latency() -> FaultState:
    global checkout_version, checkout_deployed_at
    checkout_version = "2.17"
    checkout_deployed_at = datetime.now(UTC) - timedelta(days=4)
    return await set_modes("NORMAL", "PAYMENT_LATENCY", "PAYMENT_LATENCY")


@app.post("/demo/faults/reset", response_model=FaultState)
async def reset_faults() -> FaultState:
    global checkout_version, checkout_deployed_at
    checkout_version = "2.17"
    checkout_deployed_at = datetime.now(UTC) - timedelta(days=4)
    return await set_modes("NORMAL", "NORMAL", "NORMAL")


@app.get("/demo/deployments/{service}", response_model=list[DeploymentRecord])
def recent_deployments(
    service: str, since_minutes: int = Query(default=120, ge=1, le=1440)
) -> list[DeploymentRecord]:
    if service not in {"gateway", "checkout", "payment"}:
        raise HTTPException(status_code=404, detail="Unknown demo service")
    if service == "checkout":
        deployments = [
            DeploymentRecord(
                service="checkout",
                version=checkout_version,
                deployed_at=checkout_deployed_at,
                previous_version="2.17" if checkout_version == "2.18" else None,
                change_summary=(
                    "Database connection pool setting reduced from 50 to 5"
                    if checkout_version == "2.18"
                    else "Controlled demo rollback restored pool setting"
                ),
            ),
            DeploymentRecord(
                service="checkout",
                version="2.17",
                deployed_at=checkout_deployed_at - timedelta(minutes=60),
                change_summary="Known stable simulated checkout deployment",
            ),
        ]
        cutoff = datetime.now(UTC) - timedelta(minutes=since_minutes)
        return [item for item in deployments if item.deployed_at >= cutoff]
    deployments = [
        DeploymentRecord(
            service=service,
            version="1.4.0",
            deployed_at=datetime.now(UTC) - timedelta(days=4),
            change_summary="Routine simulated demo deployment",
        )
    ]
    cutoff = datetime.now(UTC) - timedelta(minutes=since_minutes)
    return [item for item in deployments if item.deployed_at >= cutoff]


@app.post("/demo/actions/rollback-checkout", response_model=ActionResult)
async def rollback_checkout() -> ActionResult:
    global checkout_version
    checkout_version = "2.17"
    await set_modes("NORMAL", "NORMAL", "NORMAL")
    return ActionResult(
        action="ROLLBACK_CHECKOUT_DEMO",
        detail="CONTROLLED DEMO REMEDIATION: checkout v2.18 rolled back to v2.17",
    )


@app.post("/demo/actions/reset-payment-fault", response_model=ActionResult)
async def reset_payment_fault() -> ActionResult:
    await set_modes("NORMAL", "NORMAL", "NORMAL")
    return ActionResult(
        action="RESET_PAYMENT_FAULT",
        detail="CONTROLLED DEMO REMEDIATION: simulated payment latency fault reset",
    )


@app.post("/demo/actions/reset-db-pool-fault", response_model=ActionResult)
async def reset_db_pool_fault() -> ActionResult:
    await set_modes("NORMAL", "NORMAL", "NORMAL")
    return ActionResult(
        action="RESET_DB_POOL_FAULT",
        detail="CONTROLLED DEMO REMEDIATION: simulated DB pool fault reset",
    )


configure_observability(app, "demo-gateway")
