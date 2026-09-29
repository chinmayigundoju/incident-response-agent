import re
from pathlib import Path

from pydantic import BaseModel

from app.tools.schemas import ServiceName


class RunbookDocument(BaseModel):
    slug: str
    title: str
    service: ServiceName
    version: str
    content: str


class RunbookTool:
    """Read only checked-in runbooks; callers never supply a filesystem path."""

    _catalog = {
        ServiceName.CHECKOUT: ("checkout-db-pool", "database-overload"),
        ServiceName.PAYMENT: ("payment-provider-latency",),
        ServiceName.GATEWAY: ("gateway-error-rate",),
    }

    def __init__(self, root: Path):
        self._root = root.resolve()

    def list_for_service(self, service: ServiceName) -> tuple[str, ...]:
        return self._catalog[service]

    def list_runbooks(self, service: ServiceName) -> tuple[str, ...]:
        return self.list_for_service(service)

    def get(self, service: ServiceName, slug: str) -> RunbookDocument:
        if slug not in self._catalog[service]:
            raise ValueError("unknown runbook")
        path = (self._root / f"{slug}.md").resolve()
        if path.parent != self._root:
            raise ValueError("invalid runbook path")
        content = path.read_text(encoding="utf-8")
        title = re.search(r"^title:\s*(.+)$", content, re.MULTILINE)
        version = re.search(r'^version:\s*"?([^"\n]+)', content, re.MULTILINE)
        return RunbookDocument(
            slug=slug,
            title=title.group(1) if title else slug,
            service=service,
            version=version.group(1) if version else "unknown",
            content=content,
        )

    def get_runbook(self, service: ServiceName, issue: str) -> RunbookDocument:
        normalized = issue.strip().lower().replace("_", "-")
        matches = [
            slug for slug in self._catalog[service] if normalized in slug or slug in normalized
        ]
        if not matches:
            raise ValueError("unknown runbook issue")
        return self.get(service, matches[0])
