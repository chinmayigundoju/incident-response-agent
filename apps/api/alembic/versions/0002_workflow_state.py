"""Add approval-gated action and root-cause verification state.

Revision ID: 0002_workflow_state
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_workflow_state"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "hypotheses",
        "confidence",
        existing_type=sa.Numeric(5, 4),
        type_=sa.String(16),
        postgresql_using=(
            "CASE WHEN confidence IS NULL THEN NULL "
            "WHEN confidence >= 0.75 THEN 'HIGH' "
            "WHEN confidence >= 0.40 THEN 'MEDIUM' ELSE 'LOW' END"
        ),
    )
    op.create_unique_constraint(
        "uq_approvals_recommendation_id", "approvals", ["recommendation_id"]
    )
    op.create_table(
        "action_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "root_cause_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("approver_identifier", sa.String(255), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("root_cause_verifications")
    op.drop_table("action_executions")
    op.drop_constraint("uq_approvals_recommendation_id", "approvals", type_="unique")
    op.alter_column(
        "hypotheses",
        "confidence",
        existing_type=sa.String(16),
        type_=sa.Numeric(5, 4),
        postgresql_using=(
            "CASE confidence WHEN 'HIGH' THEN 0.85 WHEN 'MEDIUM' THEN 0.60 "
            "WHEN 'LOW' THEN 0.25 ELSE NULL END"
        ),
    )
