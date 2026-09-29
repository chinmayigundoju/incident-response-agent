import enum
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IncidentAutomationMode(enum.StrEnum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    DEMO_AUTOPILOT = "demo_autopilot"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    APP_ENV: str = "development"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_CORS_ORIGINS: list[str] | str = ["http://localhost:3000"]
    DATABASE_URL: str = (
        "postgresql+psycopg://incident_response:change-me@localhost:5432/incident_response"
    )
    HINDSIGHT_BASE_URL: str | None = None
    HINDSIGHT_API_KEY: str | None = None
    HINDSIGHT_BANK_ID: str = "demo-production-incidents"
    HINDSIGHT_TIMEOUT_SECONDS: float = Field(default=300.0, gt=0, le=3600)
    GROQ_API_KEY: str | None = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_MAX_EVIDENCE_CHARS: int = Field(default=12_000, ge=8_000, le=100_000)
    GROQ_RATE_LIMIT_MAX_WAIT_SECONDS: float = Field(default=65.0, ge=0, le=120)
    PROMETHEUS_BASE_URL: str = "http://prometheus:9090"
    LOKI_BASE_URL: str = "http://loki:3100"
    TEMPO_BASE_URL: str = "http://tempo:3200"
    DEMO_GATEWAY_BASE_URL: str = "http://demo-gateway:8100"
    OBSERVABILITY_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0, le=30)
    AGENT_TOOL_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    AGENT_MAX_ITERATIONS: int = Field(default=8, ge=1, le=20)
    RECOVERY_WAIT_SECONDS: float = Field(default=2.0, ge=0, le=30)
    INCIDENT_AUTOMATION_MODE: IncidentAutomationMode = IncidentAutomationMode.ASSISTED
    AUTOMATION_RECOVERY_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    AUTOMATION_RECOVERY_RETRY_SECONDS: float = Field(default=5.0, ge=0, le=60)
    API_MAX_REQUEST_BYTES: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    MUTATION_RATE_LIMIT_PER_MINUTE: int = Field(default=30, ge=1, le=600)
    RUNBOOK_ROOT: str = "runbooks"

    @field_validator("API_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("HINDSIGHT_BASE_URL", "HINDSIGHT_API_KEY", "GROQ_API_KEY", mode="before")
    @classmethod
    def empty_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def protect_demo_autopilot(self) -> "Settings":
        if self.INCIDENT_AUTOMATION_MODE != IncidentAutomationMode.DEMO_AUTOPILOT:
            return self
        host = (urlparse(self.DEMO_GATEWAY_BASE_URL).hostname or "").lower()
        if self.APP_ENV.lower() not in {"development", "demo", "test"}:
            raise ValueError("demo_autopilot requires a simulated application environment")
        if host not in {"demo-gateway", "localhost", "127.0.0.1"}:
            raise ValueError("demo_autopilot requires the controlled demo gateway")
        return self

    @property
    def hindsight_configured(self) -> bool:
        return bool(self.HINDSIGHT_BASE_URL)

    @property
    def demo_autopilot_allowed(self) -> bool:
        return self.INCIDENT_AUTOMATION_MODE == IncidentAutomationMode.DEMO_AUTOPILOT


@lru_cache
def get_settings() -> Settings:
    return Settings()
