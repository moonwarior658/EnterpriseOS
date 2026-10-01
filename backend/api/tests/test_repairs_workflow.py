"""Repair role, responsibility, and explicit-action regression tests."""
import os
import unittest
from datetime import UTC, datetime, timedelta

os.environ.setdefault('POSTGRES_DB', 'test')
os.environ.setdefault('POSTGRES_USER', 'test')
os.environ.setdefault('POSTGRES_PASSWORD', 'test')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret')

from app.models.employee import EmployeeRole, EmployeeRoleAssignment, EmployeeIikoShift, EmployeeIikoShiftStatus, Employee
from app.models.audit import AuditEvent
from sqlalchemy import select
from uuid import uuid4
from app.models.supply import Department, DepartmentBusinessType
from app.models.work_request import (
    ContractorSpecialization, ContractorSpecializationLink, ExternalContractor,
    WorkRequest, WorkRequestAttachment, WorkRequestComment,
)
from tests.test_employees_api import EmployeesApiTests
from tests.test_rbac_employee_user import RbacEmployeeUserTests


class RepairWorkflowTests(unittest.TestCase):
    setUp = EmployeesApiTests.setUp
    tearDown = EmployeesApiTests.tearDown
    actor = RbacEmployeeUserTests.actor

    def create_tables(self):
        ExternalContractor.__table__.create(self.engine)
        ContractorSpecialization.__table__.create(self.engine)
        ContractorSpecializationLink.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        WorkRequestAttachment.__table__.create(self.engine)
        WorkRequestComment.__table__.create(self.engine)

    def create_repair(self, department_id=None):
        return self.client.post('/repairs', json={
            'department_id': str(department_id or self.department_id),
            'description': 'Сломалась кофемашина',
            'repair_category': 'Кофемашина',
            'priority': 'important',
        })

    def test_scope_and_read_only_roles(self):
        self.create_tables()
        created = self.create_repair()
        self.assertEqual(created.status_code, 201, created.text)
        repair_id = created.json()['id']
        self.assertEqual(created.json()['responsible_role'], 'HANDYMAN')
        self.actor(30, EmployeeRole.DIRECTOR)
        self.current_user_id = 30
        read = self.client.get('/requests')
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual([item['id'] for item in read.json()], [repair_id])
        self.assertEqual(read.json()[0]['allowed_actions'], [])
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/take').status_code, 409)
        self.assertEqual(self.client.post(f'/requests/{repair_id}/comments', json={'body': 'Нет'}).status_code, 409)
        self.assertEqual(self.client.patch(f'/requests/{repair_id}/status', json={'status': 'completed'}).status_code, 405)
        self.actor(31, EmployeeRole.ACCOUNTANT)
        self.current_user_id = 31
        self.assertEqual(self.client.get(f'/requests/{repair_id}').status_code, 200)
        self.assertEqual(self.client.get(f'/requests/{repair_id}').json()['allowed_actions'], [])

    def test_handyman_escalation_and_manager_ownership(self):
        self.create_tables()
        repair_id = self.create_repair().json()['id']
        self.actor(32, EmployeeRole.HANDYMAN)
        self.actor(33, EmployeeRole.SUPPLY_MANAGER)
        self.current_user_id = 32
        taken = self.client.post(f'/repairs/{repair_id}/take')
        self.assertEqual(taken.status_code, 200, taken.text)
        self.assertEqual(taken.json()['status'], 'in_progress')
        escalated = self.client.post(f'/repairs/{repair_id}/escalate-to-supply')
        self.assertEqual(escalated.status_code, 200, escalated.text)
        self.assertEqual(escalated.json()['responsible_role'], 'SUPPLY_MANAGER')
        self.assertIsNone(escalated.json()['responsible_employee_id'])
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/close').status_code, 409)
        self.current_user_id = 33
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/take').status_code, 200)
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/close').status_code, 200)
        self.current_user_id = 1
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/reopen', json={'reason': ''}).status_code, 422)
        reopened = self.client.post(f'/repairs/{repair_id}/reopen', json={'reason': 'Не работает'})
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(reopened.json()['responsible_role'], 'SUPPLY_MANAGER')
        timeline = self.client.get(f'/repairs/{repair_id}/timeline').json()
        self.assertEqual([event['action'] for event in timeline], ['CREATE', 'TAKE', 'ESCALATE_TO_SUPPLY', 'TAKE', 'CLOSE', 'REOPEN'])
        self.assertEqual(timeline[-1]['reason'], 'Не работает')

    def test_network_scope_and_director_plus_handyman(self):
        self.create_tables()
        with self.sessions.begin() as session:
            self_id = self.department_id
            other = session.get(Department, self.other_department_id)
            other.business_type = DepartmentBusinessType.PRODUCTION
        repair_id = self.create_repair().json()['id']
        self.actor(34, EmployeeRole.NETWORK_MANAGER)
        self.current_user_id = 34
        self.assertEqual(self.client.get(f'/requests/{repair_id}').status_code, 200)
        self.assertEqual(self.create_repair(self.other_department_id).status_code, 403)
        self.actor(35, EmployeeRole.DIRECTOR, EmployeeRole.HANDYMAN)
        self.current_user_id = 35
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/take').status_code, 200)
        events = self.client.get(f'/repairs/{repair_id}/timeline').json()
        self.assertEqual(events[-1]['role'], 'HANDYMAN')

    def test_contractor_validation_and_visit(self):
        self.create_tables()
        repair_id = self.create_repair().json()['id']
        self.actor(36, EmployeeRole.HANDYMAN)
        self.actor(37, EmployeeRole.SUPPLY_MANAGER)
        self.current_user_id = 37
        specialization = self.client.post('/repairs/specializations', json={'name': 'Электрик'})
        self.assertEqual(specialization.status_code, 201, specialization.text)
        contractor = self.client.post('/repairs/contractors', json={'name': 'Мастер', 'phone': '+7', 'specialization_ids': [specialization.json()['id']]})
        self.assertEqual(contractor.status_code, 201, contractor.text)
        self.current_user_id = 36
        self.assertEqual(self.client.post('/repairs/contractors', json={'name': 'Нет', 'phone': '+7'}).status_code, 403)
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/take').status_code, 200)
        assigned = self.client.post(f'/repairs/{repair_id}/assign-contractor', json={
            'contractor_id': contractor.json()['id'], 'specialization_id': specialization.json()['id'],
        })
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()['contractor_id'], contractor.json()['id'])
        self.assertEqual(assigned.json()['status'], 'in_progress')
        visit = self.client.post(f'/repairs/{repair_id}/schedule-external-visit', json={
            'contractor_id': contractor.json()['id'], 'specialization_id': specialization.json()['id'],
            'visit_at': (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        })
        self.assertEqual(visit.status_code, 200, visit.text)
        self.assertEqual(visit.json()['status'], 'waiting_external')
        self.assertEqual(visit.json()['responsible_role'], 'HANDYMAN')
        self.current_user_id = 1
        second_id = self.create_repair().json()['id']
        self.current_user_id = 36
        self.assertEqual(self.client.post(f'/repairs/{second_id}/take').status_code, 200)
        self.assertEqual(self.client.post(f'/repairs/{second_id}/assign-contractor', json={
            'contractor_id': contractor.json()['id'], 'specialization_id': specialization.json()['id'],
        }).status_code, 200)
        escalated = self.client.post(f'/repairs/{second_id}/escalate-to-supply')
        self.assertEqual(escalated.status_code, 200, escalated.text)
        self.assertEqual(escalated.json()['contractor_id'], contractor.json()['id'])
        self.current_user_id = 37
        self.assertEqual(self.client.get(f'/requests/{second_id}').json()['contractor_name'], 'Мастер')
        self.assertEqual(self.client.patch(f"/repairs/contractors/{contractor.json()['id']}", json={'is_active': False}).status_code, 422)
        deactivated = self.client.patch(f"/repairs/contractors/{contractor.json()['id']}", json={
            'is_active': False, 'reason': 'Больше не работает',
        })
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        self.current_user_id = 36
        self.assertEqual(self.client.post(f'/repairs/{repair_id}/assign-contractor', json={
            'contractor_id': contractor.json()['id'], 'specialization_id': specialization.json()['id'],
        }).status_code, 409)
        self.current_user_id = 37
        self.assertEqual(self.client.patch(f"/repairs/contractors/{contractor.json()['id']}", json={'is_active': True}).status_code, 422)
        self.assertEqual(self.client.patch(f"/repairs/contractors/{contractor.json()['id']}", json={
            'is_active': True, 'reason': 'Снова доступен',
        }).status_code, 200)

    def test_seller_read_without_shift_and_write_with_shift(self):
        self.create_tables()
        repair_id = self.create_repair().json()['id']
        self.actor(38, EmployeeRole.SELLER, department_id=self.department_id)
        self.current_user_id = 38
        self.assertEqual(self.client.get(f'/requests/{repair_id}').status_code, 200)
        self.assertEqual(self.create_repair().status_code, 403)
        with self.sessions.begin() as session:
            employee_id = session.scalar(select(Employee.id).where(Employee.linked_user_id == 38))
            now = datetime.now(UTC)
            session.add(EmployeeIikoShift(
                tenant_id='eclair', employee_id=employee_id,
                iiko_user_id='seller-38', department_id=self.department_id,
                opened_at=now, first_seen_at=now, last_seen_at=now,
                status=EmployeeIikoShiftStatus.OPEN,
                reconciliation_key='seller-38-open',
            ))
        created = self.create_repair()
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['department_id'], str(self.department_id))
        with self.sessions.begin() as session:
            employee_id = session.scalar(select(Employee.id).where(Employee.linked_user_id == 38))
            session.add(EmployeeRoleAssignment(tenant_id='eclair', employee_id=employee_id,
                role=EmployeeRole.NETWORK_MANAGER, valid_from=datetime.now(UTC) - timedelta(days=1),
                reason='Multi-role fixture', assigned_by_user_id=1))
        edited = self.client.patch(f"/repairs/{created.json()['id']}/details", json={
            'description': 'Уточнённое описание', 'repair_category': 'Другое', 'priority': 'routine',
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()['description'], 'Уточнённое описание')
        with self.sessions() as session:
            event = session.scalar(select(AuditEvent).where(AuditEvent.entity_id == str(created.json()['id']),
                AuditEvent.operation == 'EDIT_DETAILS'))
            self.assertEqual(event.authorized_as, 'SELLER')
        comment = self.client.post(f"/requests/{created.json()['id']}/comments", json={'body': 'Уточнение продавца'})
        self.assertEqual(comment.status_code, 201, comment.text)
        self.assertEqual(self.client.patch(f"/repairs/{repair_id}/details", json={
            'description': 'Чужой ремонт', 'repair_category': 'Другое', 'priority': 'routine',
        }).status_code, 409)

    def test_production_initiator_only_and_management_reopen(self):
        self.create_tables()
        with self.sessions.begin() as session:
            session.get(Department, self.other_department_id).business_type = DepartmentBusinessType.PRODUCTION
        self.actor(39, EmployeeRole.CONFECTIONER, department_id=self.other_department_id)
        self.actor(40, EmployeeRole.HEAD_OF_PRODUCTION, department_id=self.other_department_id)
        self.actor(41, EmployeeRole.HANDYMAN)
        self.current_user_id = 39
        own = self.create_repair(self.other_department_id)
        self.assertEqual(own.status_code, 201, own.text)
        self.current_user_id = 1
        another_id = self.create_repair(self.other_department_id).json()['id']
        self.current_user_id = 39
        self.assertEqual([item['id'] for item in self.client.get('/requests').json()], [own.json()['id']])
        self.assertEqual(self.client.get(f'/requests/{another_id}').status_code, 404)
        self.current_user_id = 40
        self.assertEqual(len(self.client.get('/requests').json()), 2)
        self.assertEqual(self.create_repair(self.department_id).status_code, 403)
        self.current_user_id = 41
        self.assertEqual(self.client.post(f'/repairs/{another_id}/take').status_code, 200)
        self.assertEqual(self.client.post(f'/repairs/{another_id}/close').status_code, 200)
        self.current_user_id = 40
        self.assertEqual(self.client.post(f'/repairs/{another_id}/reopen', json={'reason': 'Плохо починили'}).status_code, 200)

    def test_deputy_driver_baker_chef_reopen_scopes(self):
        self.create_tables()
        production_id, auto_id = uuid4(), uuid4()
        with self.sessions.begin() as session:
            session.add_all([
                Department(id=production_id, tenant_id='eclair', code='REPAIR_PROD',
                    name='Производство', business_type=DepartmentBusinessType.PRODUCTION),
                Department(id=auto_id, tenant_id='eclair', code='REPAIR_AUTO',
                    name='Авто', business_type=DepartmentBusinessType.AUTO),
            ])
        self.actor(43, EmployeeRole.DEPUTY_DIRECTOR)
        self.actor(44, EmployeeRole.DRIVER, department_id=auto_id)
        self.actor(45, EmployeeRole.BAKER, department_id=production_id)
        self.actor(46, EmployeeRole.CHEF_CONFECTIONER, department_id=production_id)
        self.actor(47, EmployeeRole.HANDYMAN)
        self.current_user_id = 43
        deputy_id = self.create_repair().json()['id']
        self.current_user_id = 44
        self.assertEqual(self.create_repair(self.department_id).status_code, 403)
        driver = self.create_repair(auto_id)
        self.assertEqual(driver.status_code, 201, driver.text)
        driver_id = driver.json()['id']
        self.current_user_id = 45
        baker = self.create_repair(production_id)
        self.assertEqual(baker.status_code, 201, baker.text)
        baker_id = baker.json()['id']
        self.assertEqual([row['id'] for row in self.client.get('/requests').json()], [baker_id])
        self.current_user_id = 46
        self.assertEqual([row['id'] for row in self.client.get('/requests').json()], [baker_id])
        self.current_user_id = 1
        managed_id = self.create_repair(production_id).json()['id']
        self.current_user_id = 47
        for repair_id in (deputy_id, driver_id, baker_id, managed_id):
            self.assertEqual(self.client.post(f'/repairs/{repair_id}/take').status_code, 200)
            self.assertEqual(self.client.post(f'/repairs/{repair_id}/close').status_code, 200)
        for user_id, own_id, other_id in ((43, deputy_id, driver_id),
                                          (44, driver_id, baker_id),
                                          (45, baker_id, driver_id),
                                          (46, managed_id, driver_id)):
            self.current_user_id = user_id
            self.assertEqual(self.client.post(f'/repairs/{other_id}/reopen', json={'reason': 'Не принят'}).status_code, 409 if user_id == 43 else 404)
            self.assertEqual(self.client.post(f'/repairs/{own_id}/reopen', json={'reason': 'Не принят'}).status_code, 200)
