"""add immutable business audit

Revision ID: 20260929_0061
Revises: 20260929_0060
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260929_0061"
down_revision: str | None = "20260929_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(160), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_employee_id", sa.Uuid(), nullable=True),
        sa.Column("actor_name_snapshot", sa.String(240), nullable=True),
        sa.Column("active_roles_snapshot", json_type, nullable=False),
        sa.Column("authorized_as", sa.String(32), nullable=True),
        sa.Column("primary_department_id", sa.Uuid(), nullable=True),
        sa.Column("primary_department_name_snapshot", sa.String(240), nullable=True),
        sa.Column("actual_department_id", sa.Uuid(), nullable=True),
        sa.Column("actual_department_name_snapshot", sa.String(240), nullable=True),
        sa.Column("shift_id", sa.Uuid(), nullable=True),
        sa.Column("shift_context_snapshot", json_type, nullable=True),
        sa.Column("before", json_type, nullable=False),
        sa.Column("after", json_type, nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("correction_of_event_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_audit_events_tenant_id"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_audit_events_actor_employee_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "primary_department_id"], ["departments.tenant_id", "departments.id"],
            name="fk_audit_events_primary_department_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actual_department_id"], ["departments.tenant_id", "departments.id"],
            name="fk_audit_events_actual_department_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "shift_id"], ["employee_iiko_shifts.tenant_id", "employee_iiko_shifts.id"],
            name="fk_audit_events_shift_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "correction_of_event_id"], ["audit_events.tenant_id", "audit_events.id"],
            name="fk_audit_events_correction_tenant", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("reason IS NULL OR length(trim(reason)) > 0", name="ck_audit_events_reason"),
        sa.CheckConstraint("source IN ('HUMAN', 'SYSTEM')", name="ck_audit_events_source"),
        sa.CheckConstraint(
            "(source = 'HUMAN' AND actor_user_id IS NOT NULL) OR "
            "(source = 'SYSTEM' AND actor_user_id IS NULL)",
            name="ck_audit_events_actor_source",
        ),
    )
    op.create_index("ix_audit_events_tenant_occurred", "audit_events", ["tenant_id", "occurred_at", "id"])
    op.create_index("ix_audit_events_entity", "audit_events", ["tenant_id", "entity_type", "entity_id", "occurred_at"])
    op.create_index("ix_audit_events_employee", "audit_events", ["tenant_id", "actor_employee_id", "occurred_at"])
    op.create_index("ix_audit_events_department", "audit_events", ["tenant_id", "actual_department_id", "occurred_at"])
    op.create_index("ix_audit_events_type", "audit_events", ["tenant_id", "event_type", "occurred_at"])
    op.execute("""
        CREATE FUNCTION prevent_audit_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events are immutable' USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_audit_events_immutable
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_event_mutation()")
    op.drop_table("audit_events")
