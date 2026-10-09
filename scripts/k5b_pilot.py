"""Operator-only K5B tools. Resolve/preflight/export are DB read-only; enqueue is explicit.
Run inside eos-api with the script on stdin; never creates a schedule or a full batch.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

TARGETS = ('5fcc771dd5101343', 'b22356f1bc446f77', '47d5bdfb4b6f1aa7')
DEPARTMENT_KEY = 'a8e0fe727d8767fd'
PROTECTED = ('product_knowledge_products', 'product_knowledge_prices',
             'product_knowledge_price_snapshots', 'supply_products')


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def resolve_rows(products, departments):
    found = {}
    for target in TARGETS:
        matches = [p for p in products if key(p['iiko_product_id']) == target]
        if len(matches) != 1:
            raise ValueError('K5A_UUID_NOT_UNIQUE:' + target)
        found[target] = dict(matches[0])
    sources = {(p['tenant_id'], p['source_id']) for p in found.values()}
    if len(sources) != 1:
        raise ValueError('K5A_SOURCE_NOT_UNIQUE')
    tenant, source = next(iter(sources))
    matches = [d for d in departments if d['tenant_id'] == tenant and key(d['olap_department_id']) == DEPARTMENT_KEY]
    if len(matches) != 1:
        raise ValueError('K5A_DEPARTMENT_NOT_UNIQUE')
    # K5A used this UUID directly in departmentId. No substitution by name,
    # EOS department ID, or the distinct corporation/groups UUID.
    return dict(tenant_id=tenant, source_id=source, department_id=str(matches[0]['olap_department_id']),
                department_eos_id=str(matches[0]['eos_department_id']), products=found,
                warehouse_id=None, size_id=None)


def database_snapshot(db):
    from sqlalchemy import text
    result = {}
    for table in PROTECTED:
        rows = list(db.execute(text(f'SELECT row_to_json(t)::text FROM {table} t ORDER BY id')).scalars())
        result[table] = dict(count=len(rows), sha256=checksum(rows))
    return result


@contextmanager
def database_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.config import settings
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def read_report(mode, args):
    from sqlalchemy import text
    with database_session() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        if mode == 'preflight':
            head = list(db.execute(text('SELECT version_num FROM alembic_version')).scalars())
            collisions = list(db.execute(text("""SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND relname IN ('product_recipe_versions','product_recipe_observations')
                UNION ALL SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname=current_schema() AND proname='reject_recipe_mutation'""")).scalars())
            privileges = dict(db.execute(text("""SELECT
                has_schema_privilege(current_user,current_schema(),'CREATE') AS schema_create,
                has_language_privilege(current_user,'plpgsql','USAGE') AS plpgsql_usage,
                has_table_privilege(current_user,'sales_sync_states','REFERENCES') AS source_references,
                has_table_privilege(current_user,'product_knowledge_products','REFERENCES') AS product_references
                """)).mappings().one())
            if not all(privileges.values()):
                raise ValueError('K5B_MIGRATION_PRIVILEGES_REQUIRED')
            if head != ['20261009_0077'] or collisions:
                raise ValueError('K5B_PREFLIGHT_HEAD_OR_OBJECT_COLLISION')
            return dict(head=head, collisions=collisions, privileges=privileges, protected=database_snapshot(db))
        if mode == 'resolve':
            products = list(db.execute(text("""SELECT id,tenant_id,source_id,iiko_product_id,name,unit_id,unit_name
                FROM product_knowledge_products WHERE published AND deleted_at IS NULL""")).mappings())
            departments = list(db.execute(text('SELECT tenant_id,olap_department_id,eos_department_id FROM iiko_department_mappings')).mappings())
            result = resolve_rows(products, departments)
            result['protected'] = database_snapshot(db)
            result['head'] = list(db.execute(text('SELECT version_num FROM alembic_version')).scalars())
            result['recipe_schedule_count'] = db.scalar(text("SELECT count(*) FROM automation_schedules WHERE automation_type='products.sync_iiko_recipes'"))
            return result
        if mode == 'export':
            from app.models.product_recipe import ProductRecipeObservation, ProductRecipeVersion
            from app.models.automation import AutomationExecution
            from sqlalchemy import select
            execution = db.scalar(select(AutomationExecution).where(AutomationExecution.execution_id == UUID(args.execution)))
            if execution is None or execution.automation_type != 'products.sync_iiko_recipes':
                raise ValueError('K5B_EXECUTION_NOT_FOUND')
            rows = list(db.scalars(select(ProductRecipeObservation).where(
                ProductRecipeObservation.tenant_id == execution.tenant_id,
                ProductRecipeObservation.execution_id == execution.execution_id).order_by(ProductRecipeObservation.product_id)))
            version_ids = {UUID(v['version_id']) for row in rows for v in row.payload['manifest']}
            versions = list(db.scalars(select(ProductRecipeVersion).where(
                ProductRecipeVersion.tenant_id == execution.tenant_id, ProductRecipeVersion.id.in_(version_ids))))
            return dict(execution_id=str(execution.execution_id), status=execution.status.value,
                payload=execution.payload, result=execution.result, error_code=execution.error_code,
                observations=[dict(id=str(r.id),product_id=str(r.product_id),effective_on=str(r.effective_on),
                    observed_at=r.observed_at.isoformat(),status=r.status,payload=r.payload) for r in rows],
                versions=[dict(id=str(v.id),source_id=v.source_id,chart_id=str(v.chart_id),
                    source_product_id=str(v.source_product_id),kind=v.kind,content_hash=v.content_hash,payload=v.payload) for v in versions],
                protected=database_snapshot(db))
        raise ValueError('READ_MODE_INVALID')


def queue_pilot(args):
    from app.models.user import User
    from app.product_knowledge.recipes import RecipeRefreshPayload, enqueue
    resolved = read_report('resolve', args)
    if resolved['head'] != ['20261009_0078'] or resolved['recipe_schedule_count'] != 0:
        raise ValueError('PILOT_REQUIRES_0078_AND_NO_RECIPE_SCHEDULE')
    data = dict(source_id=resolved['source_id'],department_id=resolved['department_id'],
        product_ids=[str(resolved['products'][k]['iiko_product_id']) for k in TARGETS],
        effective_on=args.date, scope_evidence='K5A controlled pilot; source UUID hash confirmed; Office acceptance pending',
        warehouse_id=None,size_id=None)
    payload = RecipeRefreshPayload.model_validate(data)
    with database_session() as db:
        with db.begin():
            actor = db.get(User,args.actor)
            if actor is None or actor.tenant_id != resolved['tenant_id']:
                raise ValueError('PILOT_ACTOR_TENANT_INVALID')
            execution = enqueue(db,actor,payload)
            identity = str(execution.execution_id)
    return dict(accepted=True,execution_id=identity,payload=payload.model_dump(mode='json'),
        resolved=resolved,ready_for_production=False)


def compare_runs(first, second):
    if first['status'] != 'succeeded' or second['status'] != 'succeeded':
        raise ValueError('PILOT_EXECUTION_NOT_SUCCEEDED')
    if first['execution_id'] == second['execution_id'] or first['payload'] != second['payload']:
        raise ValueError('PILOT_REPEAT_SCOPE_INVALID')
    a = {r['product_id']:r for r in first['observations']}
    b = {r['product_id']:r for r in second['observations']}
    if not a or set(a) != set(b):
        raise ValueError('PILOT_COVERAGE_CHANGED')
    unchanged = all(a[p]['id'] != b[p]['id'] and a[p]['status'] == b[p]['status'] and
        a[p]['payload']['manifest_hash'] == b[p]['payload']['manifest_hash'] for p in a)
    version_ids_equal = {v['id'] for v in first['versions']} == {v['id'] for v in second['versions']}
    protected_equal = first['protected'] == second['protected']
    return dict(repeat_unchanged=unchanged,content_versions_reused=version_ids_equal,
        protected_equal=protected_equal,passed=unchanged and version_ids_equal and protected_equal,
        ready_for_production=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['preflight','resolve','enqueue','export','compare'])
    parser.add_argument('--actor',type=int)
    parser.add_argument('--date')
    parser.add_argument('--execution')
    parser.add_argument('--first')
    parser.add_argument('--second')
    args=parser.parse_args()
    if args.mode=='enqueue':
        if not args.actor or not args.date: parser.error('enqueue requires explicit --actor and --date')
        result=queue_pilot(args)
    elif args.mode=='compare':
        if not args.first or not args.second: parser.error('compare requires two private export files')
        result=compare_runs(json.loads(Path(args.first).read_text(encoding='utf-8-sig')),
                            json.loads(Path(args.second).read_text(encoding='utf-8-sig')))
    else:
        if args.mode=='export' and not args.execution: parser.error('export requires --execution')
        result=read_report(args.mode,args)
    print(json.dumps(result,ensure_ascii=False,default=str,indent=2))

if __name__=='__main__':
    main()
