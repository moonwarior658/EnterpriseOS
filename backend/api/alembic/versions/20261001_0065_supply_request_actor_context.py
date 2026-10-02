"""Persist the authorizing actor of new Supply requests.

Revision ID: 20261001_0065
Revises: 20261001_0064
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261001_0065"
down_revision: str | None = "20261001_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, column_type in (
        ("creator_employee_id", sa.Uuid()),
        ("creator_authorized_as", sa.String(32)),
        ("department_name_snapshot", sa.String(160)),
        ("primary_department_id", sa.Uuid()),
        ("actual_department_id", sa.Uuid()),
        ("creator_shift_id", sa.Uuid()),
    ):
        op.add_column("supply_requests", sa.Column(name, column_type, nullable=True))
    for name, local, remote in (
        ("creator_employee", "creator_employee_id", "employees"),
        ("primary_department", "primary_department_id", "departments"),
        ("actual_department", "actual_department_id", "departments"),
        ("creator_shift", "creator_shift_id", "employee_iiko_shifts"),
    ):
        op.create_foreign_key(
            f"fk_supply_requests_{name}_tenant", "supply_requests", remote,
            ["tenant_id", local], ["tenant_id", "id"], ondelete="RESTRICT",
        )
    op.create_index("ix_supply_requests_tenant_creator_employee", "supply_requests", ["tenant_id", "creator_employee_id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM supply_requests WHERE creator_employee_id IS NOT NULL "
        "OR creator_authorized_as IS NOT NULL OR department_name_snapshot IS NOT NULL "
        "OR primary_department_id IS NOT NULL OR actual_department_id IS NOT NULL "
        "OR creator_shift_id IS NOT NULL)"
    )):
        raise RuntimeError("Cannot downgrade Supply actor context after new requests were created")
    op.drop_index("ix_supply_requests_tenant_creator_employee", table_name="supply_requests")
    for name in ("creator_shift", "actual_department", "primary_department", "creator_employee"):
        op.drop_constraint(f"fk_supply_requests_{name}_tenant", "supply_requests", type_="foreignkey")
    for name in ("creator_shift_id", "actual_department_id", "primary_department_id", "department_name_snapshot", "creator_authorized_as", "creator_employee_id"):
        op.drop_column("supply_requests", name)
