"""Explicit read-only collection using the existing iiko session, never a schedule."""
from datetime import datetime, timezone
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.sales.sync import source_identity
from app.schemas.product_knowledge import SourceProduct, SourceSnapshot, SourceUnit
from app.product_knowledge.bootstrap import PublicationError


async def collect(source_id: str) -> SourceSnapshot:
    settings = get_iiko_settings()
    if source_identity(settings) != source_id:
        raise PublicationError('IIKO_SOURCE_MISMATCH')
    client = IikoServerClient(settings)
    try:
        await client.authenticate()
        products = await client.get_products()
        units = await client.get_units()
        return SourceSnapshot(source_id=source_id, observed_at=datetime.now(timezone.utc),
            evidence='iiko products/includeDeleted + MeasureUnit, complete allowlist read', complete=True,
            products=[SourceProduct(id=p.dto.external_id, name=p.dto.name, sku=p.dto.sku or p.dto.code,
                main_unit=p.dto.base_unit_external_id, unit_weight_kg=p.raw_payload.get('unitWeight'),
                use_balance_for_sell=p.raw_payload.get('useBalanceForSell'), deleted=p.dto.is_deleted,
                source_type=p.dto.product_type or 'UNKNOWN', description=p.raw_payload.get('description') or None) for p in products],
            units=[SourceUnit(id=u.dto.external_id, name=u.dto.name) for u in units])
    finally:
        await client.aclose()
