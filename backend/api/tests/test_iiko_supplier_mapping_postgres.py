import os
import threading
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.integrations.iiko.supplier_mapping_service import (
    SupplierMappingError,
    confirm_supplier_mapping,
)
from app.models.iiko import (
    IikoRawEntity,
    IikoSupplierMapping,
    IikoSupplierMappingStatus,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
)
from app.models.supply import SupplySupplier
from app.models.user import User


class IikoSupplierMappingPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        database_url = os.environ.get("SUPPLY_TEST_DATABASE_URL")
        if not database_url:
            raise unittest.SkipTest("SUPPLY_TEST_DATABASE_URL is not set")
        parsed = make_url(database_url)
        if parsed.host not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("Supplier mapping PostgreSQL test requires localhost")
        if parsed.database != "eos_supply_migration_test":
            raise RuntimeError("Supplier mapping PostgreSQL test requires disposable database")
        cls.engine = create_engine(database_url, pool_size=5)
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.tenant = f"supplier-map-{uuid4()}"
        self.external_ids = [uuid4(), uuid4()]
        with self.sessions.begin() as session:
            user = User(
                username=f"admin-{uuid4()}", display_name="Admin",
                hashed_password="unused", is_active=True, is_admin=True,
                tenant_id=self.tenant,
            )
            suppliers = [
                SupplySupplier(tenant_id=self.tenant, display_name=f"Supplier {index}")
                for index in range(3)
            ]
            run = IikoSyncRun(
                tenant_id=self.tenant,
                sync_type=IikoSyncType.FULL_REFERENCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="test",
            )
            session.add_all([user, *suppliers, run])
            session.flush()
            self.user_id = user.id
            self.supplier_ids = [supplier.id for supplier in suppliers]
            session.add_all([
                IikoRawEntity(
                    tenant_id=self.tenant, sync_run_id=run.id,
                    entity_type="supplier", external_id=str(external_id),
                    payload={
                        "id": str(external_id), "name": f"iiko {index}",
                        "code": f"S{index}", "supplier": True,
                        "employee": False, "representsStore": False,
                        "deleted": False,
                    },
                    payload_hash=uuid4().hex, is_active=True,
                )
                for index, external_id in enumerate(self.external_ids)
            ])

    def test_fk_remap_history_and_concurrent_external_uniqueness(self) -> None:
        with self.sessions() as session:
            session.add(IikoSupplierMapping(
                tenant_id=self.tenant,
                supplier_id=uuid4(),
                iiko_supplier_id=uuid4(),
                iiko_supplier_name="Wrong tenant target",
                created_by_user_id=self.user_id,
            ))
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()

        with self.sessions() as session:
            first = confirm_supplier_mapping(
                session, tenant_id=self.tenant,
                supplier_id=self.supplier_ids[0],
                iiko_supplier_id=self.external_ids[0],
                actor_user_id=self.user_id,
            )
            second = confirm_supplier_mapping(
                session, tenant_id=self.tenant,
                supplier_id=self.supplier_ids[0],
                iiko_supplier_id=self.external_ids[1],
                actor_user_id=self.user_id,
            )
            history = list(session.scalars(select(IikoSupplierMapping).where(
                IikoSupplierMapping.tenant_id == self.tenant,
                IikoSupplierMapping.supplier_id == self.supplier_ids[0],
            )))
            archived = next(item for item in history if item.id == first.id)
            self.assertEqual(archived.status, IikoSupplierMappingStatus.ARCHIVED)
            self.assertEqual(archived.superseded_by_id, second.id)

        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker(supplier_id):
            with self.sessions() as session:
                barrier.wait()
                try:
                    confirm_supplier_mapping(
                        session, tenant_id=self.tenant,
                        supplier_id=supplier_id,
                        iiko_supplier_id=self.external_ids[0],
                        actor_user_id=self.user_id,
                    )
                    outcome = "created"
                except SupplierMappingError:
                    outcome = "rejected"
            with lock:
                outcomes.append(outcome)

        threads = [
            threading.Thread(target=worker, args=(supplier_id,))
            for supplier_id in self.supplier_ids[1:]
        ]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(sorted(outcomes), ["created", "rejected"])
        with self.sessions() as session:
            active_count = session.scalar(select(func.count()).select_from(
                IikoSupplierMapping,
            ).where(
                IikoSupplierMapping.tenant_id == self.tenant,
                IikoSupplierMapping.iiko_supplier_id == self.external_ids[0],
                IikoSupplierMapping.status == IikoSupplierMappingStatus.CONFIRMED,
            ))
        self.assertEqual(active_count, 1)
