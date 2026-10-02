"""Repair compatibility at the legacy /requests read path."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('POSTGRES_DB', 'test')
os.environ.setdefault('POSTGRES_USER', 'test')
os.environ.setdefault('POSTGRES_PASSWORD', 'test')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret')

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.api.dependencies import get_current_user
from app.core.config import settings
from app.main import app
from app.models.work_request import (
    ContractorSpecialization, ContractorSpecializationLink, ExternalContractor,
    WorkRequest, WorkRequestAttachment, WorkRequestComment,
)
from tests import test_employees_api as fixture


class WorkRequestsApiTests(unittest.TestCase):
    setUp = fixture.EmployeesApiTests.setUp
    tearDown = fixture.EmployeesApiTests.tearDown

    def setup_repair_tables(self):
        ExternalContractor.__table__.create(self.engine)
        ContractorSpecialization.__table__.create(self.engine)
        ContractorSpecializationLink.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        WorkRequestAttachment.__table__.create(self.engine)
        WorkRequestComment.__table__.create(self.engine)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_upload_dir = settings.work_request_upload_dir
        settings.work_request_upload_dir = self.temp_dir.name
        self.addCleanup(lambda: setattr(settings, 'work_request_upload_dir', self.previous_upload_dir))
        self.addCleanup(self.temp_dir.cleanup)

    def payload(self):
        return {
            'department_id': str(self.department_id),
            'description': 'Не включается кофемашина',
            'repair_category': 'Кофемашина',
            'priority': 'urgent',
        }

    def test_authenticated_creation_and_legacy_routes_fail_closed(self):
        self.setup_repair_tables()
        created = self.client.post('/repairs', json=self.payload())
        self.assertEqual(created.status_code, 201, created.text)
        repair_id = created.json()['id']
        self.assertEqual(created.json()['responsible_role'], 'HANDYMAN')
        self.assertEqual(self.client.post('/public/requests', json={'request_type': 'repair'}).status_code, 403)
        self.assertEqual(self.client.post('/requests', json={'request_type': 'repair'}).status_code, 422)
        self.assertEqual(self.client.patch(f'/requests/{repair_id}', json={'status': 'completed'}).status_code, 405)
        self.assertEqual(self.client.patch(f'/requests/{repair_id}/status', json={'status': 'completed'}).status_code, 405)

    def test_list_excludes_archived_warehouse_and_other_tenant(self):
        self.setup_repair_tables()
        own_id = self.client.post('/repairs', json=self.payload()).json()['id']
        with self.sessions.begin() as session:
            session.add_all([
                WorkRequest(request_type='warehouse', department='М15', description='Архив', status='new', warehouse_category='products', tenant_id='eclair'),
                WorkRequest(request_type='repair', department='М15', description='Чужой', status='new', repair_category='Другое', priority='routine', tenant_id='other'),
            ])
        listed = self.client.get('/requests?_ts=123')
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item['id'] for item in listed.json()], [own_id])
        self.assertEqual(listed.headers['cache-control'], 'no-store, no-cache, must-revalidate, max-age=0')
        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get('/requests').status_code, 401)

    def test_authenticated_multipart_and_attachment_read(self):
        self.setup_repair_tables()
        created = self.client.post('/repairs', data=self.payload(), files=[('photos', ('machine.jpg', b'jpeg-data', 'image/jpeg'))])
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['attachment_count'], 1)
        attachment = created.json()['attachments'][0]
        self.assertEqual(len(list(Path(self.temp_dir.name).iterdir())), 1)
        response = self.client.get(f"/requests/{created.json()['id']}/attachments/{attachment['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'jpeg-data')
        added = self.client.post(f"/repairs/{created.json()['id']}/photos", files={'photo': ('later.png', b'png-data', 'image/png')})
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual(self.client.get(f"/requests/{created.json()['id']}").json()['attachment_count'], 2)
        invalid = self.client.post('/repairs', data=self.payload(), files=[('photos', ('note.txt', b'text', 'text/plain'))])
        self.assertEqual(invalid.status_code, 409)

    def test_legacy_repair_is_readable_without_guessed_responsibility(self):
        self.setup_repair_tables()
        with self.sessions.begin() as session:
            legacy = WorkRequest(tenant_id='eclair', request_type='repair', department='Кафе',
                description='Исторический ремонт', status='completed', repair_category='Другое',
                priority='routine')
            session.add(legacy)
            session.flush()
            legacy_id = legacy.id
        card = self.client.get(f'/requests/{legacy_id}')
        self.assertEqual(card.status_code, 200, card.text)
        self.assertEqual(card.json()['department'], 'Кафе')
        self.assertIsNone(card.json()['department_id'])
        self.assertIsNone(card.json()['responsible_role'])
        self.assertEqual(card.json()['allowed_actions'], [])

    def test_migrations_have_single_head(self):
        config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        scripts = ScriptDirectory.from_config(config)
        self.assertEqual(scripts.get_heads(), ['20261001_0065'])
