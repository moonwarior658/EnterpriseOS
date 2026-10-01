"""Disposable PostgreSQL proof for repair migration 0063 -> 0064."""
import os
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from tests.postgres_test_support import reset_disposable_postgres_schema

TEST_URL = os.getenv('SUPPLY_TEST_DATABASE_URL')


@unittest.skipUnless(TEST_URL, 'requires isolated PostgreSQL')
class RepairMigrationTests(unittest.TestCase):
    def test_legacy_survives_upgrade_downgrade_and_constraints(self):
        url = make_url(TEST_URL)
        self.assertIn(url.host, {'127.0.0.1', 'localhost', '::1'})
        self.assertEqual(url.database, 'eos_supply_migration_test')
        previous = (settings.postgres_db, settings.postgres_user, settings.postgres_password,
                    settings.postgres_host, settings.postgres_port)
        engine = create_engine(TEST_URL)
        try:
            reset_disposable_postgres_schema(engine)
            settings.postgres_db = url.database
            settings.postgres_user = url.username or ''
            settings.postgres_password = url.password or ''
            settings.postgres_host = url.host or ''
            settings.postgres_port = url.port or 5432
            config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
            command.upgrade(config, '20261001_0063')
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO work_requests (id, tenant_id, request_type, department, description, status, repair_category, priority) VALUES (92001, 'eclair', 'repair', 'Кафе', 'Старый ремонт', 'new', 'Другое', 'routine')"))
            command.upgrade(config, '20261001_0064')
            with engine.connect() as connection:
                row = connection.execute(text('SELECT id, department, department_id, responsible_role FROM work_requests WHERE id=92001')).one()
                self.assertEqual((row.id, row.department, row.department_id, row.responsible_role), (92001, 'Кафе', None, None))
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text("UPDATE work_requests SET responsible_role='DIRECTOR' WHERE id=92001"))
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO external_contractors (id, tenant_id, name, phone, is_active) VALUES ('00000000-0000-4000-8000-000000000001', 'eclair', 'Мастер', '+7', true)"))
                connection.execute(text("INSERT INTO contractor_specializations (id, tenant_id, name, is_active) VALUES ('00000000-0000-4000-8000-000000000002', 'eclair', 'Электрик', true)"))
                connection.execute(text("INSERT INTO contractor_specialization_links (tenant_id, contractor_id, specialization_id) VALUES ('eclair', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002')"))
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text("INSERT INTO contractor_specialization_links (tenant_id, contractor_id, specialization_id) VALUES ('other', '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002')"))
            with self.assertRaises(RuntimeError):
                command.downgrade(config, '20261001_0063')
            with engine.begin() as connection:
                connection.execute(text('DELETE FROM contractor_specialization_links'))
                connection.execute(text('DELETE FROM contractor_specializations'))
                connection.execute(text('DELETE FROM external_contractors'))
            command.downgrade(config, '20261001_0063')
            with engine.connect() as connection:
                self.assertEqual(connection.scalar(text('SELECT description FROM work_requests WHERE id=92001')), 'Старый ремонт')
            command.upgrade(config, '20261001_0064')
            with engine.connect() as connection:
                self.assertEqual(connection.scalar(text('SELECT department FROM work_requests WHERE id=92001')), 'Кафе')
        finally:
            (settings.postgres_db, settings.postgres_user, settings.postgres_password,
             settings.postgres_host, settings.postgres_port) = previous
            engine.dispose()
