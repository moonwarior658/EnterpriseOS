import unittest

from app.api.routes.iiko import get_iiko_provider
from app.integrations.iiko.schemas import IikoEmployeeDto, IikoPersonalShiftDto
from app.models.employee import EmployeeIikoShift, IikoEmployeeLink
from tests.test_employees_api import EmployeesApiTests


class FakeIikoProvider:
    async def get_employees(self):
        return [
            IikoEmployeeDto(external_id="iiko-1", name="Иванов Иван Иванович", code="001", is_employee=True),
            IikoEmployeeDto(external_id="iiko-2", name="Иванов Иван Иванович", code="002", is_employee=True),
        ]

    async def get_personal_shifts(self, *, date_from, date_to):
        return []


class EmployeeIikoApiTests(EmployeesApiTests):
    def setUp(self) -> None:
        super().setUp()
        IikoEmployeeLink.__table__.create(self.engine)
        app_provider = FakeIikoProvider()
        from app.main import app
        app.dependency_overrides[get_iiko_provider] = lambda: app_provider

    def test_admin_candidate_link_history_and_shift_reads(self) -> None:
        employee = self.create_employee()
        employee_id = employee["id"]
        candidates = self.client.get(f"/employees/{employee_id}/iiko/candidates")
        self.assertEqual(candidates.status_code, 200, candidates.text)
        self.assertEqual(len(candidates.json()), 2)
        self.assertIsNone(self.client.get(f"/employees/{employee_id}/iiko/link").json())
        linked = self.client.post(
            f"/employees/{employee_id}/iiko/link",
            json={"iiko_user_id": "iiko-1", "reason": "Подтверждение личности"},
        )
        self.assertEqual(linked.status_code, 201, linked.text)
        self.assertEqual(linked.json()["iiko_user_id"], "iiko-1")
        history = self.client.get(f"/employees/{employee_id}/iiko/link/history")
        self.assertEqual(len(history.json()), 1)
        self.assertEqual(self.client.get(f"/employees/{employee_id}/iiko/shifts").json(), [])
        self.assertIsNone(self.client.get(f"/employees/{employee_id}/iiko/shifts/active").json())

        self.current_user_id = 2
        self.assertEqual(
            self.client.get(f"/employees/{employee_id}/iiko/candidates").status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
