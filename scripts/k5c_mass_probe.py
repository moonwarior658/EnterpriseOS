"""Read-only K5C reconnaissance. Run in eos-api on stdin/in memory; no writes.

49 independently transcribed Office rows. UUID identity is resolved by article
and code, never by name; missing EOS items are not added to the catalog. Evidence uses UUID hashes, never credentials/raw
payloads. Stock context is exploratory, not an approved production mapping.
"""
import asyncio
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from zoneinfo import ZoneInfo


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


async def main():
    from sqlalchemy import create_engine, text
    from app.core.config import settings
    from app.integrations.iiko.config import get_iiko_settings
    from app.integrations.iiko.client import IikoServerClient

    engine = create_engine(settings.database_url)
    with engine.connect() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        candidates=list(db.execute(text('SELECT tenant_id,source_id,iiko_product_id,sku,name,unit_name '
            'FROM product_knowledge_products WHERE published AND deleted_at IS NULL')).mappings())
        source_set={(r['tenant_id'],r['source_id']) for r in candidates}
        from app.sales.sync import source_identity
        if len(source_set)!=1 or next(iter(source_set))[1]!=source_identity(get_iiko_settings()):
            raise ValueError('PROBE_SOURCE_MISMATCH')
        tenant,source=next(iter(source_set))
        head=list(db.execute(text('SELECT version_num FROM alembic_version')).scalars())
        stores=list(db.execute(text('SELECT iiko_warehouse_id,source_name,status,role FROM iiko_warehouse_mappings WHERE tenant_id=:tenant'),{'tenant':tenant}).mappings())
        db.rollback()
    engine.dispose()
    now = datetime.now(ZoneInfo('Asia/Yekaterinburg'))
    if now.date().isoformat() != OFFICE['effective_on']:
        raise ValueError('SCREENSHOT_DATE_DIFFERS_FROM_SYSTEM_DATE')
    out = dict(office_context=OFFICE['office_context'], missing_from_eos_catalog=[], head=head, observed_at=now.isoformat(), roots=[], stores=[
        dict(key=key(s['iiko_warehouse_id']), name=s['source_name'], status=s['status'], role=s['role']) for s in stores],
        requests=[], publication_allowed=False)
    config = get_iiko_settings().model_copy(update={'max_safe_retries': 0, 'request_timeout_seconds': 30.0})
    client = IikoServerClient(config)
    async def read(path, params):
        await client.authenticate()
        response = await client._raw_request('GET', path, params=params)
        out['requests'].append(dict(path=path, status=response.status_code, bytes=len(response.content)))
        if not response.is_success:
            return None
        if len(response.content) > 16 * 1024 * 1024:
            raise ValueError('PROBE_RESPONSE_LIMIT')
        return json.loads(response.text, parse_float=Decimal)
    try:
        units=await read('api/v2/entities/list',dict(rootType='MeasureUnit',includeDeleted='true'))
        out['units']=[dict(key=key(u['id']),name=u.get('name')) for u in units or []]
        raw_catalog=None
        for office in OFFICE['rows']:
            local=[r for r in candidates if r['sku']==office['article']]
            if len(local)>1:raise ValueError('EOS_ARTICLE_AMBIGUOUS')
            if local:
                root=str(local[0]['iiko_product_id'])
                source_rows=await read('api/v2/entities/products/list',[('ids',root),('includeDeleted','true')])
            else:
                out['missing_from_eos_catalog'].append(office['article'])
                if raw_catalog is None:raw_catalog=await client._product_payloads()
                source_rows=[p for p in raw_catalog if p.get('num')==office['article'] and p.get('code')==office['code']]
            if len(source_rows)!=1 or source_rows[0].get('num')!=office['article'] or source_rows[0].get('code')!=office['code']:
                raise ValueError('SOURCE_ARTICLE_CODE_MISMATCH')
            root=source_rows[0]['id']
            tree=await read('api/v2/assemblyCharts/getTree',dict(productId=root,date=now.date().isoformat()))
            charts=tree.get('assemblyCharts',[])
            ids={root} | {c['assembledProductId'] for c in charts} | {i['productId'] for c in charts for i in c['items']}
            if len(ids)>200:raise ValueError('PROBE_REFERENCE_LIMIT')
            refs=[];balances=[];ordered=sorted(ids)
            for offset in range(0,len(ordered),50):
                batch=ordered[offset:offset+50]
                refs+=await read('api/v2/entities/products/list',[('includeDeleted','true')]+[('ids',p) for p in batch]) or []
                balances+=await read('api/v2/reports/balance/stores',[('timestamp',now.strftime('%Y-%m-%dT%H:%M:%S'))]+[('product',p) for p in batch]) or []
            specific_ids=sorted({c['assembledProductId'] for c in charts if c.get('productSizeAssemblyStrategy')=='SPECIFIC'})
            scales={}
            for offset in range(0,len(specific_ids),50):
                batch=specific_ids[offset:offset+50]
                result=await read('api/v2/entities/products/productScales',[('productId',p) for p in batch])
                if not isinstance(result,dict) or set(result)!=set(batch):raise ValueError('PROBE_SIZE_SCALE_UNAVAILABLE')
                scales.update(result)
            out['roots'].append(dict(key=key(root),name=source_rows[0].get('name'),office=office,units=out['units'],
                charts=[dict(key=key(c['id']),root_key=key(c['assembledProductId']),assembledAmount=c.get('assembledAmount'),
                    dateFrom=c.get('dateFrom'),dateTo=c.get('dateTo'),writeoff=c.get('productWriteoffStrategy'),
                    direct_spec=c.get('effectiveDirectWriteoffStoreSpecification'),size_strategy=c.get('productSizeAssemblyStrategy'),
                    scale_absent=c['assembledProductId'] in scales and scales[c['assembledProductId']] is None,
                    items=[dict(product_key=key(i['productId']),amountIn=i.get('amountIn'),amountOut=i.get('amountOut'),
                        storeSpecification=i.get('storeSpecification'),size_specified=i.get('productSizeSpecification') is not None) for i in c['items']]) for c in charts],
                references=[dict(key=key(p['id']),num=p.get('num'),code=p.get('code'),name=p.get('name'),type=p.get('type'),
                    deleted=p.get('deleted'),mainUnit_key=key(p.get('mainUnit')),unitWeight=p.get('unitWeight'),estimatedPurchasePrice=p.get('estimatedPurchasePrice')) for p in refs],
                balances=[dict(scope='ALL_STORES_EXPLORATORY',rows=[dict(product_key=key(b['product']),store_key=key(b['store']),amount=b.get('amount'),sum=b.get('sum')) for b in balances])]))
            print('K5C_PROGRESS:'+office['article'],flush=True)
        fields = await read('api/v2/reports/olap/columns', {'reportType':'TRANSACTIONS'})
        out['transaction_fields'] = {k:dict(name=v.get('name'), type=v.get('type'),
            groupingAllowed=v.get('groupingAllowed'), aggregationAllowed=v.get('aggregationAllowed'),
            filteringAllowed=v.get('filteringAllowed')) for k,v in (fields or {}).items()
            if k in ('Product.Id','Product.MeasureUnit','Product.Cost','Product.AvgSum','Amount','Amount.In',
                'Sum.Incoming','Sum.Outgoing','FinalBalance.Money','FinalBalance.Amount','Store.Id','DateTime','DateTime.DateTyped')}
    finally:
        if client._token:
            response = await client._raw_request('GET','api/logout')
            out['logout_status'] = response.status_code
            client._token = None
        await client.aclose()
    # Store specifications may contain UUIDs; keep hashes, not API identifiers.
    def safe(value):
        if isinstance(value, Decimal): return str(value)
        if isinstance(value, dict): return {k:safe(v) for k,v in value.items()}
        if isinstance(value, list): return [safe(v) for v in value]
        if isinstance(value, str):
            from uuid import UUID
            try: return 'key:'+key(UUID(value))
            except ValueError: return value
        return value
    import base64, zlib
    print('K5C_B64_START'+base64.b64encode(zlib.compress(json.dumps(safe(out), ensure_ascii=True).encode())).decode()+'K5C_B64_END')


