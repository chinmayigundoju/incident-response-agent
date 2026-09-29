import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incident import MemorySync


class MemorySyncRepository:
    def __init__(self, session: Session):
        self.session = session

    def begin(self, incident_id: uuid.UUID, bank_id: str, document_id: str) -> MemorySync:
        statement = select(MemorySync).where(
            MemorySync.incident_id == incident_id,
            MemorySync.bank_id == bank_id,
            MemorySync.document_id == document_id,
        )
        sync = self.session.scalars(statement).first()
        if sync is None:
            sync = MemorySync(
                incident_id=incident_id,
                bank_id=bank_id,
                document_id=document_id,
                status="PENDING",
            )
            self.session.add(sync)
        else:
            sync.status = "PENDING"
            sync.error_message = None
        self.session.commit()
        return sync

    def get(self, incident_id: uuid.UUID, bank_id: str, document_id: str) -> MemorySync | None:
        return self.session.scalars(
            select(MemorySync).where(
                MemorySync.incident_id == incident_id,
                MemorySync.bank_id == bank_id,
                MemorySync.document_id == document_id,
            )
        ).first()

    def succeeded(self, sync: MemorySync, checksum: str) -> None:
        sync.status = "SUCCEEDED"
        sync.checksum = checksum
        sync.retained_at = datetime.now(UTC)
        sync.error_message = None
        self.session.commit()

    def failed(self, sync: MemorySync, error_type: str) -> None:
        sync.status = "FAILED"
        sync.error_message = error_type
        self.session.commit()
