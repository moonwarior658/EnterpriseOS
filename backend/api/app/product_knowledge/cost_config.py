"""K5C fixed source policy; replace this resolver when explicit mapping is approved."""
from uuid import UUID
from app.product_knowledge.bootstrap import PublicationError

WAREHOUSE_ID = UUID('1c22edc0-7ded-41c9-b781-0389462c7247')
WAREHOUSE_LABEL = 'Цех Производство ИП'
SOURCE_ID = '244d6eaf9c7c106993d10feb0ff9883dbdb73101cd3a2ab6852c9ba5b9907401'
SCOPE_EVIDENCE = 'Решение владельца 12.10.2026: единственный склад стоимости ингредиентов — Цех Производство; UUID проверен по iiko и маршруту внутреннего перемещения.'


def warehouse_for(source_id):
    if source_id != SOURCE_ID:
        raise PublicationError('COST_SOURCE_MISMATCH')
    return WAREHOUSE_ID


def require_scope(payload):
    if payload.warehouse_ids != [warehouse_for(payload.source_id)]:
        raise PublicationError('COST_FIXED_WAREHOUSE_REQUIRED')
