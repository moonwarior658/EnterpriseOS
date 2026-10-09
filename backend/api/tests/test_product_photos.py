from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4
from PIL import Image
from sqlalchemy import select
from app.core.config import settings
from app.models.employee import EmployeeRole, EmployeeRoleAssignment
from app.models.supply import Department
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from tests.test_product_knowledge_management import ProductKnowledgeManagementTests


def image_bytes(color='red', fmt='PNG'):
    stream=BytesIO();Image.new('RGB',(64,48),color).save(stream,format=fmt);return stream.getvalue()


class ProductPhotoTests(ProductKnowledgeManagementTests):
    def setUp(self):
        super().setUp()
        self.storage=TemporaryDirectory();self.previous=settings.product_photo_upload_dir
        settings.product_photo_upload_dir=self.storage.name

    def tearDown(self):
        settings.product_photo_upload_dir=self.previous;self.storage.cleanup();super().tearDown()

    def upload(self, content=None, command=None, mime='image/png', pid=None):
        return self.client.put('/products/'+(pid or self.pid)+'/photo',data=command or self.command(),
            files={'file':('../../unsafe.svg',image_bytes() if content is None else content,mime)})

    def test_photo_lifecycle_retry_history_and_reopen(self):
        self.assertEqual(self.client.get('/products/'+self.pid+'/photo').status_code,404)
        base=self.command();response=self.upload(command=base);self.assertEqual(response.status_code,200,response.text)
        first=response.json()['photo'];self.assertTrue(first)
        self.assertEqual(self.upload(command=base).json()['version'],2)
        self.assertEqual(self.upload(image_bytes('blue'),command=base).status_code,409)
        self.assertEqual(self.client.get('/products').json()['items'][0]['photo'],first)
        photo=self.client.get('/products/'+self.pid+'/photo');self.assertEqual(photo.status_code,200)
        self.assertEqual(photo.headers['cache-control'],'private, no-store');self.assertEqual(photo.headers['x-content-type-options'],'nosniff')
        Image.open(BytesIO(photo.content)).verify()
        self.load();self.assertEqual(self.client.get('/products/'+self.pid).json()['photo'],first)
        self.assertEqual(self.upload(image_bytes('blue')).status_code,200)
        second=self.client.get('/products/'+self.pid).json()['photo'];self.assertNotEqual(first,second)
        from app.product_knowledge.media import read
        from app.models.user import User
        with self.sessions() as db:
            actor=db.scalar(select(User).where(User.tenant_id=='eclair'))
            self.assertTrue(read(db,actor,UUID(self.pid),self.storage.name).is_file())
        base=self.command()
        for _ in range(2):self.assertEqual(self.client.request('DELETE','/products/'+self.pid+'/photo',json=base).status_code,200)
        self.assertIsNone(self.client.get('/products/'+self.pid).json()['photo'])
        self.assertEqual(self.client.get('/products/'+self.pid+'/photo').status_code,404)
        self.assertEqual(len(list(Path(self.storage.name).rglob('*.webp'))),2)
        history=self.client.get('/products/'+self.pid+'/history').json()
        self.assertEqual([r['operation'] for r in history],['PHOTO_DELETE','PHOTO_UPLOAD','PHOTO_UPLOAD'])
        self.assertEqual(history[-1]['after']['local_photo_hash'],first)
        self.assertEqual(history[0]['before']['local_photo_hash'],second)
        from app.product_knowledge.media import verify_storage
        import shutil
        with TemporaryDirectory() as restored:
            shutil.copytree(self.storage.name, restored, dirs_exist_ok=True)
            with self.sessions() as db:
                self.assertEqual(verify_storage(db,restored),dict(references=2,missing=0,damaged=0))
                path=next(Path(restored).rglob('*.webp'));path.write_bytes(b'damaged')
                self.assertEqual(verify_storage(db,restored)['damaged'],1)
                path.unlink();self.assertEqual(verify_storage(db,restored)['missing'],1)

    def test_photo_content_errors_and_rollback(self):
        for content,mime,status in [(b'<svg/>','image/svg+xml',415),(b'junk','image/png',422),(image_bytes(),'image/jpeg',422),(b'x'*(10*1024*1024+1),'image/png',413)]:
            self.assertEqual(self.upload(content,mime=mime).status_code,status)
        self.assertEqual(self.upload(command={'expected_version':1,'reason':'  '}).status_code,422)
        with patch('app.product_knowledge.media.MAX_PIXELS',1):self.assertEqual(self.upload().status_code,422)
        animated=BytesIO();Image.new('RGB',(10,10),'red').save(animated,format='PNG',save_all=True,append_images=[Image.new('RGB',(10,10),'blue')])
        self.assertEqual(self.upload(animated.getvalue()).status_code,422)
        with patch('app.product_knowledge.media.store',side_effect=OSError('private path')):
            result=self.upload();self.assertEqual(result.status_code,503);self.assertNotIn('private',result.text)
        with patch('app.product_knowledge.management.record_audit_event',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.upload()
        self.assertIsNone(self.client.get('/products/'+self.pid).json()['photo'])
        self.assertEqual(self.client.get('/products/'+self.pid).json()['version'],1)
        self.assertEqual(self.upload(pid=str(uuid4())).status_code,404)
        self.client.request('DELETE','/products/'+self.pid,json=self.command())
        self.assertEqual(self.upload().status_code,409)
        self.client.post('/products/'+self.pid+'/restore',json=self.command())
        for fmt,mime in [('JPEG','image/jpeg'),('WEBP','image/webp')]:
            self.assertEqual(self.upload(image_bytes(fmt=fmt),mime=mime).status_code,200)

    def test_photo_access_matrix_and_tenant_guard(self):
        from app.api.dependencies import get_current_user
        overrides=self.client.app.dependency_overrides
        actor=overrides.pop(get_current_user)
        try:
            self.assertEqual(self.client.get('/products/'+self.pid+'/photo').status_code,401)
            self.assertEqual(self.client.put('/products/'+self.pid+'/photo',data={'expected_version':1,'reason':'anonymous'},files={'file':('x.png',image_bytes(),'image/png')}).status_code,401)
            self.assertEqual(self.client.request('DELETE','/products/'+self.pid+'/photo',json={'expected_version':1,'reason':'anonymous'}).status_code,401)
        finally:
            overrides[get_current_user]=actor
        self.assertEqual(self.upload().status_code,200)
        for role in EmployeeRole:
            with self.sessions.begin() as db:
                for assignment in db.scalars(select(EmployeeRoleAssignment)):assignment.role=role
                db.get(Department,self.department_id).business_type='PRODUCTION'
            readable=role in {EmployeeRole.ADMIN,EmployeeRole.DIRECTOR,EmployeeRole.DEPUTY_DIRECTOR,EmployeeRole.NETWORK_MANAGER,EmployeeRole.CHEF_CONFECTIONER,EmployeeRole.HEAD_OF_PRODUCTION}
            writable=readable and role not in {EmployeeRole.DIRECTOR,EmployeeRole.DEPUTY_DIRECTOR}
            self.assertEqual(self.client.get('/products/'+self.pid+'/photo').status_code,200 if readable else 403,role)
            with self.sessions() as db:version=db.get(Product,UUID(self.pid)).version
            self.assertEqual(self.upload(command=dict(expected_version=version,reason=role.value)).status_code,200 if writable else 403,role)
            if not writable:self.assertEqual(self.client.request('DELETE','/products/'+self.pid+'/photo',json=dict(expected_version=version,reason='deny')).status_code,403,role)
        with self.sessions.begin() as db:
            for assignment in db.scalars(select(EmployeeRoleAssignment)):assignment.role='ADMIN'
        from tests import test_product_knowledge as k1
        with patch.object(self, "load"):
            k1.ProductKnowledgeTests.test_foreign_tenant_product_not_found(self)
        with self.sessions() as db:foreign=str(db.scalar(select(Product.id).where(Product.tenant_id=='other')))
        self.assertEqual(self.upload(pid=foreign).status_code,404)
        self.assertEqual(self.client.get('/products/'+foreign+'/photo').status_code,404)
        self.assertEqual(self.client.request('DELETE','/products/'+foreign+'/photo',json=self.command()).status_code,404)
