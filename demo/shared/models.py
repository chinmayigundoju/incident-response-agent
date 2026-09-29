from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    service: str


class CheckoutRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class CheckoutResponse(BaseModel):
    order_id: str
    status: Literal["confirmed"]
    amount: Decimal


class PaymentRequest(BaseModel):
    customer_id: str
    amount_minor: int = Field(gt=0)


class PaymentResponse(BaseModel):
    authorization_id: str
    approved: Literal[True] = True


class FaultState(BaseModel):
    state: Literal["NORMAL", "DB_POOL_EXHAUSTION", "PAYMENT_LATENCY"]


class DeploymentRecord(BaseModel):
    service: Literal["gateway", "checkout", "payment"]
    version: str
    deployed_at: datetime
    previous_version: str | None = None
    simulated: Literal[True] = True
    change_summary: str


class ActionResult(BaseModel):
    action: Literal[
        "ROLLBACK_CHECKOUT_DEMO", "RESET_PAYMENT_FAULT", "RESET_DB_POOL_FAULT"
    ]
    status: Literal["succeeded"] = "succeeded"
    detail: str
