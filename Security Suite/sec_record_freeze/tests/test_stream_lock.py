# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the back-end stream lock toggles (PRD US-3.2, BRD FR-3.3)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStreamLock(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lock = cls.env["sec.stream.lock"]
        cls.sales_lock = cls.env.ref("sec_record_freeze.stream_lock_sales")
        cls.purchase_lock = cls.env.ref("sec_record_freeze.stream_lock_purchase")
        cls.partner = cls.env["res.partner"].create({"name": "Lock Test Partner"})

        cls.super_admin = cls.env["res.users"].create(
            {
                "name": "Suite Super Admin",
                "login": "lock_super_admin",
                "groups_id": [
                    (4, cls.env.ref("sec_plaza_rbac.group_security_super_admin").id),
                    (4, cls.env.ref("sales_team.group_sale_salesman").id),
                    (4, cls.env.ref("purchase.group_purchase_user").id),
                ],
            }
        )
        cls.ordinary_user = cls.env["res.users"].create(
            {
                "name": "Ordinary Sales User",
                "login": "lock_ordinary_user",
                "groups_id": [
                    (4, cls.env.ref("sales_team.group_sale_salesman").id),
                    (4, cls.env.ref("purchase.group_purchase_user").id),
                ],
            }
        )

    def tearDown(self):
        for lock in (self.sales_lock, self.purchase_lock):
            if lock.locked:
                lock.with_user(self.super_admin).action_release_lock(
                    reason="Test teardown."
                )
        super().tearDown()

    # --- Who may toggle ----------------------------------------------------
    def test_ordinary_user_cannot_engage_lock(self):
        with self.assertRaises(UserError):
            self.sales_lock.with_user(self.ordinary_user).action_engage_lock(
                reason="Trying it on."
            )

    def test_super_admin_can_engage_lock(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Suspected incident; freezing sales for review."
        )
        self.assertTrue(self.sales_lock.locked)
        self.assertEqual(self.sales_lock.locked_by_id, self.super_admin)
        self.assertTrue(self.sales_lock.locked_at)

    def test_reason_is_mandatory(self):
        with self.assertRaises(UserError):
            self.sales_lock.with_user(self.super_admin).action_engage_lock(reason="  ")

    def test_cannot_double_lock(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(reason="First.")
        with self.assertRaises(UserError):
            self.sales_lock.with_user(self.super_admin).action_engage_lock(
                reason="Second."
            )

    def test_locked_field_cannot_be_written_directly(self):
        """Direct writes would skip the reason, confirmation and history."""
        with self.assertRaises(UserError):
            self.sales_lock.sudo().write({"locked": True})

    # --- AC: Sales and Purchase are independent ----------------------------
    def test_locking_sales_does_not_affect_purchase(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Sales only."
        )
        self.assertTrue(self.sales_lock.locked)
        self.assertFalse(self.purchase_lock.locked)
        # A purchase order must still be creatable.
        self.env["purchase.order"].with_user(self.super_admin).create(
            {"partner_id": self.partner.id}
        )

    # --- Enforcement -------------------------------------------------------
    def test_locked_stream_blocks_edit_by_ordinary_user(self):
        order = self.env["sale.order"].with_user(self.ordinary_user).create(
            {"partner_id": self.partner.id}
        )
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Lockdown."
        )
        with self.assertRaises(UserError):
            order.with_user(self.ordinary_user).write({"note": "change"})

    def test_locked_stream_blocks_creation_by_ordinary_user(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Lockdown."
        )
        with self.assertRaises(UserError):
            self.env["sale.order"].with_user(self.ordinary_user).create(
                {"partner_id": self.partner.id}
            )

    def test_locked_stream_blocks_draft_records_too(self):
        """Unlike the confirm-state freeze, a lockdown covers draft work."""
        order = self.env["sale.order"].with_user(self.ordinary_user).create(
            {"partner_id": self.partner.id}
        )
        self.assertEqual(order.state, "draft")
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Lockdown."
        )
        with self.assertRaises(UserError):
            order.with_user(self.ordinary_user).unlink()

    def test_super_admin_can_still_work_while_locked(self):
        order = self.env["sale.order"].with_user(self.super_admin).create(
            {"partner_id": self.partner.id}
        )
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Lockdown."
        )
        order.with_user(self.super_admin).write({"note": "admin note"})

    def test_release_restores_normal_working(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(reason="Lock.")
        self.sales_lock.with_user(self.super_admin).action_release_lock(
            reason="Investigation closed."
        )
        self.assertFalse(self.sales_lock.locked)
        self.env["sale.order"].with_user(self.ordinary_user).create(
            {"partner_id": self.partner.id}
        )

    def test_block_message_names_the_reason(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Forensic window open until Friday."
        )
        with self.assertRaises(UserError) as caught:
            self.env["sale.order"].with_user(self.ordinary_user).create(
                {"partner_id": self.partner.id}
            )
        self.assertIn("Forensic window", str(caught.exception))

    # --- AC: the toggle is itself logged with before/after -----------------
    def test_toggle_is_logged_with_actor_and_states(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(
            reason="Audit trail check."
        )
        entry = self.sales_lock.log_ids[0]
        self.assertEqual(entry.actor_id, self.super_admin)
        self.assertFalse(entry.state_before)
        self.assertTrue(entry.state_after)
        self.assertIn("Audit trail", entry.reason)
        self.assertTrue(entry.changed_at)

    def test_toggle_log_is_append_only(self):
        self.sales_lock.with_user(self.super_admin).action_engage_lock(reason="x.")
        entry = self.sales_lock.log_ids[0]
        with self.assertRaises(UserError):
            entry.write({"reason": "rewritten"})
        with self.assertRaises(UserError):
            entry.unlink()

    def test_toggle_raises_critical_anomaly(self):
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self.sales_lock.with_user(self.super_admin).action_engage_lock(reason="x.")
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(Alert.search([], order="id desc", limit=1).severity, "critical")

    # --- WebAuthn hook honesty ---------------------------------------------
    def test_toggle_recorded_as_weakly_authenticated_without_webauthn(self):
        """US-3.2 wants WebAuthn. It does not exist yet, so say so in the log."""
        self.assertFalse(self.Lock._webauthn_available())
        self.sales_lock.with_user(self.super_admin).action_engage_lock(reason="x.")
        self.assertFalse(self.sales_lock.log_ids[0].strongly_authenticated)

    def test_policy_can_refuse_unconfirmed_toggles(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "sec_record_freeze.allow_toggle_without_webauthn", "False"
        )
        with self.assertRaises(UserError):
            self.sales_lock.with_user(self.super_admin).action_engage_lock(reason="x.")
        self.env["ir.config_parameter"].sudo().set_param(
            "sec_record_freeze.allow_toggle_without_webauthn", "True"
        )
