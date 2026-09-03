import json
import os
import tempfile
import unittest
from werkzeug.security import generate_password_hash

_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
os.environ['DATABASE_URL'] = f'sqlite:///{_tmp.name}'
os.environ['FLASK_ENV'] = 'testing'
os.environ['SECRET_KEY'] = 'document-security-test-secret'
os.environ['ADMIN_EMAIL'] = 'admin-docs@example.com'
os.environ['ADMIN_PASSWORD'] = 'AdminDocs12345'

import app as app_module
from app.operations import init_operations
from app.staff_accounts import init_staff_accounts
from app.partner_access import init_partner_access
from app.document_security import init_document_security

class DocumentSecurityCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        init_staff_accounts(cls.app, app_module)
        init_partner_access(cls.app, app_module)
        init_document_security(cls.app, app_module)
        profile={'zone':{'main':'Milano','km':5},'budget':{'ideal':200000,'max':230000,'flex':5},'spaces':{'sqm':70,'beds':2,'baths':1},'timing':'3-6 mesi','style':'Appartamento','must':[],'houseTypes':['Appartamento'],'purchase':['Buono stato']}
        with cls.app.app_context():
            cls.client_ids=[]
            for i in (1,2):
                u=app_module.User(role='client',name=f'Doc Client {i}',email=f'doc-client-{i}@example.com',phone='+3900000000',active=True,password_hash=generate_password_hash('ClientDocs12345',method='scrypt'))
                app_module.db.session.add(u); app_module.db.session.flush()
                app_module.db.session.add(app_module.ClientProfile(user_id=u.id,profile_json=json.dumps(profile),status='Ricerca attiva'))
                cls.client_ids.append(u.id)
            app_module.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try: os.unlink(_tmp.name)
        except OSError: pass

    def login_admin(self):
        c=self.app.test_client(); r=c.post('/api/staff/login',json={'email':'admin-docs@example.com','password':'AdminDocs12345'}); self.assertEqual(r.status_code,200); return c

    def test_partner_document_urls_are_redacted_and_unassigned_blocked(self):
        admin=self.login_admin()
        r=admin.post('/api/admin/partners',json={'name':'Doc Partner','email':'doc-partner@example.com','password':'PartnerDocs12345','client_id':self.client_ids[0]})
        self.assertEqual(r.status_code,201)
        with self.app.app_context():
            d1=app_module.Document(client_id=self.client_ids[0],title='Assegnato',url='https://public.example/a.pdf')
            d2=app_module.Document(client_id=self.client_ids[1],title='Non assegnato',url='https://public.example/b.pdf')
            app_module.db.session.add_all([d1,d2]); app_module.db.session.commit(); assigned_id=d1.id; other_id=d2.id
        p=self.app.test_client(); self.assertEqual(p.post('/api/partner/login',json={'email':'doc-partner@example.com','password':'PartnerDocs12345'}).status_code,200)
        listing=p.get(f'/api/partner/cases/{self.client_ids[0]}/documents'); self.assertEqual(listing.status_code,200)
        doc=listing.get_json()['documents'][0]; self.assertNotIn('url',doc); self.assertEqual(doc['access_url'],f'/api/partner/documents/{assigned_id}')
        self.assertEqual(p.get(f'/api/partner/documents/{other_id}').status_code,403)
        self.assertEqual(p.get(f'/api/partner/documents/{assigned_id}').status_code,409)

if __name__ == '__main__': unittest.main()
