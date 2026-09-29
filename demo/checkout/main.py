import asyncio
import logging
import os
import uuid
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from shared.models import (
    CheckoutRequest,
    CheckoutResponse,
    FaultState,
    Health,
    PaymentRequest,
)
from shared.observability import (
    CHECKOUT_FAILURES,
    DB_POOL_ACTIVE,
    DB_POOL_AVAILABLE,
    DB_POOL_WAITING,
    configure_observability,
)

app = FastAPI(title="Demo Checkout Service")
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
capacity = int(os.getenv("DB_POOL_CAPACITY", "5"))
pool = asyncio.Semaphore(capacity)
fault_state: Literal["NORMAL", "DB_POOL_EXHAUSTION"] = "NORMAL"
fault_counter = 0
DB_POOL_AVAILABLE.labels("demo-checkout").set(capacity)


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(service="demo-checkout")


async def database_order_operation() -> None:
    global fault_counter
    if fault_state == "DB_POOL_EXHAUSTION":
        fault_counter += 1
        DB_POOL_AVAILABLE.labels("demo-checkout").set(0)
        DB_POOL_WAITING.labels("demo-checkout").inc()
        await asyncio.sleep(float(os.getenv("DB_ACQUIRE_TIMEOUT_SECONDS", "0.08")))
        DB_POOL_WAITING.labels("demo-checkout").dec()
        if fault_counter % 2:
            logger.error("Timed out acquiring database connection")
            CHECKOUT_FAILURES.labels("db_pool_exhaustion").inc()
            raise HTTPException(
                status_code=503, detail="Database connection pool unavailable"
            )
        await asyncio.sleep(0.25)
        return

    await pool.acquire()
    DB_POOL_ACTIVE.labels("demo-checkout").inc()
    DB_POOL_AVAILABLE.labels("demo-checkout").dec()
    try:
        await asyncio.sleep(0.02)
    finally:
        DB_POOL_ACTIVE.labels("demo-checkout").dec()
        DB_POOL_AVAILABLE.labels("demo-checkout").inc()
        pool.release()


@app.post("/internal/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest) -> CheckoutResponse:
    with tracer.start_as_current_span("checkout processing"):
        with tracer.start_as_current_span("database/order operation"):
            await database_order_operation()
        payment_url = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8102")
        payload = PaymentRequest(
            customer_id=request.customer_id,
            amount_minor=int(request.amount * 100),
        )
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    f"{payment_url}/internal/payments/authorize",
                    json=payload.model_dump(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            CHECKOUT_FAILURES.labels("payment_error").inc()
            logger.error("Payment authorization failed: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503, detail="Payment service unavailable"
            ) from exc
        return CheckoutResponse(
            order_id=str(uuid.uuid4()), status="confirmed", amount=request.amount
        )


@app.get("/internal/fault", response_model=FaultState)
def get_fault() -> FaultState:
    return FaultState(state=fault_state)


@app.post("/internal/fault/{mode}", response_model=FaultState)
def set_fault(mode: Literal["NORMAL", "DB_POOL_EXHAUSTION"]) -> FaultState:
    global fault_state, fault_counter
    fault_state = mode
    fault_counter = 0
    DB_POOL_AVAILABLE.labels("demo-checkout").set(
        0 if mode == "DB_POOL_EXHAUSTION" else capacity
    )
    DB_POOL_WAITING.labels("demo-checkout").set(0)
    return FaultState(state=fault_state)


configure_observability(app, "demo-checkout")
