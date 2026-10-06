"""Immutable sales management reports and their existing-scheduler registration.

Revision ID: 20261006_0073
Revises: 20261006_0072
"""
from alembic import op
import sqlalchemy as sa

revision = '20261006_0073'
down_revision = '20261006_0072'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sales_period_snapshots',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('format_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'source_id'], ['sales_sync_states.tenant_id', 'sales_sync_states.source_id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('tenant_id', 'kind', 'period_start', name='uq_sales_snapshot_period'),
        sa.CheckConstraint("kind IN ('week', 'month')", name='ck_sales_snapshot_kind'),
        sa.CheckConstraint('period_end >= period_start', name='ck_sales_snapshot_dates'),
        sa.CheckConstraint('format_version = 1', name='ck_sales_snapshot_version'))
    op.create_index('ix_sales_snapshot_history', 'sales_period_snapshots', ['tenant_id', 'kind', 'period_start'])
    op.execute('''CREATE FUNCTION reject_sales_snapshot_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Sales period snapshot is immutable'; END; $$ LANGUAGE plpgsql''')
    op.execute('''CREATE TRIGGER sales_snapshot_immutable BEFORE UPDATE OR DELETE
        ON sales_period_snapshots FOR EACH ROW EXECUTE FUNCTION reject_sales_snapshot_mutation()''')
    # Use a configured source timezone and the existing sync owner, never invent identity.
    op.execute('''WITH inserted AS (
        INSERT INTO automation_schedules
            (name, automation_type, contract_version, tenant_id, scope_type, schedule_config,
             payload, recipients, timezone, is_enabled, next_run_at, created_by_user_id)
        SELECT 'Отчёты продаж', 'sales.finalize_reports', '1.0', s.tenant_id, 'company',
            '{"type":"daily","time":"08:00"}'::jsonb, '{}'::jsonb, '[]'::jsonb,
            s.source_timezone, true, now(), a.created_by_user_id
        FROM sales_sync_states s JOIN LATERAL (
            SELECT created_by_user_id FROM automation_schedules
            WHERE tenant_id=s.tenant_id AND automation_type='sales.sync_iiko'
            ORDER BY id LIMIT 1
        ) a ON true
        WHERE (SELECT count(*) FROM sales_sync_states WHERE tenant_id=s.tenant_id)=1
            AND NOT EXISTS (SELECT 1 FROM automation_schedules WHERE tenant_id=s.tenant_id
                AND automation_type='sales.finalize_reports')
        RETURNING id, created_by_user_id
    ) INSERT INTO automation_schedule_audit_events (event_type, actor_user_id, schedule_id, metadata)
        SELECT 'automation_schedule_created', created_by_user_id, id, '{"reason":"Sales reports migration 0073"}'::jsonb FROM inserted''')


def downgrade():
    # Preserve execution/audit history; stop the action before removing its data model.
    op.execute("UPDATE automation_schedules SET is_enabled=false, next_run_at=NULL WHERE automation_type='sales.finalize_reports'")
    op.execute('DROP TRIGGER sales_snapshot_immutable ON sales_period_snapshots')
    op.execute('DROP FUNCTION reject_sales_snapshot_mutation()')
    op.drop_index('ix_sales_snapshot_history', table_name='sales_period_snapshots')
    op.drop_table('sales_period_snapshots')
