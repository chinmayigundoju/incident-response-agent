from app.core.config import Settings
from app.memory import client as memory_client


def test_configured_timeout_is_passed_to_hindsight(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def construct_hindsight(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(memory_client, "Hindsight", construct_hindsight)
    settings = Settings(
        HINDSIGHT_BASE_URL="https://api.hindsight.vectorize.io",
        HINDSIGHT_API_KEY="test-key",
        HINDSIGHT_TIMEOUT_SECONDS=187.5,
    )

    client = memory_client.build_hindsight_client(settings)

    assert client is sentinel
    assert captured["timeout"] == 187.5
    assert Settings.model_fields["HINDSIGHT_TIMEOUT_SECONDS"].default == 300.0
