import os
import unittest

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import User
from app.models.work_request import WorkRequest, WorkRequestAttachment
from app.requests.service import (
    WorkRequestNotFoundError,
    get_work_request,
    list_work_requests,
)


class WorkRequestRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        WorkRequestAttachment.__table__.create(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_repair_remains_active_while_warehouse_is_archived(self) -> None:
        with self.session_factory.begin() as session:
            repair = WorkRequest(
                request_type="repair",
                department="Авто",
                description="Не заводится",
                status="new",
                repair_category="Другое",
                priority="urgent",
            )
            warehouse = WorkRequest(
                request_type="warehouse",
                department="М15",
                description="Историческая строка",
                status="new",
                warehouse_category="products",
            )
            session.add_all([repair, warehouse])
            session.flush()
            repair_id = repair.id
            warehouse_id = warehouse.id

        with self.session_factory() as session:
            self.assertEqual(
                [item.id for item in list_work_requests(session)],
                [repair_id],
            )
            self.assertEqual(get_work_request(session, repair_id).id, repair_id)
            with self.assertRaises(WorkRequestNotFoundError):
                get_work_request(session, warehouse_id)


if __name__ == "__main__":
    unittest.main()
