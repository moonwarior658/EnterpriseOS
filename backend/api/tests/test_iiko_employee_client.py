import unittest
from datetime import date, timedelta

import httpx

from app.integrations.iiko.client import IikoServerClient
from tests.test_iiko_client import make_settings, response


class IikoEmployeeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_employee_and_attendance_contracts(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            requests.append(request)
            if request.url.path.endswith("/api/employees"):
                return response(request, text="""
                    <employees><employee><id>employee-1</id><name>Иванов Иван</name>
                    <code>001</code><employee>true</employee><deleted>false</deleted>
                    </employee></employees>
                """)
            return response(request, text="""
                <attendances><attendance><id>shift-1</id><employeeId>employee-1</employeeId>
                <departmentId>11111111-1111-4111-8111-111111111111</departmentId>
                <dateFrom>2026-09-28T08:00:00+05:00</dateFrom>
                <dateTo>2026-09-28T16:17:00+05:00</dateTo></attendance></attendances>
            """)

        async with IikoServerClient(make_settings(), transport=httpx.MockTransport(handler)) as client:
            employees = await client.get_employees()
            shifts = await client.get_personal_shifts(
                date_from=date(2026, 9, 28), date_to=date(2026, 9, 28),
            )
        self.assertEqual(employees[0].external_id, "employee-1")
        self.assertEqual(shifts[0].external_id, "shift-1")
        self.assertEqual(shifts[0].opened_at.utcoffset(), timedelta(hours=5))
        attendance_request = next(
            request for request in requests
            if request.url.path.endswith("/api/employees/attendance")
        )
        self.assertEqual(attendance_request.url.params["from"], "2026-09-28")
        self.assertEqual(attendance_request.url.params["to"], "2026-09-28")


if __name__ == "__main__":
    unittest.main()
