"""add persistent supply print jobs

Revision ID: 20260812_0033
Revises: 20260812_0032
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0033"
down_revision: Union[str, Sequence[str], None] = "20260812_0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supply_print_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("supply_request_id", sa.Uuid(), nullable=False),
        sa.Column("iiko_document_write_id", sa.Uuid(), nullable=True),
        sa.Column("automation_execution_id", sa.Uuid(), nullable=False),
        sa.Column("document_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("pdf_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("printer_name", sa.String(length=160), nullable=False),
        sa.Column("copies", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "attempt_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "last_error_code", sa.String(length=100), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "copies = 2", name="ck_supply_print_jobs_copies_two"
        ),
        sa.CheckConstraint(
            "printer_name = 'HP LaserJet Pro MFP M125rnw'",
            name="ck_supply_print_jobs_production_printer",
        ),
        sa.CheckConstraint(
            "purpose IN ('NORMAL', 'REPRINT')",
            name="supply_print_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED_FOR_PRINT', 'PRINTING', 'PRINTED', "
            "'PRINT_FAILED')",
            name="supply_print_job_status",
        ),
        sa.ForeignKeyConstraint(
            ["supply_request_id"], ["supply_requests.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["iiko_document_write_id"],
            ["iiko_document_writes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["automation_execution_id"],
            ["automation_executions.execution_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_supply_print_jobs_idempotency_key"
        ),
    )
    op.create_index(
        "ix_supply_print_jobs_request_created",
        "supply_print_jobs",
        ["tenant_id", "supply_request_id", "created_at"],
    )
    op.create_index(
        "uq_supply_print_jobs_normal_fingerprint",
        "supply_print_jobs",
        ["tenant_id", "supply_request_id", "pdf_fingerprint"],
        unique=True,
        postgresql_where=sa.text("purpose = 'NORMAL'"),
        sqlite_where=sa.text("purpose = 'NORMAL'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_supply_print_jobs_normal_fingerprint",
        table_name="supply_print_jobs",
    )
    op.drop_index(
        "ix_supply_print_jobs_request_created",
        table_name="supply_print_jobs",
    )
    op.drop_table("supply_print_jobs")
