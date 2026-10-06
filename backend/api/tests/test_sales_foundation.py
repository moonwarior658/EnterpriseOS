import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch, AsyncMock

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import select, func
from app.models.employee import Employee, IikoEmployeeLink, IikoDepartmentMapping
from app.models.iiko import IikoProductMapping
from app.models.sales import SalesFact, SalesSyncState, SalesDaySync
from app.models.supply import Department, DepartmentBusinessType, SupplyProduct
from app.models.user import User
from app.sales.service import daily_query, ingest_day, reconcile, seller_orders, sync_health, SalesContractError
from app.sales.sync import sync_sales, source_identity
from app.integrations.iiko.config import IikoSettings
from tests import test_employee_iiko_identity as identity_fixture

NOW = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
DAY = date(2026, 10, 5)


class SalesFoundationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        identity_fixture.EmployeeIikoIdentityTests.setUp(self)
        for model in (SupplyProduct, IikoProductMapping, SalesSyncState, SalesDaySync, SalesFact):
            model.__table__.create(self.engine)
        self.point, self.order, self.product = uuid4(), uuid4(), uuid4()
        self.source_id = "a" * 64
        with self.sessions.begin() as db:
            db.get(Department, self.department_id).business_type = DepartmentBusinessType.RETAIL_POINT
            db.add(SalesSyncState(tenant_id="eclair", source_id=self.source_id,
                                 source_timezone="Asia/Yekaterinburg", history_from=DAY, backfill_next=DAY))
            db.add(IikoDepartmentMapping(tenant_id="eclair", iiko_department_id=uuid4(),
                olap_department_id=self.point, eos_department_id=self.department_id,
                reason="explicit", decided_by_user_id=1))
            db.add(IikoEmployeeLink(tenant_id="eclair", employee_id=self.employee_id,
                iiko_user_id="cashier", iiko_display_name="raw", valid_from=self.started,
                reason="explicit", created_by_user_id=1))

    def tearDown(self):
        self.engine.dispose()

    def row(self, **changes):
        result = {"Department.Id": str(self.point), "UniqOrderId.Id": str(self.order),
            "ItemSaleEvent.Id": str(uuid4()), "DishId": str(self.product),
            "OpenDate.Typed": DAY.isoformat(), "OpenTime": "2026-10-05T10:00:00",
            "CloseTime": "2026-10-05T10:01:00", "Cashier.Id": "cashier",
            "OrderWaiter.Id": "order-waiter", "WaiterName.ID": "item-waiter",
            "DishAmountInt": 2, "DishSumInt": 300, "DishDiscountSumInt": 280,
            "DishReturnSum": 0, "Storned": "FALSE", "OrderDeleted": "NOT_DELETED",
            "DeletedWithWriteoff": "NOT_DELETED"}
        result.update(changes)
        return result

    def ingest(self, rows, day=DAY):
        with self.sessions.begin() as db:
            return ingest_day(db, rows, state=db.get(SalesSyncState, ("eclair", self.source_id)),
                              day=day, department_ids=[self.point], seen_at=NOW)

    def orders(self):
        with self.sessions() as db:
            return reconcile(db, db.get(SalesSyncState, ("eclair", self.source_id)))

    def test_ingestion_repeat_update_disappearance(self):
        row = self.row(DishAmountInt=Decimal("1.25"), DishDiscountSumInt=Decimal("123.4567"))
        self.ingest([row]); self.ingest([row])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SalesFact)), 1)
            fact = db.scalar(select(SalesFact))
            self.assertEqual(fact.employee_id, self.employee_id)
            self.assertEqual((fact.order_waiter_id, fact.item_waiter_id), ("order-waiter", "item-waiter"))
        row["DishDiscountSumInt"] = 120; self.ingest([row])
        self.assertEqual(self.orders()[0].revenue, 120)
        self.ingest([]); self.assertEqual(self.orders(), [])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SalesFact)), 1)

    def test_invalid_or_duplicate_response_is_atomic(self):
        row = self.row(); self.ingest([row])
        for rows in ([row, row], [self.row(DishAmountInt="NaN")], [self.row(**{"Department.Id": str(uuid4())})]):
            with self.assertRaises(SalesContractError): self.ingest(rows)
        self.assertEqual(self.orders()[0].revenue, 280)

    def test_full_return_same_order(self):
        self.ingest([self.row(Storned="TRUE"), self.row(Storned="TRUE", DishAmountInt=-2,
            DishSumInt=-300, DishDiscountSumInt=-280, DishReturnSum=280)])
        order = self.orders()[0]
        self.assertTrue(order.excluded)
        self.assertEqual((order.revenue, order.quantity), (0, 0))

    def test_partial_cross_day_deleted_refund(self):
        self.ingest([self.row(DishAmountInt=20, DishDiscountSumInt=3200)])
        refund = self.row(**{"UniqOrderId.Id": str(uuid4()), "SourceOrderId": str(self.order),
            "OpenDate.Typed": "2026-10-06", "OpenTime": "2026-10-06T12:00:00",
            "DishAmountInt": -10, "DishDiscountSumInt": 0, "DishReturnSum": 1600,
            "Storned": "TRUE", "DeletedWithWriteoff": "DELETED_WITH_WRITEOFF",
            "Cashier.Id": "different-cashier"})
        self.ingest([refund], date(2026, 10, 6)); self.ingest([refund], date(2026, 10, 6))
        orders = self.orders(); self.assertEqual(len(orders), 1)
        self.assertEqual((orders[0].revenue, orders[0].quantity), (1600, 10))
        self.assertEqual((orders[0].business_date, orders[0].employee_id), (DAY, self.employee_id))

    def test_signed_refund_not_subtracted_twice(self):
        self.ingest([self.row(), self.row(DishAmountInt=-1, DishDiscountSumInt=-140,
            DishReturnSum=140, Storned="TRUE")])
        self.assertEqual(self.orders()[0].revenue, 140)

    def test_free_only_excluded_from_fullness(self):
        self.ingest([self.row(), self.row(DishAmountInt=3, DishDiscountSumInt=0)])
        order = self.orders()[0]
        self.assertEqual((order.quantity, order.fullness_quantity, order.revenue), (5, 2, 280))
        self.assertFalse(order.excluded)

    def test_missing_original_not_counted(self):
        self.ingest([self.row(**{"SourceOrderId": str(uuid4()), "DishAmountInt": -1,
            "DishDiscountSumInt": 0, "DishReturnSum": 140, "Storned": "TRUE"})])
        self.assertEqual(self.orders(), [])

    def test_seller_identity_rechecked(self):
        self.ingest([self.row()])
        with self.sessions.begin() as db:
            db.get(Employee, self.admin_employee_id).linked_user_id = None
            db.flush()
            db.get(Employee, self.employee_id).linked_user_id = 1
        with self.sessions() as db:
            state, user = db.get(SalesSyncState, ("eclair", self.source_id)), db.get(User, 1)
            self.assertEqual(len(seller_orders(db, state, user=user)), 1)
        with self.sessions.begin() as db:
            db.scalar(select(IikoEmployeeLink).where(IikoEmployeeLink.iiko_user_id == "cashier")).valid_from = NOW
        with self.sessions() as db:
            self.assertEqual(seller_orders(db, db.get(SalesSyncState, ("eclair", self.source_id)), user=db.get(User, 1)), [])
        self.ingest([self.row(**{"Cashier.Id": "unknown"})]); self.assertIsNone(self.orders()[0].employee_id)

    def test_point_namespace_is_explicit(self):
        with self.sessions.begin() as db:
            mapping = db.scalar(select(IikoDepartmentMapping))
            mapping.iiko_department_id, mapping.olap_department_id = self.point, None
        self.ingest([self.row()]); self.assertIsNone(self.orders()[0].department_id)

    def test_query_and_health(self):
        query = daily_query(DAY, [self.point])
        self.assertFalse(query["buildSummary"])
        self.assertNotIn("OperationType", query["groupByRowFields"])
        self.assertEqual(query["filters"]["OpenDate.Typed"]["to"], "2026-10-06T00:00:00.000")
        self.assertFalse(query["filters"]["OpenDate.Typed"]["includeHigh"])
        with self.sessions() as db:
            state = db.get(SalesSyncState, ("eclair", self.source_id))
            self.assertTrue(sync_health(state, now=NOW)["stale"])
            state.last_success_at = NOW; self.assertEqual(sync_health(state, now=NOW)["state"], "ok")
            self.assertTrue(sync_health(state, now=NOW+timedelta(minutes=31))["stale"])
            state.error_code = "SALES_SYNC_FAILED"; self.assertEqual(sync_health(state, now=NOW)["state"], "error")

    async def test_sync_repeat_and_error_keeps_last_success(self):
        settings = IikoSettings(enabled=True, base_url="https://example.invalid/resto/", login="test", password="test")
        sid = source_identity(settings)
        with self.sessions.begin() as db: db.get(SalesSyncState, ("eclair", self.source_id)).source_id = sid
        self.source_id = sid
        client = AsyncMock(); row = self.row()
        client.get_sales_olap.side_effect = lambda body: [row] if body["filters"]["OpenDate.Typed"]["from"].startswith(str(DAY)) else []
        client.__aenter__.return_value = client
        with patch("app.sales.sync.get_iiko_settings", return_value=settings), patch("app.sales.sync.IikoServerClient", return_value=client):
            await sync_sales(self.sessions, tenant_id="eclair", source_id=sid, now=NOW)
            await sync_sales(self.sessions, tenant_id="eclair", source_id=sid, now=NOW)
            self.assertEqual(len(self.orders()), 1)
            client.get_sales_olap.side_effect = RuntimeError("secret must not appear")
            with self.assertRaisesRegex(SalesContractError, "^SALES_SYNC_FAILED$"):
                await sync_sales(self.sessions, tenant_id="eclair", source_id=sid, now=NOW+timedelta(minutes=15))
        with self.sessions() as db:
            state = db.get(SalesSyncState, ("eclair", sid))
            self.assertEqual(state.last_success_at.replace(tzinfo=timezone.utc), NOW)
            self.assertEqual(state.error_code, "SALES_SYNC_FAILED")

    def test_a0_anonymized_control_and_returns(self):
        import json
        from pathlib import Path
        data = json.loads((Path(__file__).parent / "fixtures/sales_a0_events.json").read_text())
        rows = data["canonical_ingestion"]
        for row in rows: row["Department.Id"] = str(self.point)
        self.ingest(rows)
        orders = [o for o in self.orders() if not o.excluded]
        self.assertEqual(len(orders), 86)
        self.assertEqual(sum(o.revenue for o in orders), 71090)
        self.assertEqual(sum(o.quantity for o in orders), 293)
        self.assertEqual(sum(o.fullness_quantity for o in orders), 290)
        with self.sessions.begin() as db:
            for fact in db.scalars(select(SalesFact)).all(): fact.is_present = False
        rows = data["canonical_returns"]
        for day in sorted({date.fromisoformat(r["OpenDate.Typed"]) for r in rows}):
            selected = [dict(r, **{"Department.Id": str(self.point)}) for r in rows if r["OpenDate.Typed"] == str(day)]
            self.ingest(selected, day)
        orders = self.orders()
        self.assertEqual(len(orders), 2)
        self.assertEqual(sum(not o.excluded for o in orders), 1)
        remaining = next(o for o in orders if not o.excluded)
        self.assertEqual((remaining.revenue, remaining.quantity), (1600, 10))
        self.assertEqual(remaining.fullness_quantity, 10)

    async def test_http_olap_contract_and_exact_decimal(self):
        import httpx
        import json
        from app.integrations.iiko.client import IikoServerClient
        from app.integrations.iiko.exceptions import IikoContractError, IikoAuthenticationError, IikoAuthorizationError
        settings = IikoSettings(enabled=True, base_url="https://example.invalid/resto", login="test", password="test")
        requests = []
        status = 200
        content = '{"data":[{"DishDiscountSumInt":123.456789123456789}]}'
        def handler(request):
            if request.url.path.endswith('/auth'): return httpx.Response(200, text="token")
            if request.url.path.endswith('/logout'): return httpx.Response(200, text="ok")
            requests.append(request)
            return httpx.Response(status, text=content)
        async with IikoServerClient(settings, transport=httpx.MockTransport(handler)) as client:
            rows = await client.get_sales_olap(daily_query(DAY, [self.point]))
            self.assertEqual(rows[0]["DishDiscountSumInt"], Decimal("123.456789123456789"))
            for code, error in ((401, IikoAuthenticationError), (403, IikoAuthorizationError)):
                status = code
                with self.assertRaises(error): await client.get_sales_olap(daily_query(DAY, [self.point]))
            status, content = 200, '{"data":{}}'
            with self.assertRaises(IikoContractError): await client.get_sales_olap(daily_query(DAY, [self.point]))
        self.assertEqual(requests[0].url.path, '/resto/api/v2/reports/olap')
        self.assertEqual(requests[0].url.params['key'], 'token')
        self.assertEqual(json.loads(requests[0].content)["buildSummary"], False)

    def test_sales_schedule_contract(self):
        from pydantic import ValidationError
        from app.schemas.automation import AutomationScheduleCreate
        body = dict(recipients=[], name="Sales", automation_type="sales.sync_iiko", schedule_config={"type":"interval","minutes":15}, payload={"source_id":"a"*64})
        self.assertEqual(AutomationScheduleCreate(**body).schedule_config.minutes, 15)
        body["schedule_config"]["minutes"] = 10
        with self.assertRaises(ValidationError): AutomationScheduleCreate(**body)

    def test_linked_full_return_and_free_return(self):
        self.ingest([self.row(DishDiscountSumInt=0), self.row(DishAmountInt=-2,
            DishDiscountSumInt=0, Storned="TRUE")])
        order = self.orders()[0]
        self.assertTrue(order.excluded)
        self.assertIsNone(order.issue)
        original = self.row()
        refund = self.row(**{"UniqOrderId.Id":str(uuid4()), "SourceOrderId":str(self.order),
            "DishAmountInt":-2, "DishDiscountSumInt":0, "DishReturnSum":280, "Storned":"TRUE"})
        self.ingest([original, refund])
        self.assertTrue(self.orders()[0].excluded)
        self.assertEqual(self.orders()[0].revenue, 0)

    def test_return_chain_is_quarantined(self):
        first, second = uuid4(), uuid4()
        self.ingest([self.row(), self.row(**{"UniqOrderId.Id":str(first), "SourceOrderId":str(self.order),
            "DishAmountInt":-1,"DishDiscountSumInt":-140,"Storned":"TRUE"}),
            self.row(**{"UniqOrderId.Id":str(second),"SourceOrderId":str(first),
                "DishAmountInt":-1,"DishDiscountSumInt":-140,"Storned":"TRUE"})])
        self.assertTrue(all(order.excluded for order in self.orders()))

    def test_other_seller_and_tenant_are_not_visible(self):
        self.ingest([self.row()])
        with self.sessions() as db:
            state = db.get(SalesSyncState, ("eclair", self.source_id))
            # The fixture admin is linked to a different employee than the cashier.
            user = db.get(User, 1)
            self.assertEqual(seller_orders(db, state, user=user), [])
            user.tenant_id = "different"
            self.assertEqual(seller_orders(db, state, user=user), [])

    def test_mapping_olap_id_is_audited_and_unique(self):
        from app.employees.iiko import set_department_mapping
        from app.models.audit import AuditEvent
        from fastapi import HTTPException
        with self.sessions() as db:
            mapping = db.scalar(select(IikoDepartmentMapping))
            group_id = mapping.iiko_department_id
            actor = db.get(User, 1)
            updated = set_department_mapping(db, tenant_id="eclair", iiko_department_id=group_id,
                eos_department_id=self.department_id, source_name="Test", reason="Confirm OLAP namespace",
                actor=actor, olap_department_id=self.point, update_olap=True)
            self.assertEqual(updated.olap_department_id, self.point)
            self.assertIsNotNone(db.scalar(select(AuditEvent).where(AuditEvent.entity_type=="IikoDepartmentMapping")))
            with self.assertRaises(HTTPException) as error:
                set_department_mapping(db, tenant_id="eclair", iiko_department_id=uuid4(),
                    eos_department_id=self.department_id, source_name="Test", reason="Duplicate point",
                    actor=actor, olap_department_id=self.point, update_olap=True)
            self.assertEqual(error.exception.status_code, 409)
