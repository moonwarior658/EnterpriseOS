"""Read-only K5C reconnaissance. Run in eos-api on stdin/in memory; no writes.

Four screenshot products only. Name selection locates research candidates and
does not create any mapping. Evidence uses UUID hashes, never credentials/raw
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
        head = list(db.execute(text('SELECT version_num FROM alembic_version')).scalars())
        candidates = list(db.execute(text('SELECT tenant_id,source_id,iiko_product_id,name,unit_name '
            'FROM product_knowledge_products WHERE published AND deleted_at IS NULL')).mappings())
        # Existing EOS UUID hashes located in the read-only discovery pass.
        targets = ('0ea35d0437aba09f', '644426929e9e917f', '4346d8f830d17e6c', '2a411f2751bc9ad7')
        roots = []
        for target in targets:
            found = [r for r in candidates if key(r['iiko_product_id']) == target]
            if len(found) != 1:
                raise ValueError('PROBE_SCREENSHOT_CANDIDATE_NOT_UNIQUE:'+target)
            roots.append(found[0])
        sources = {(r['tenant_id'],r['source_id']) for r in roots}
        from app.sales.sync import source_identity
        if len(sources) != 1 or next(iter(sources))[1] != source_identity(get_iiko_settings()):
            raise ValueError('PROBE_SOURCE_MISMATCH')
        stores = list(db.execute(text('SELECT iiko_warehouse_id,source_name,status,role '
            'FROM iiko_warehouse_mappings WHERE tenant_id=:tenant ORDER BY id'),
            {'tenant':next(iter(sources))[0]}).mappings())
        db.rollback()
    engine.dispose()
    now = datetime.now(ZoneInfo('Asia/Yekaterinburg'))
    out = dict(head=head, observed_at=now.isoformat(), roots=[], stores=[
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
        for row in roots:
            root = str(row['iiko_product_id'])
            tree = await read('api/v2/assemblyCharts/getTree', dict(productId=root,
                date=now.date().isoformat()))
            charts = tree.get('assemblyCharts', []) if tree else []
            ids = {root} | {i['productId'] for c in charts for i in c.get('items', [])}
            if len(ids) > 50:
                raise ValueError('PROBE_REFERENCE_LIMIT')
            refs = await read('api/v2/entities/products/list', [('ids', p) for p in sorted(ids)] + [('includeDeleted','true')])
            prepared = await read('api/v2/assemblyCharts/getPrepared', dict(productId=root,
                date=now.date().isoformat()))
            entry = dict(key=key(root), name=row['name'], unit=row['unit_name'], recipe_status='OFFICE_COMPARISON_PENDING',
                department_key=None, warehouse_key=None,
                charts=[dict(key=key(c['id']), root_key=key(c['assembledProductId']),
                    assembledAmount=c.get('assembledAmount'), writeoff=c.get('productWriteoffStrategy'),
                    dateFrom=c.get('dateFrom'), dateTo=c.get('dateTo'),
                    items=[dict(product_key=key(i['productId']), amountIn=i.get('amountIn'),
                        amountOut=i.get('amountOut'), storeSpecification=i.get('storeSpecification'),
                        size_specified=i.get('productSizeSpecification') is not None) for i in c.get('items',[])]) for c in charts],
                references=[dict(key=key(p['id']), type=p.get('type'), mainUnit_key=key(p.get('mainUnit')),
                    num=p.get('num'), name=p.get('name'), unitWeight=p.get('unitWeight'), estimatedPurchasePrice=p.get('estimatedPurchasePrice'),
                    cost_fields={k:v for k,v in p.items() if 'cost' in k.lower()}) for p in refs or []],
                prepared_keys=sorted(prepared.keys()) if prepared else None,
                prepared_sample=[dict(keys=sorted(c.keys()), assembledAmount=c.get('assembledAmount'),
                    items=[dict(product_key=key(i['productId']), amount=i.get('amount'), amountIn=i.get('amountIn'),
                        keys=sorted(i.keys())) for i in c.get('items',[])]) for c in (prepared or {}).get('preparedCharts',[])],
                balances=[])
            # Bounded product scope across stores; no inferred production mapping.
            data = await read('api/v2/reports/balance/stores', [('timestamp',now.strftime('%Y-%m-%dT%H:%M:%S'))]
                + [('product',p) for p in sorted(ids)])
            entry['balances'].append(dict(store_key=None, scope='ALL_STORES_EXPLORATORY',
                rows=[dict(product_key=key(b.get('product')), store_key=key(b.get('store')),
                    amount=b.get('amount'), sum=b.get('sum'), keys=sorted(b.keys())) for b in data or []]))
            out['roots'].append(entry)
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


if __name__ == '__main__':
    asyncio.run(main())
