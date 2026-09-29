"""Enforce one active incident per Alertmanager fingerprint.

Revision ID: 0003_recurring_incident_identity
Revises: 0002_workflow_state
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_recurring_incident_identity"
down_revision: str | None = "0002_workflow_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_STATUS_SQL = (
    "'DETECTED', 'TRIAGED', 'INVESTIGATING', 'DIAGNOSIS_PROPOSED', "
    "'MITIGATION_PROPOSED', 'AWAITING_APPROVAL', 'MITIGATING', "
    "'VERIFYING_RECOVERY'"
)


def upgrade() -> None:
    op.create_index(
        "uq_incidents_active_fingerprint",
        "incidents",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text(f"fingerprint IS NOT NULL AND status IN ({ACTIVE_STATUS_SQL})"),
    )


def downgrade() -> None:
    op.drop_index("uq_incidents_active_fingerprint", table_name="incidents")
