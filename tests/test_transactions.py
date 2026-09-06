import json
import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "transaction-test-secret"
os.environ["ADMIN_EMAIL"] = "transaction-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "TransactionAdmin12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts
from app.transactions import init_transactions


class TransactionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_accounts(cls.app, app_module)
        init_transactions(cls.app, app_module)
        with cls.app.app_context():
            client = app_module.User(
                role="client", name="Cliente Reale", email="transaction-client@example.com",
                phone="+393331234567", password_hash=generate_password_hash("ClientPass12345", method="scrypt"),
            )
            operator = app_module.User(
                role="operator", name="Operatore Trattativa", email="transaction-operator@example.com",
                phone="", password_hash=generate_password_hash("OperatorPass12345", method="scrypt"),
            )
            app_module.db.session.add_all([client, operator])
            app_module.db.session.flush()
            app_module.db.session.add(app_module.ClientProfile(
                user_id=client.id, profile_json=json.dumps({"zone": {"main": "Roma Nord"}}),
                is_test=False,
            ))
            prop = app_module.Property(ref="IMM-REALE", zone="Roma Nord", price=200000, sqm=90)
            app_module.db.session.add(prop)
            app_module.db.session.flush()
            app_module.db.session.add(app_module.Deal(
                client_id=client.id, property_id=prop.id, ref=prop.ref, stage="Proposta",
            ))
            app_module.db.session.commit()
            cls.operator_id = operator.id

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def session_for(self, email):
        with self.app.app_context():
            uid = app_module.User.query.filter_by(email=email).first().id
        client = self.app.test_client()
        with client.session_transaction() as state:
            state["uid"] = uid
            state["nonce"] = "transaction-test"
        return client

    def admin(self):
        return self.session_for("transaction-admin@example.com")

    def operator(self):
        return self.session_for("transaction-operator@example.com")

    def test_01_proposal_creates_controlled_transaction(self):
        response = self.admin().get("/api/staff/transactions")
        self.assertEqual(response.status_code, 200, response.get_json())
        row = response.get_json()["transactions"][0]
        self.assertEqual(row["stage"], "Presentazione preliminare")
        self.assertIn("Manifestazione di interesse", row["missing"][0])

    def test_02_minimum_deposit_gate_is_enforced(self):
        row = self.admin().get("/api/staff/transactions").get_json()["transactions"][0]
        transaction_id = row["id"]
        assigned = self.admin().patch(f"/api/staff/transactions/{transaction_id}", json={
            "assigned_to_user_id": self.operator_id,
            "interest_status": "Confermata", "deposit_status": "Ricevuta",
            "interest_at": "2026-09-06T12:00:00Z",
            "deposit_amount": 4999, "deposit_reference": "Ricevuta prova",
            "next_action": "Integrare la caparra", "change_note": "Registrato importo ricevuto",
        })
        self.assertEqual(assigned.status_code, 200, assigned.get_json())
        self.assertEqual(assigned.get_json()["transaction"]["stage"], "Interesse manifestato")
        self.assertIn("€5.000", assigned.get_json()["transaction"]["missing"][0])
        advanced = self.operator().patch(f"/api/staff/transactions/{transaction_id}", json={
            "deposit_amount": 5000, "next_action": "Preparare il preliminare",
            "change_note": "Caparra minima completata",
        })
        self.assertEqual(advanced.status_code, 200, advanced.get_json())
        self.assertEqual(advanced.get_json()["transaction"]["stage"], "Impegno economico")

    def test_03_only_admin_records_professional_validation(self):
        row = self.admin().get("/api/staff/transactions").get_json()["transactions"][0]
        transaction_id = row["id"]
        denied = self.operator().post(f"/api/admin/transactions/{transaction_id}/validation", json={
            "type": "legal", "status": "Verificata", "note": "Notaio incaricato",
        })
        self.assertEqual(denied.status_code, 403)
        approved = self.admin().post(f"/api/admin/transactions/{transaction_id}/validation", json={
            "type": "legal", "status": "Verificata", "note": "Verifica notaio pratica N-01",
        })
        self.assertEqual(approved.status_code, 200, approved.get_json())
        updated = self.operator().patch(f"/api/staff/transactions/{transaction_id}", json={
            "preliminary_status": "Firmato", "preliminary_reference": "Preliminare P-01",
            "next_action": "Trascrivere il preliminare", "change_note": "Preliminare firmato",
        })
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["transaction"]["stage"], "Preliminare")


if __name__ == "__main__":
    unittest.main()
