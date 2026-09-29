import os

import pytest

from app.core.config import Settings
from app.llm.groq import GroqProvider

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_live_groq_can_select_a_registered_tool():
    if os.getenv("RUN_GROQ_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_GROQ_INTEGRATION_TESTS=1 to run live Groq test")
    settings = Settings()
    if not settings.GROQ_API_KEY:
        pytest.skip("GROQ_API_KEY is not configured")
    provider = GroqProvider(
        settings.GROQ_API_KEY,
        settings.GROQ_BASE_URL,
        settings.GROQ_MODEL,
        timeout=30,
    )
    try:
        step = await provider.next_step(
            incident={
                "id": "00000000-0000-0000-0000-000000000001",
                "title": "Checkout 503s",
                "service": "checkout",
                "environment": "integration",
            },
            evidence=[],
            called_tools=[],
        )
    finally:
        await provider.close()
    assert step.kind in {"tool", "diagnosis"}
