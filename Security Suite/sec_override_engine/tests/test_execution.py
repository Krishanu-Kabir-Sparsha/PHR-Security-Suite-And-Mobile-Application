# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for override execution and automatic re-freeze (P2-8).

This is the end-to-end test of the BRD's central claim: a confirmed record
cannot be changed except through three independent WebAuthn-authenticated
approvals, and even then only in the exact way that was approved.
"""

import base64
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOverrideExecution(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["override.request"]
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.Ticket = cls.env["sec.freeze.unlock.ticket"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.partner = cls.env["res.partner"].create({"name": "Exec Customer"})
        cls.other_partner = cls.env["res.partner"].create({"name": "Exec Other"})
        cls.product = cls.env["product.product"].create(
            {"name": "Exec Product", "list_price": 100.0}
        )
        cls.category = cls.env.ref("sec_override_engine.reason_data_entry_error")
        cls.dept = cls._approver("exec_dept", "sec_plaza_rbac.role_dept_head_sales")
        cls.compliance = cls._approver(
            "exec_compliance", "sec_plaza_rbac.role_compliance_lead"
        )
        cls.ceo = cls._approver("exec_ceo", "sec_plaza_rbac.role_ceo_owner")

    @classmethod
    def _approver(cls, login, role_xmlid):
        user = cls.env["res.users"].create({"name": login, "login": login})
        role = cls.env.ref(role_xmlid)
        user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, role.group_id.id)]}
        )
        cls.env["sec.webauthn.credential"].sudo().create(
            {
                "user_id": user.id,
                "credential_id": "cred-%s" % login,
                "public_key": "a2V5",
                "device_label": "Key %s" % login,
                "rp_id": "erp.example.com",
            }
        )
        return user

    def _order(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {
                        "product_id": self.product.id,
                        "product_uom_qty": 1,
                        "price_unit": 10000.0,
                    })
                ],
            }
        )
        order.action_confirm()
        return order

    def _request(self, order, changes=None):
        attachment = self.env["ir.attachment"].create(
            {"name": "src.pdf", "datas": base64.b64encode(b"x")}
        )
        record = self.Request.create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.category.id,
                "justification": "Wrong client reference keyed at confirmation.",
                "proposed_changes": "Set the client order reference correctly.",
                "instruction_type": "written",
                "attachment_ids": [(4, attachment.id)],
                "change_ids": changes
                or [(0, 0, {"field_name": "client_order_ref",
                            "new_value": "PO-CORRECTED-1"})],
            }
        )
        record.action_submit()
        return record

    def _approve_all(self, record):
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=True,
            ):
                record.with_user(self.dept).validate_tier()
                record.with_user(self.compliance).validate_tier()
                record.with_user(self.ceo).validate_tier()

    # --- Structured changes are mandatory ----------------------------------
    def test_submission_requires_structured_changes(self):
        order = self._order()
        attachment = self.env["ir.attachment"].create(
            {"name": "s.pdf", "datas": base64.b64encode(b"x")}
        )
        record = self.Request.create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.category.id,
                "justification": "x",
                "proposed_changes": "prose only",
                "instruction_type": "written",
                "attachment_ids": [(4, attachment.id)],
            }
        )
        with self.assertRaises(UserError) as caught:
            record.action_submit()
        self.assertIn("exact field changes", str(caught.exception).lower())

    def test_unknown_field_is_rejected(self):
        order = self._order()
        with self.assertRaises(ValidationError):
            self._request(order, changes=[
                (0, 0, {"field_name": "not_a_field", "new_value": "x"})
            ])

    def test_current_values_are_captured_at_submission(self):
        order = self._order()
        order_ref = order.client_order_ref or ""
        record = self._request(order)
        self.assertEqual(record.change_ids[0].old_value, str(order_ref))

    # --- Execution requires full approval ----------------------------------
    def test_execution_blocked_before_approval(self):
        record = self._request(self._order())
        with self.assertRaises(UserError):
            record.action_execute()

    def test_execution_blocked_after_one_approval(self):
        record = self._request(self._order())
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=True,
            ):
                record.with_user(self.dept).validate_tier()
        with self.assertRaises(UserError):
            record.action_execute()

    # --- The happy path: the whole claim, end to end -----------------------
    def test_direct_edit_is_blocked_but_approved_override_succeeds(self):
        order = self._order()
        # Direct edit: refused.
        with self.assertRaises(UserError):
            order.write({"client_order_ref": "SNEAKY"})
        # Through the full chain: applied.
        record = self._request(order)
        self._approve_all(record)
        record.action_execute()
        order.invalidate_recordset()
        self.assertEqual(order.client_order_ref, "PO-CORRECTED-1")
        self.assertEqual(record.state, "executed")

    def test_record_is_frozen_again_immediately(self):
        order = self._order()
        record = self._request(order)
        self._approve_all(record)
        record.action_execute()
        with self.assertRaises(UserError):
            order.write({"client_order_ref": "AFTERWARDS"})

    def test_execution_records_who_and_when(self):
        record = self._request(self._order())
        self._approve_all(record)
        record.action_execute()
        self.assertTrue(record.executed_at)
        self.assertEqual(record.executed_by_id, self.env.user)
        self.assertTrue(record.unlock_ticket_id)

    def test_cannot_execute_twice(self):
        record = self._request(self._order())
        self._approve_all(record)
        record.action_execute()
        with self.assertRaises(UserError):
            record.action_execute()

    # --- Ticket scoping -----------------------------------------------------
    def test_ticket_is_spent_after_use(self):
        record = self._request(self._order())
        self._approve_all(record)
        record.action_execute()
        self.assertTrue(record.unlock_ticket_id.consumed)

    def test_spent_ticket_authorises_nothing_further(self):
        order = self._order()
        record = self._request(order)
        self._approve_all(record)
        record.action_execute()
        ticket = record.unlock_ticket_id
        with self.assertRaises(UserError):
            order.with_context(
                sec_freeze_unlock_ticket=ticket.id
            ).write({"client_order_ref": "REUSED"})

    def test_ticket_does_not_authorise_a_different_field(self):
        """An approval for one correction cannot be spent on another."""
        order = self._order()
        ticket = self.Ticket.issue(
            order, ["client_order_ref"], "override.request,0"
        )
        with self.assertRaises(UserError):
            order.with_context(
                sec_freeze_unlock_ticket=ticket.id
            ).write({"partner_id": self.other_partner.id})

    def test_ticket_does_not_authorise_a_different_record(self):
        first = self._order()
        second = self._order()
        ticket = self.Ticket.issue(
            first, ["client_order_ref"], "override.request,0"
        )
        with self.assertRaises(UserError):
            second.with_context(
                sec_freeze_unlock_ticket=ticket.id
            ).write({"client_order_ref": "WRONG RECORD"})

    def test_fabricated_ticket_id_authorises_nothing(self):
        order = self._order()
        with self.assertRaises(UserError):
            order.with_context(
                sec_freeze_unlock_ticket=999999999
            ).write({"client_order_ref": "MADE UP"})

    def test_ticket_never_authorises_deletion(self):
        """A correction is not a deletion of the thing being corrected."""
        order = self._order()
        ticket = self.Ticket.issue(
            order, ["client_order_ref"], "override.request,0"
        )
        with self.assertRaises(UserError):
            order.with_context(sec_freeze_unlock_ticket=ticket.id).unlink()

    def test_ticket_cannot_be_edited_or_deleted(self):
        order = self._order()
        ticket = self.Ticket.issue(
            order, ["client_order_ref"], "override.request,0"
        )
        with self.assertRaises(UserError):
            ticket.write({"allowed_fields": "partner_id"})
        with self.assertRaises(UserError):
            ticket.unlink()

    # --- Evidence -----------------------------------------------------------
    def test_execution_raises_a_critical_alert_naming_approvers(self):
        record = self._request(self._order())
        self._approve_all(record)
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        record.action_execute()
        alert = Alert.search([], order="id desc", limit=1)
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(alert.severity, "critical")
        self.assertIn("exec_ceo", alert.reason)

    def test_locker_entry_covers_the_whole_chain(self):
        if "audit.locker.entry" not in self.env:
            self.skipTest("sec_audit_locker not installed")
        record = self._request(self._order())
        self._approve_all(record)
        record.action_execute()
        entry = self.env["audit.locker.entry"].sudo().search(
            [("model_name", "=", "sale.order")], order="sequence desc", limit=1
        )
        self.assertIn(record.name, entry.field_changes)
        self.assertIn("exec_ceo", entry.field_changes)
