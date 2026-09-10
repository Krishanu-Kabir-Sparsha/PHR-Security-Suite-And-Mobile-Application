# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the freeze enforcement itself (PRD US-3.1, BRD FR-3.1/FR-3.2)."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRecordFreeze(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Freeze Test Customer"})
        cls.other_partner = cls.env["res.partner"].create({"name": "Someone Else"})
        cls.product = cls.env["product.product"].create(
            {"name": "Freeze Test Product", "list_price": 100.0}
        )

    def _draft_order(self):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                            "price_unit": 100.0,
                        },
                    )
                ],
            }
        )

    # --- Draft records are untouched --------------------------------------
    def test_draft_order_is_freely_editable(self):
        order = self._draft_order()
        order.partner_id = self.other_partner
        self.assertEqual(order.partner_id, self.other_partner)

    def test_draft_order_can_be_deleted(self):
        order = self._draft_order()
        order.unlink()

    # --- AC: write blocked once confirmed ---------------------------------
    def test_confirmed_order_blocks_protected_field_write(self):
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            order.partner_id = self.other_partner

    def test_confirmed_order_blocks_amount_change_via_line(self):
        """Editing the line must be blocked too, or the total is editable."""
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            order.order_line[0].price_unit = 5.0

    def test_confirmed_order_blocks_line_deletion(self):
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            order.order_line[0].unlink()

    def test_confirmed_order_blocks_unlink(self):
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            order.unlink()

    # --- AC: applies to ALL roles including admin -------------------------
    def test_sudo_does_not_bypass_the_freeze(self):
        """FR-3.1: immutability applies including to administrators."""
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            order.sudo().write({"partner_id": self.other_partner.id})

    def test_superuser_does_not_bypass_the_freeze(self):
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            order.with_user(self.env.ref("base.user_root")).write(
                {"partner_id": self.other_partner.id}
            )

    def test_setting_the_unlock_context_by_hand_achieves_nothing(self):
        """A context key any caller can set is not an authorisation mechanism."""
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            order.with_context(sec_freeze_unlock_ticket=1).write(
                {"partner_id": self.other_partner.id}
            )

    # --- Unprotected fields must keep working -----------------------------
    def test_unprotected_field_still_writable_when_frozen(self):
        """Fulfilment must not break; only business-material fields freeze."""
        order = self._draft_order()
        order.action_confirm()
        order.note = "Delivery scheduled for Tuesday."
        self.assertIn("Tuesday", order.note or "")

    def test_chatter_still_works_on_frozen_record(self):
        order = self._draft_order()
        order.action_confirm()
        order.message_post(body="Customer called about delivery.")

    # --- AC: a clear, non-technical message -------------------------------
    def test_error_message_points_to_the_override_route(self):
        order = self._draft_order()
        order.action_confirm()
        with self.assertRaises(UserError) as caught:
            order.partner_id = self.other_partner
        message = str(caught.exception)
        self.assertIn("override request", message)
        self.assertIn("CEO", message)
        self.assertNotIn("Traceback", message)

    # --- Blocked attempts are flagged -------------------------------------
    def test_blocked_write_raises_critical_anomaly_surviving_rollback(self):
        order = self._draft_order()
        order.action_confirm()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([("alert_type", "=", "frozen_record_write_attempt")])
        with self.assertRaises(UserError):
            order.partner_id = self.other_partner
        after = Alert.search_count([("alert_type", "=", "frozen_record_write_attempt")])
        self.assertGreater(after, before)
        alert = Alert.search(
            [("alert_type", "=", "frozen_record_write_attempt")],
            order="id desc",
            limit=1,
        )
        self.assertEqual(alert.severity, "critical")
        self.assertEqual(alert.res_model, "sale.order")

    # --- Enforcement switch -----------------------------------------------
    def test_disabling_enforcement_permits_the_edit(self):
        """The intended operational safety valve, and an audited one."""
        rule = self.env["sec.freeze.rule"].search(
            [("model_name", "=", "sale.order")], limit=1
        )
        order = self._draft_order()
        order.action_confirm()
        rule.enforcement_active = False
        order.partner_id = self.other_partner
        self.assertEqual(order.partner_id, self.other_partner)

    def test_posted_invoice_blocks_protected_write(self):
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "invoice_line_ids": [
                    (0, 0, {"name": "Line", "quantity": 1, "price_unit": 50.0})
                ],
            }
        )
        move.action_post()
        with self.assertRaises(UserError):
            move.partner_id = self.other_partner