OFFICE = {'effective_on': '2026-10-09', 'office_context': 'ЦЕХ Полярная Производство', 'context_confirmed_by_user': True, 'warehouse_uuid_confirmed': False, 'rows': [{'article': '76214', 'code': '18474', 'ssn': '61.28', 'estimated': False}, {'article': '00241', 'code': '285', 'ssn': '25.88', 'estimated': False}, {'article': '75911', 'code': '18156', 'ssn': '39.05', 'estimated': False}, {'article': '75753', 'code': '17983', 'ssn': '45.50', 'estimated': False}, {'article': '75834', 'code': '18072', 'ssn': '26.62', 'estimated': False}, {'article': '74796', 'code': '16924', 'ssn': '26.06', 'estimated': False}, {'article': '75835', 'code': '18073', 'ssn': '31.38', 'estimated': False}, {'article': '75836', 'code': '18074', 'ssn': '31.91', 'estimated': False}, {'article': '00236', 'code': '280', 'ssn': '33.32', 'estimated': False}, {'article': '75837', 'code': '18075', 'ssn': '31.21', 'estimated': False}, {'article': '76409', 'code': '18674', 'ssn': '39.28', 'estimated': False}, {'article': '76397', 'code': '18661', 'ssn': '74.25', 'estimated': False}, {'article': '11612', 'code': '3570', 'ssn': '34.49', 'estimated': False}, {'article': '76387', 'code': '18650', 'ssn': '41.34', 'estimated': False}, {'article': '76347', 'code': '18609', 'ssn': '152.62', 'estimated': False}, {'article': '76065', 'code': '18315', 'ssn': '49.91', 'estimated': False}, {'article': '75751', 'code': '17981', 'ssn': '51.63', 'estimated': False}, {'article': '75919', 'code': '18164', 'ssn': '61.37', 'estimated': False}, {'article': '75951', 'code': '18198', 'ssn': '8.14', 'estimated': False}, {'article': '76060', 'code': '18310', 'ssn': '43.44', 'estimated': False}, {'article': '76354', 'code': '18616', 'ssn': '45.55', 'estimated': False}, {'article': '75913', 'code': '18158', 'ssn': '50.73', 'estimated': False}, {'article': '76366', 'code': '18629', 'ssn': '93.12', 'estimated': False}, {'article': '01412', 'code': '1619', 'ssn': '114.22', 'estimated': False}, {'article': '76410', 'code': '18675', 'ssn': '113.08', 'estimated': True}, {'article': '00152', 'code': '191', 'ssn': '27.29', 'estimated': False}, {'article': '75950', 'code': '18197', 'ssn': '38.25', 'estimated': False}, {'article': '75915', 'code': '18160', 'ssn': '60.99', 'estimated': False}, {'article': '75922', 'code': '18167', 'ssn': '96.05', 'estimated': False}, {'article': '76070', 'code': '18320', 'ssn': '90.34', 'estimated': False}, {'article': '12441', 'code': '4437', 'ssn': '70.93', 'estimated': False}, {'article': '75683', 'code': '17910', 'ssn': '21.96', 'estimated': False}, {'article': '00201', 'code': '245', 'ssn': '17.84', 'estimated': False}, {'article': '75685', 'code': '17912', 'ssn': '39.71', 'estimated': False}, {'article': '75690', 'code': '17917', 'ssn': '36.68', 'estimated': False}, {'article': '76243', 'code': '18504', 'ssn': '388.57', 'estimated': False}, {'article': '76242', 'code': '18503', 'ssn': '425.32', 'estimated': False}, {'article': '74872', 'code': '17007', 'ssn': '149.89', 'estimated': False}, {'article': '12425', 'code': '4421', 'ssn': '246.12', 'estimated': False}, {'article': '75810', 'code': '18046', 'ssn': '312.29', 'estimated': False}, {'article': '13756', 'code': '5843', 'ssn': '336.20', 'estimated': False}, {'article': '75957', 'code': '18204', 'ssn': '356.68', 'estimated': False}, {'article': '75806', 'code': '18042', 'ssn': '309.28', 'estimated': False}, {'article': '75800', 'code': '18036', 'ssn': '313.16', 'estimated': False}, {'article': '75808', 'code': '18044', 'ssn': '278.44', 'estimated': False}, {'article': '76411', 'code': '18676', 'ssn': '469.05', 'estimated': False}, {'article': '76069', 'code': '18319', 'ssn': '767.59', 'estimated': False}, {'article': '75802', 'code': '18038', 'ssn': '404.40', 'estimated': False}, {'article': '11602', 'code': '3560', 'ssn': '1188.18', 'estimated': False}]}

if __name__ == '__main__':
    asyncio.run(main())
