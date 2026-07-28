import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.automation.supply_actions import (
    SupplyAutomationContext,
    SupplyCyclePeriodInvalidError,
    SupplyDirectionInactiveError,
    SupplyDirectionNotFoundError,
    SupplyTimezoneInvalidError,
    close_expired_request_cycles,
    ensure_request_cycle,
)
from app.models.supply import (
    SupplyRequestCycle,
    SupplyRequestDirection,
)


EXECUTION_ID = UUID("41644d7a-8875-4f35-a493-371b330fb154")
REQUESTED_AT = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)


class SupplyAutomationActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.execute(
                "PRAGMA foreign_keys=ON"
            ),
        )
        SupplyRequestDirection.__table__.create(self.engine)
        SupplyRequestCycle.__table__.create(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        with self.session_factory.begin() as session:
            session.add_all(
                [
                    SupplyRequestDirection(
                        tenant_id="eclair",
                        code="MAIN",
                        name="Основное",
                    ),
                    SupplyRequestDirection(
                        tenant_id="eclair",
                        code="HOUSEHOLD",
                        name="Хозяйственное",
                        is_active=False,
                    ),
                    SupplyRequestDirection(
                        tenant_id="other",
                        code="MAIN",
                        name="Чужое",
                    ),
                ]
            )

    def tearDown(self) -> None:
        self.engine.dispose()

    def context(
        self,
        *,
        tenant_id: str = "eclair",
        requested_at: datetime = REQUESTED_AT,
        executed_at: datetime = REQUESTED_AT,
    ) -> SupplyAutomationContext:
        return SupplyAutomationContext(
            execution_id=EXECUTION_ID,
            tenant_id=tenant_id,
            requested_at=requested_at,
            executed_at=executed_at,
        )

    def ensure_payload(self, **changes: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "direction_code": "MAIN",
            "cycle_date_offset_days": 0,
            "opens_time": "00:00",
            "closes_time": "23:59",
            "hard_closes_time": "00:10",
            "hard_close_next_day": True,
            "timezone": "Asia/Yekaterinburg",
            "initial_status": "OPEN",
        }
        payload.update(changes)
        return payload

    def run_ensure(
        self,
        *,
        context: SupplyAutomationContext | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with self.session_factory.begin() as session:
            return ensure_request_cycle(
                session,
                context or self.context(),
                payload or self.ensure_payload(),
            )

    def test_ensure_creates_timezone_aware_cycle_from_direction_code(
        self,
    ) -> None:
        result = self.run_ensure()

        self.assertEqual(result["outcome"], "created")
        self.assertEqual(result["direction_code"], "MAIN")
        self.assertEqual(result["cycle_date"], "2026-07-28")
        self.assertEqual(
            result["opens_at"],
            "2026-07-27T19:00:00+00:00",
        )
        self.assertEqual(
            result["closes_at"],
            "2026-07-28T18:59:00+00:00",
        )
        self.assertEqual(
            result["hard_closes_at"],
            "2026-07-28T19:10:00+00:00",
        )
        with self.session_factory() as session:
            cycle = session.scalar(select(SupplyRequestCycle))
            self.assertIsNotNone(cycle)
            assert cycle is not None
            direction = session.get(
                SupplyRequestDirection,
                cycle.direction_id,
            )
            self.assertEqual(direction.code, "MAIN")
            self.assertEqual(cycle.status, "OPEN")

    def test_repeat_and_retry_return_existing_without_duplicate(self) -> None:
        created = self.run_ensure()
        repeated = self.run_ensure()

        self.assertEqual(created["outcome"], "created")
        self.assertEqual(repeated["outcome"], "already_exists")
        self.assertEqual(created["cycle_id"], repeated["cycle_id"])
        with self.session_factory() as session:
            count = session.scalar(
                select(func.count()).select_from(SupplyRequestCycle)
            )
        self.assertEqual(count, 1)

    def test_positive_offset_uses_next_local_cycle_date(self) -> None:
        result = self.run_ensure(
            payload=self.ensure_payload(cycle_date_offset_days=1)
        )
        self.assertEqual(result["cycle_date"], "2026-07-29")

    def test_direction_missing_inactive_and_tenant_isolation(self) -> None:
        with self.assertRaises(SupplyDirectionNotFoundError):
            self.run_ensure(
                payload=self.ensure_payload(direction_code="UNKNOWN")
            )
        with self.assertRaises(SupplyDirectionInactiveError):
            self.run_ensure(
                payload=self.ensure_payload(direction_code="HOUSEHOLD")
            )

        foreign = self.run_ensure(context=self.context(tenant_id="other"))
        local = self.run_ensure()
        self.assertNotEqual(foreign["cycle_id"], local["cycle_id"])
        with self.session_factory() as session:
            tenants = session.scalars(
                select(SupplyRequestCycle.tenant_id).order_by(
                    SupplyRequestCycle.tenant_id
                )
            ).all()
        self.assertEqual(list(tenants), ["eclair", "other"])

    def test_invalid_timezone_and_period_are_controlled_errors(self) -> None:
        with self.assertRaises(SupplyTimezoneInvalidError):
            self.run_ensure(
                payload=self.ensure_payload(timezone="Mars/Olympus")
            )
        with self.assertRaises(SupplyCyclePeriodInvalidError):
            self.run_ensure(
                payload=self.ensure_payload(
                    opens_time="12:00",
                    closes_time="11:00",
                )
            )

    def add_cycle(
        self,
        *,
        status: str,
        closes_at: datetime,
        hard_closes_at: datetime | None,
        tenant_id: str = "eclair",
        direction_code: str = "MAIN",
        day_offset: int = 0,
    ) -> UUID:
        with self.session_factory.begin() as session:
            direction = session.scalar(
                select(SupplyRequestDirection).where(
                    SupplyRequestDirection.tenant_id == tenant_id,
                    SupplyRequestDirection.code == direction_code,
                )
            )
            assert direction is not None
            cycle = SupplyRequestCycle(
                tenant_id=tenant_id,
                direction_id=direction.id,
                cycle_date=date(2026, 7, 20)
                + timedelta(days=day_offset),
                opens_at=closes_at - timedelta(hours=1),
                closes_at=closes_at,
                hard_closes_at=hard_closes_at,
                status=status,
            )
            session.add(cycle)
            session.flush()
            return cycle.id

    def test_close_expired_honors_terminal_future_fallback_and_tenant(
        self,
    ) -> None:
        expired_at = REQUESTED_AT - timedelta(minutes=1)
        future_at = REQUESTED_AT + timedelta(minutes=1)
        expired_hard = self.add_cycle(
            status="OPEN",
            closes_at=expired_at - timedelta(minutes=5),
            hard_closes_at=expired_at,
        )
        expired_fallback = self.add_cycle(
            status="SCHEDULED",
            closes_at=expired_at,
            hard_closes_at=None,
            day_offset=1,
        )
        future = self.add_cycle(
            status="OPEN",
            closes_at=expired_at,
            hard_closes_at=future_at,
            day_offset=2,
        )
        closed = self.add_cycle(
            status="CLOSED",
            closes_at=expired_at,
            hard_closes_at=expired_at,
            day_offset=3,
        )
        cancelled = self.add_cycle(
            status="CANCELLED",
            closes_at=expired_at,
            hard_closes_at=expired_at,
            day_offset=4,
        )
        foreign = self.add_cycle(
            tenant_id="other",
            status="OPEN",
            closes_at=expired_at,
            hard_closes_at=expired_at,
        )

        with (
            patch(
                "app.automation.supply_actions."
                "_advance_debts_for_closed_cycle"
            ) as advance_debts,
            self.session_factory.begin() as session,
        ):
            result = close_expired_request_cycles(
                session,
                self.context(executed_at=REQUESTED_AT),
                {"timezone": "Asia/Yekaterinburg"},
            )

        self.assertEqual(result["closed_count"], 2)
        self.assertEqual(
            set(result["closed_cycle_ids"]),
            {str(expired_hard), str(expired_fallback)},
        )
        self.assertEqual(advance_debts.call_count, 2)
        self.assertEqual(
            result["executed_at"],
            "2026-07-28T15:00:00+05:00",
        )
        with self.session_factory() as session:
            states = {
                cycle_id: session.get(SupplyRequestCycle, cycle_id).status
                for cycle_id in (
                    expired_hard,
                    expired_fallback,
                    future,
                    closed,
                    cancelled,
                    foreign,
                )
            }
        self.assertEqual(states[expired_hard], "CLOSED")
        self.assertEqual(states[expired_fallback], "CLOSED")
        self.assertEqual(states[future], "OPEN")
        self.assertEqual(states[closed], "CLOSED")
        self.assertEqual(states[cancelled], "CANCELLED")
        self.assertEqual(states[foreign], "OPEN")

    def test_close_expired_is_idempotent(self) -> None:
        expired = self.add_cycle(
            status="OPEN",
            closes_at=REQUESTED_AT - timedelta(minutes=2),
            hard_closes_at=REQUESTED_AT - timedelta(minutes=1),
        )
        with patch(
            "app.automation.supply_actions."
            "_advance_debts_for_closed_cycle"
        ):
            with self.session_factory.begin() as session:
                first = close_expired_request_cycles(
                    session,
                    self.context(),
                    {"timezone": "Asia/Yekaterinburg"},
                )
            with self.session_factory.begin() as session:
                second = close_expired_request_cycles(
                    session,
                    self.context(),
                    {"timezone": "Asia/Yekaterinburg"},
                )
        self.assertEqual(first["closed_cycle_ids"], [str(expired)])
        self.assertEqual(second["closed_count"], 0)


if __name__ == "__main__":
    unittest.main()
