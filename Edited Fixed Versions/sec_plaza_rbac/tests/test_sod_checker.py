# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the segregation-of-duties checker (PRD US-2.2, BRD FR-2.4)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSodChecker(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Role = cls.env["role.plaza_model"]
        cls.Scan = cls.env["plaza.sod.scan"]
        cls.creator_role = cls.env.ref("sec_plaza_rbac.role_sales_exec")
        cls.approver_role = cls.env.ref("sec_plaza_rbac.role_sales_manager")
        cls.user = cls.env["res.users"].create(
            {"name": "SoD Test User", "login": "sod_test_user"}
        )

    def _grant(self, user, roles):
        """Assign Plaza role groups, bypassing the non-standard grant guard."""
        user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, role.group_id.id) for role in roles]}
        )

    # --- AC: report lists users who can both create and approve ------------
    def test_conflict_detected_across_two_roles(self):
        self._grant(self.user, [self.creator_role, self.approver_role])
        scan = self.Scan.run_scan()
        conflicts = scan.conflict_ids.filtered(lambda c: c.user_id == self.user)
        self.assertEqual(len(conflicts), 1)
        conflict = conflicts[0]
        self.assertEqual(conflict.transaction_type, "sale_order")
        self.assertIn(self.creator_role, conflict.create_role_ids)
        self.assertIn(self.approver_role, conflict.approve_role_ids)

    def test_no_conflict_for_creator_only(self):
        self._grant(self.user, [self.creator_role])
        scan = self.Scan.run_scan()
        self.assertFalse(scan.conflict_ids.filtered(lambda c: c.user_id == self.user))

    def test_no_conflict_for_approver_only(self):
        self._grant(self.user, [self.approver_role])
        scan = self.Scan.run_scan()
        self.assertFalse(scan.conflict_ids.filtered(lambda c: c.user_id == self.user))

    def test_conflict_requires_same_transaction_class(self):
        """Creating sales orders and approving purchase orders is not a conflict."""
        self._grant(
            self.user,
            [self.creator_role, self.env.ref("sec_plaza_rbac.role_purch_manager")],
        )
        scan = self.Scan.run_scan()
        self.assertFalse(scan.conflict_ids.filtered(lambda c: c.user_id == self.user))

    def test_archived_role_does_not_contribute_capability(self):
        self._grant(self.user, [self.creator_role, self.approver_role])
        self.approver_role.active = False
        scan = self.Scan.run_scan()
        self.assertFalse(scan.conflict_ids.filtered(lambda c: c.user_id == self.user))

    def test_scan_records_population_size(self):
        scan = self.Scan.run_scan()
        expected = self.env["res.users"].search_count(
            [("active", "=", True), ("share", "=", False)]
        )
        self.assertEqual(scan.users_scanned, expected)

    # --- AC: exportable and consumable by the monthly forensic report ------
    def test_latest_scan_summary_shape(self):
        self._grant(self.user, [self.creator_role, self.approver_role])
        self.Scan.run_scan()
        summary = self.Scan.latest_scan_summary()
        self.assertTrue(summary["has_scan"])
        self.assertGreaterEqual(summary["open_conflicts"], 1)
        self.assertFalse(summary["clean"])

    def test_accepting_risk_requires_a_note(self):
        self._grant(self.user, [self.creator_role, self.approver_role])
        scan = self.Scan.run_scan()
        conflict = scan.conflict_ids.filtered(lambda c: c.user_id == self.user)[0]
        with self.assertRaises(UserError):
            conflict.action_accept_risk()
        conflict.acceptance_note = "Interim cover during Q3; reviewed monthly."
        conflict.action_accept_risk()
        self.assertEqual(conflict.state, "accepted")
        self.assertEqual(conflict.accepted_by_id, self.env.user)

    def test_seed_catalog_has_no_intra_role_conflicts(self):
        """No shipped role grants create and approve on one transaction class."""
        for role in self.Role.search([("active", "=", True)]):
            by_txn = {}
            for line in role.access_line_ids:
                if not line.transaction_type or line.capability == "none":
                    continue
                by_txn.setdefault(line.transaction_type, set()).add(line.capability)
            for txn, caps in by_txn.items():
                self.assertFalse(
                    {"create", "approve"}.issubset(caps),
                    "Role %s grants both create and approve on %s" % (role.code, txn),
                )
