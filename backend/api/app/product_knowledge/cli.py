"""Run locally against an explicitly selected DB. Default command is read-only preview."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID
from sqlalchemy import text
from app.db.session import SessionLocal
from app.models.user import User
from app.product_knowledge.bootstrap import preview, publish, rollback_publication, PublicationError
from app.schemas.product_knowledge import SourceSnapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['collect', 'preview', 'publish', 'rollback'])
    parser.add_argument('--tenant', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--actor-id', type=int)
    parser.add_argument('--expected-hash')
    parser.add_argument('--initial-status', choices=['ON_SALE','OFF_SALE'])
    parser.add_argument('--confirmed-point', type=UUID, action='append', default=[])
    parser.add_argument('--batch-id', type=UUID)
    args = parser.parse_args()
    try:
        if args.command == 'collect':
            if not args.snapshot:
                raise PublicationError('SNAPSHOT_OUTPUT_REQUIRED')
            from app.product_knowledge.snapshot import collect
            snapshot = asyncio.run(collect(args.source))
            args.snapshot.write_text(snapshot.model_dump_json(indent=2))
            print('SOURCE_SNAPSHOT_COLLECTED')
            return
        with SessionLocal() as db:
            if args.command == 'rollback':
                actor = db.get(User, args.actor_id) if args.actor_id else None
                if not actor or actor.tenant_id != args.tenant or not args.batch_id:
                    raise PublicationError('ACTOR_AND_BATCH_REQUIRED')
                batch = rollback_publication(db, actor, args.batch_id)
                if batch.source_id != args.source:
                    raise PublicationError('SOURCE_MISMATCH')
                db.commit()
                print(json.dumps({'batch_id':str(batch.id), 'rolled_back':True}))
                return
            if not args.snapshot:
                raise PublicationError('SNAPSHOT_REQUIRED')
            snapshot = SourceSnapshot.model_validate_json(args.snapshot.read_text())
            if args.command == 'preview' and db.bind.dialect.name == 'postgresql':
                db.execute(text('SET TRANSACTION READ ONLY'))
            report = preview(db, args.tenant, args.source, snapshot)
            if args.command == 'preview':
                if args.report:
                    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                db.rollback()
                print(json.dumps({k:v for k,v in report.items() if k not in {'rows','point_day_coverage'}},ensure_ascii=False))
            else:
                actor = db.get(User, args.actor_id) if args.actor_id else None
                if not actor or not args.expected_hash or not args.initial_status:
                    raise PublicationError('ACTOR_REVIEW_HASH_AND_STATUS_REQUIRED')
                batch = publish(db, actor, report, expected_hash=args.expected_hash,
                    initial_status=args.initial_status, confirmed_point_ids=args.confirmed_point)
                db.commit()
                print(json.dumps({'batch_id':str(batch.id),'plan_hash':batch.plan_hash}))
    except PublicationError as error:
        parser.exit(2, str(error)+'\n')
    except Exception:
        # Never expose DB URLs, input payloads, validation internals or stack traces.
        parser.exit(2, 'PRODUCT_KNOWLEDGE_OPERATION_FAILED\n')


if __name__ == '__main__':
    main()
