import importlib
import time

import pytest
from fastapi import HTTPException


async def test_db_pool_exhaustion_has_deterministic_failure_and_slow_path() -> None:
    checkout = importlib.import_module("checkout.main")
    checkout.set_fault("DB_POOL_EXHAUSTION")
    with pytest.raises(HTTPException) as error:
        await checkout.database_order_operation()
    assert error.value.status_code == 503
    started = time.perf_counter()
    await checkout.database_order_operation()
    assert time.perf_counter() - started >= 0.2
    checkout.set_fault("NORMAL")
    assert checkout.get_fault().state == "NORMAL"


async def test_payment_latency_is_slower_than_normal(monkeypatch) -> None:
    payment = importlib.import_module("payment.main")
    monkeypatch.setenv("PAYMENT_NORMAL_DELAY_SECONDS", "0.001")
    monkeypatch.setenv("PAYMENT_FAULT_DELAY_SECONDS", "0.08")
    request = payment.PaymentRequest(customer_id="demo", amount_minor=149900)
    payment.set_fault("NORMAL")
    normal_start = time.perf_counter()
    await payment.authorize(request)
    normal_duration = time.perf_counter() - normal_start
    payment.set_fault("PAYMENT_LATENCY")
    fault_start = time.perf_counter()
    await payment.authorize(request)
    fault_duration = time.perf_counter() - fault_start
    payment.set_fault("NORMAL")
    assert fault_duration > normal_duration + 0.04
