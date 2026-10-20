"""Only direct, approved, dated, supplier/container-specific conversions. Never infer a factor."""
import copy
from datetime import datetime
from decimal import localcontext
from zoneinfo import ZoneInfo
from app.raw_materials.purchases import decimal


def normalize(documents, mapping):
    conversions=mapping.get('conversions', [])
    if not conversions:return documents
    rows=copy.deepcopy(documents)
    for doc in rows:
        try:
            stamp=datetime.fromisoformat(doc.get('dateIncoming',''))
            stamp=stamp.replace(tzinfo=ZoneInfo('Asia/Yekaterinburg')) if stamp.tzinfo is None else stamp.astimezone(ZoneInfo('Asia/Yekaterinburg'))
            day=stamp.date().isoformat()
        except (TypeError,ValueError):continue
        for item in doc['items']:
            if item.get('product')!=mapping['iiko_product_id']:continue
            container=item.get('containerId')
            if container in ('','00000000-0000-0000-0000-000000000000'):container=None
            if item.get('amountUnit')==mapping['unit_id'] and container is None:continue
            matches=[c for c in conversions if c['from_unit_id']==item.get('amountUnit') and c['to_unit_id']==mapping['unit_id']
                and c['supplier_iiko_id']==doc.get('supplier') and c.get('container_id')==container and c['valid_from']<=day<c['valid_to']]
            if len(matches)!=1:continue  # no match or ambiguity stays BLOCKED under existing quality checks
            c=matches[0];factor=decimal(c['factor']);amount=decimal(item.get('amount'));actual=decimal(item.get('actualAmount'))
            if factor is None or factor<=0 or amount is None or actual is None:continue
            item['original_line']=dict(item)
            with localcontext() as ctx:
                ctx.prec=80
                item.update(amount=str(amount*factor),actualAmount=str(actual*factor),amountUnit=mapping['unit_id'],containerId='')
            item['conversion']=dict(**c,specification_hash=mapping.get('specification_hash'))
    return rows
