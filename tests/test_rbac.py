import unittest

from app.rbac import effective_role, has_permission, require_assignment


class RBACTest(unittest.TestCase):
    def test_legacy_staff_maps_to_admin(self):
        self.assertEqual(effective_role("staff"), "admin")
        self.assertTrue(has_permission("staff", "audit_read"))

    def test_operator_cannot_read_admin_audit(self):
        self.assertTrue(has_permission("operator", "dashboard_full"))
        self.assertFalse(has_permission("operator", "audit_read"))
        self.assertFalse(has_permission("operator", "staff_manage"))

    def test_partner_is_assignment_scoped(self):
        self.assertTrue(has_permission("partner", "assigned_case_read"))
        self.assertTrue(require_assignment("partner", "assigned_case_read"))
        self.assertFalse(has_permission("partner", "client_read_all"))
        self.assertFalse(has_permission("partner", "dashboard_full"))

    def test_client_only_has_own_profile_permission(self):
        self.assertTrue(has_permission("client", "own_profile_read"))
        self.assertFalse(has_permission("client", "client_read_all"))
        self.assertFalse(has_permission("client", "document_share"))

    def test_unknown_roles_and_permissions_fail_closed(self):
        self.assertIsNone(effective_role("superuser"))
        self.assertFalse(has_permission("superuser", "dashboard_full"))
        self.assertFalse(has_permission("admin", "unknown_permission"))
        self.assertFalse(has_permission(None, "dashboard_full"))


if __name__ == "__main__":
    unittest.main()
