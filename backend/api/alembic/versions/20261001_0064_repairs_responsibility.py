"""Repair responsibility and external contractor directory.

Revision ID: 20261001_0064
Revises: 20261001_0063
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261001_0064"
down_revision: str | None = "20261001_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_work_requests_department", "work_requests", type_="check")
    op.alter_column("work_requests", "department", type_=sa.String(160), existing_nullable=False)
    op.alter_column("work_requests", "author_name", type_=sa.String(240), existing_nullable=True)
    op.create_check_constraint("ck_work_requests_department", "work_requests", "length(trim(department)) > 0")
    op.create_table(
        "external_contractors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("phone", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_external_contractors_tenant_id"),
        sa.CheckConstraint("length(trim(name)) > 0 AND length(trim(phone)) > 0", name="ck_external_contractors_identity"),
    )
    op.create_index("ix_external_contractors_tenant_active_name", "external_contractors", ["tenant_id", "is_active", "name"])
    op.create_table(
        "contractor_specializations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contractor_specializations_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_contractor_specializations_name"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_contractor_specializations_name"),
    )
    op.create_index("ix_contractor_specializations_tenant_active", "contractor_specializations", ["tenant_id", "is_active"])
    op.create_table(
        "contractor_specialization_links",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("contractor_id", sa.Uuid(), primary_key=True),
        sa.Column("specialization_id", sa.Uuid(), primary_key=True),
        sa.ForeignKeyConstraint(["tenant_id", "contractor_id"], ["external_contractors.tenant_id", "external_contractors.id"], name="fk_contractor_links_contractor_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "specialization_id"], ["contractor_specializations.tenant_id", "contractor_specializations.id"], name="fk_contractor_links_specialization_tenant", ondelete="RESTRICT"),
    )
    columns = (
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("creator_employee_id", sa.Uuid(), nullable=True),
        sa.Column("creator_authorized_as", sa.String(32), nullable=True),
        sa.Column("responsible_role", sa.String(32), nullable=True),
        sa.Column("responsible_employee_id", sa.Uuid(), nullable=True),
        sa.Column("responsibility_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contractor_id", sa.Uuid(), nullable=True),
        sa.Column("specialization_id", sa.Uuid(), nullable=True),
        sa.Column("visit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", sa.Integer(), nullable=True),
    )
    for column in columns:
        op.add_column("work_requests", column)
    for name, local, remote in (
        ("department", "department_id", "departments"),
        ("creator_employee", "creator_employee_id", "employees"),
        ("responsible_employee", "responsible_employee_id", "employees"),
        ("contractor", "contractor_id", "external_contractors"),
        ("specialization", "specialization_id", "contractor_specializations"),
    ):
        op.create_foreign_key(f"fk_work_requests_{name}_tenant", "work_requests", remote, ["tenant_id", local], ["tenant_id", "id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_work_requests_closed_by_user", "work_requests", "users", ["closed_by_user_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_work_requests_tenant_department", "work_requests", ["tenant_id", "department_id"])
    op.create_index("ix_work_requests_tenant_contractor", "work_requests", ["tenant_id", "contractor_id"])
    op.create_check_constraint("ck_work_requests_responsible_role", "work_requests", "responsible_role IS NULL OR responsible_role IN ('HANDYMAN', 'SUPPLY_MANAGER')")
    op.drop_constraint("ck_work_requests_status", "work_requests", type_="check")
    op.create_check_constraint("ck_work_requests_status", "work_requests", "status IN ('new', 'in_progress', 'waiting_external', 'escalated', 'completed', 'reopened', 'cancelled')")


def downgrade() -> None:
    connection = op.get_bind()
    has_new_repair_data = connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM work_requests WHERE department_id IS NOT NULL "
        "OR creator_employee_id IS NOT NULL OR responsible_role IS NOT NULL "
        "OR contractor_id IS NOT NULL OR visit_at IS NOT NULL "
        "OR status IN ('waiting_external', 'escalated', 'reopened'))"
    ))
    has_directory_data = connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM external_contractors) "
        "OR EXISTS (SELECT 1 FROM contractor_specializations)"
    ))
    if has_new_repair_data or has_directory_data:
        raise RuntimeError("Cannot downgrade repair workflow with new repair or contractor data")
    op.drop_constraint("ck_work_requests_status", "work_requests", type_="check")
    op.create_check_constraint("ck_work_requests_status", "work_requests", "status IN ('new', 'in_progress', 'completed', 'cancelled')")
    op.drop_constraint("ck_work_requests_responsible_role", "work_requests", type_="check")
    op.drop_index("ix_work_requests_tenant_department", table_name="work_requests")
    op.drop_index("ix_work_requests_tenant_contractor", table_name="work_requests")
    op.drop_constraint("fk_work_requests_closed_by_user", "work_requests", type_="foreignkey")
    for name in ("department", "creator_employee", "responsible_employee", "contractor", "specialization"):
        op.drop_constraint(f"fk_work_requests_{name}_tenant", "work_requests", type_="foreignkey")
    for column in ("closed_by_user_id", "closed_at", "visit_at", "specialization_id", "contractor_id", "responsibility_started_at", "responsible_employee_id", "responsible_role", "creator_authorized_as", "creator_employee_id", "department_id"):
        op.drop_column("work_requests", column)
    op.drop_table("contractor_specialization_links")
    op.drop_index("ix_contractor_specializations_tenant_active", table_name="contractor_specializations")
    op.drop_table("contractor_specializations")
    op.drop_index("ix_external_contractors_tenant_active_name", table_name="external_contractors")
    op.drop_table("external_contractors")
    op.drop_constraint("ck_work_requests_department", "work_requests", type_="check")
    op.alter_column("work_requests", "department", type_=sa.String(64), existing_nullable=False)
    op.alter_column("work_requests", "author_name", type_=sa.String(128), existing_nullable=True)
    op.create_check_constraint("ck_work_requests_department", "work_requests", "department IN ('М15', 'М35', 'М6А', 'Цех ГХ', 'Бар ГХ', 'Кухня', 'Авто', 'Производство', 'Кондитерский цех', 'Кафе', 'М6а', 'Снабжение', 'Администрация', 'Другое')")
