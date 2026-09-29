import asyncio
import logging
import os
import uuid
from typing import Literal

from fastapi import FastAPI
from opentelemetry import trace
from shared.models import FaultState, Health, PaymentRequest, PaymentResponse
from shared.observability import (
    PAYMENT_DURATION,
    PAYMENT_FAULT_ACTIVE,
    configure_observability,
)

app = FastAPI(title="Demo Payment Service")
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
fault_state: Literal["NORMAL", "PAYMENT_LATENCY"] = "NORMAL"
PAYMENT_FAULT_ACTIVE.labels("demo-payment").set(0)


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(service="demo-payment")


@app.post("/internal/payments/authorize", response_model=PaymentResponse)
async def authorize(request: PaymentRequest) -> PaymentResponse:
    delay = float(os.getenv("PAYMENT_NORMAL_DELAY_SECONDS", "0.05"))
    if fault_state == "PAYMENT_LATENCY":
        delay = float(os.getenv("PAYMENT_FAULT_DELAY_SECONDS", "1.0"))
        logger.warning("Payment latency fault active; delaying authorization")
    with tracer.start_as_current_span("payment authorization"):
        with PAYMENT_DURATION.labels("demo-payment").time():
            await asyncio.sleep(delay)
        return PaymentResponse(authorization_id=str(uuid.uuid4()))


@app.get("/internal/fault", response_model=FaultState)
def get_fault() -> FaultState:
    return FaultState(state=fault_state)


@app.post("/internal/fault/{mode}", response_model=FaultState)
def set_fault(mode: Literal["NORMAL", "PAYMENT_LATENCY"]) -> FaultState:
    global fault_state
    fault_state = mode
    PAYMENT_FAULT_ACTIVE.labels("demo-payment").set(mode == "PAYMENT_LATENCY")
    return FaultState(state=fault_state)


configure_observability(app, "demo-payment")
