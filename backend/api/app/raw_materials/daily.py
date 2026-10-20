"""One gated Core schedule for an explicitly accepted pilot; no separate scheduler."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.config import settings
from app.raw_materials import purchase_refresh as refresh
from app.audit.service import record_audit_event

ACTION='materials.refresh_enrolled'
class DailyPayload(BaseModel):
    model_config=ConfigDict(extra='forbid')
    product_ids:list[UUID]=Field(min_length=1,max_length=10)
    @model_validator(mode='after')
    def unique(self):
        if len(set(self.product_ids))!=len(self.product_ids):raise ValueError('Повторяющиеся карточки')
        return self


def run(db, context, payload):
    if not settings.raw_material_daily_accepted:raise ValueError('Ежедневное обновление ожидает бизнес-приёмки')
    command=DailyPayload.model_validate(payload)
    executions=[]
    # Parent execution/outbox transaction owns idempotency and commits all child commands atomically.
    for pid in sorted(command.product_ids):
        mapping=refresh.scope(db,context.tenant_id,pid)
        row=refresh.ensure_execution(db,context.tenant_id,pid,mapping)
        record_audit_event(db,tenant_id=context.tenant_id,entity_type='MaterialPurchaseRefresh',entity_id=pid,
            event_type='MATERIAL_DAILY_REFRESH_REQUESTED',operation='REFRESH_PURCHASE',source='SYSTEM',
            after=dict(execution_id=str(row.execution_id)),correlation_id=str(context.execution_id),reason='Согласованное ежедневное обновление')
        executions.append(str(row.execution_id))
    return dict(queued=len(executions),child_executions=executions)
