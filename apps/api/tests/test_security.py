from fastapi.testclient import TestClient

from app.core.security import MutationRateLimiter, RedactingFormatter
from app.main import app


def test_mutation_rate_limit_is_bounded():
    limiter = MutationRateLimiter(2)
    assert limiter.allow("client", now=0)
    assert limiter.allow("client", now=1)
    assert not limiter.allow("client", now=2)
    assert limiter.allow("client", now=61)


def test_secret_formatter_redacts_values():
    import logging

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "api_key=secret-value", (), None)
    assert "secret-value" not in RedactingFormatter("%(message)s").format(record)


def test_health_response_does_not_expose_configuration_secrets():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.text.upper()
    assert "HINDSIGHT_API_KEY" not in body
    assert "GROQ_API_KEY" not in body
