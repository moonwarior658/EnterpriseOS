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
                    <code>001</code><firstName>Иван</firstName><middleName>Иванович</middleName>
                    <lastName>Иванов</lastName><birthday>1990-01-02T00:00:00+05:00</birthday>
                    <preferredDepartmentCode>M15</preferredDepartmentCode>
                    <departmentCodes>M15</departmentCodes><departmentCodes>M35</departmentCodes>
                    <responsibilityDepartmentCodes>M15</responsibilityDepartmentCodes>
                    <mainRoleId>role-1</mainRoleId><rolesIds>role-1</rolesIds>
                    <mainRoleCode>SELLER</mainRoleCode><roleCodes>SELLER</roleCodes>
                    <employee>true</employee><deleted>false</deleted>
                    </employee></employees>
                """)
            return response(request, text="""
                <attendances><attendance><id>shift-1</id><employeeId>employee-1</employeeId>
                <roleId>role-1</roleId><attendanceType>W</attendanceType>
                <departmentId>11111111-1111-4111-8111-111111111111</departmentId>
                <departmentName>М15</departmentName>
                <dateFrom>2026-09-28T08:00:00+05:00</dateFrom>
                <dateTo>2026-09-28T16:17:00+05:00</dateTo>
                <personalDateFrom>2026-09-28T08:05:00+05:00</personalDateFrom>
                <personalDateTo>2026-09-28T16:11:00+05:00</personalDateTo>
                <created>2026-09-28T08:00:01+05:00</created>
                <modified>2026-09-28T16:17:01+05:00</modified>
                <userModified>manager-1</userModified></attendance></attendances>
            """)

        async with IikoServerClient(make_settings(), transport=httpx.MockTransport(handler)) as client:
            employees = await client.get_employees()
            shifts = await client.get_personal_shifts(
                date_from=date(2026, 9, 28), date_to=date(2026, 9, 28),
            )
        self.assertEqual(employees[0].external_id, "employee-1")
        self.assertEqual(employees[0].birth_date, date(1990, 1, 2))
        self.assertEqual(employees[0].department_codes, ("M15", "M35"))
        self.assertTrue(employees[0].is_employee)
        self.assertEqual(shifts[0].external_id, "shift-1")
        self.assertEqual(shifts[0].opened_at.utcoffset(), timedelta(hours=5))
        self.assertEqual(shifts[0].opened_at.hour, 8)
        self.assertEqual(shifts[0].opened_at.minute, 5)
        self.assertEqual(shifts[0].closed_at.minute, 11)
        self.assertEqual(shifts[0].confirmed_opened_at.minute, 0)
        self.assertEqual(shifts[0].confirmed_closed_at.minute, 17)
        attendance_request = next(
            request for request in requests
            if request.url.path.endswith("/api/employees/attendance")
        )
        self.assertEqual(attendance_request.url.params["from"], "2026-09-28")
        self.assertEqual(attendance_request.url.params["to"], "2026-09-28")
        self.assertEqual(attendance_request.url.params["withPaymentDetails"], "false")

    async def test_employee_birthday_is_optional_and_office_attendance_is_not_personal_shift(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/employees"):
                return response(request, text="""
                    <employees><employee><id>employee-2</id><name>Без даты</name>
                    <employee>true</employee><deleted>false</deleted></employee></employees>
                """)
            return response(request, text="""
                <attendances><attendance><id>office-1</id><employeeId>employee-2</employeeId>
                <departmentId>11111111-1111-4111-8111-111111111111</departmentId>
                <dateFrom>2026-09-28T08:00:00+05:00</dateFrom>
                <dateTo>2026-09-28T16:00:00+05:00</dateTo></attendance></attendances>
            """)
        async with IikoServerClient(make_settings(), transport=httpx.MockTransport(handler)) as client:
            employees = await client.get_employees()
            shifts = await client.get_personal_shifts(
                date_from=date(2026, 9, 28), date_to=date(2026, 9, 28),
            )
        self.assertIsNone(employees[0].birth_date)
        self.assertEqual(shifts, [])


if __name__ == "__main__":
    unittest.main()
