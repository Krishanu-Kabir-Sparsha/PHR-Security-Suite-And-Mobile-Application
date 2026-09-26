# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Adversarial tests for the override chain (P4-4)."""

import base64
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOverrideAdversarial(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.partner = cls.env["res.partner"].create({"name": "Adv Customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Adv Product", "list_price": 100.0}
        )
        cls.category = cls.env.ref("sec_override_engine.reason_data_entry_error")
        cls.dept = cls._approver("adv_dept", "sec_plaza_rbac.role_dept_head_sales")
        cls.compliance = cls._approver(
            "adv_compliance", "sec_plaza_rbac.role_compliance_lead"
        )
        cls.ceo = cls._approver("adv_ceo", "sec_plaza_rbac.role_ceo_owner")

    @classmethod
    def _approver(cls, login, role_xmlid):
        user = cls.env["res.users"].create({"name": login, "login": login})
        role = cls.env.ref(role_xmlid)
        user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, role.group_id.id)]}
        )
        cls.env["sec.webauthn.credential"].sudo().create(
            {"user_id": user.id, "credential_id": "cred-%s" % login,
             "public_key": "a2V5", "device_label": login,
             "rp_id": "erp.example.com"}
        )
        return user

    def _approved_request(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {"product_id": self.product.id,
                            "product_uom_qty": 1, "price_unit": 100.0})
                ],
            }
        )
        order.action_confirm()
        attachment = self.env["ir.attachment"].create(
            {"name": "s.pdf", "datas": base64.b64encode(b"x")}
        )
        record = self.env["override.request"].create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.category.id,
                "justification": "Reference keyed wrong.",
                "proposed_changes": "client_order_ref -> PO-1",
                "instruction_type": "written",
                "attachment_ids": [(4, attachment.id)],
                "change_ids": [
                    (0, 0, {"field_name": "client_order_ref",
                            "new_value": "PO-1"})
                ],
            }
        )
        record.action_submit()
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
        return record, order

    # --- FINDING 2 (P4-4): rewriting what was approved ---------------------
    def test_cannot_change_an_approved_value_before_execution(self):
        """This worked before the adversarial review.

        The parent locks its justification under review, but the actual field
        values sat in a child model with full write rights for every user.
        """
        record, _order = self._approved_request()
        with self.assertRaises(UserError):
            record.change_ids[0].write({"new_value": "SOMETHING ELSE"})

    def test_cannot_add_a_change_after_approval(self):
        record, _order = self._approved_request()
        with self.assertRaises(UserError):
            self.env["override.change"].create(
                {
                    "request_id": record.id,
                    "field_name": "client_order_ref",
                    "new_value": "SNEAKY",
                }
            )

    def test_cannot_remove_a_change_after_approval(self):
        record, _order = self._approved_request()
        with self.assertRaises(UserError):
            record.change_ids[0].unlink()

    def test_altering_an_approved_change_raises_a_critical_alert(self):
        record, _order = self._approved_request()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(UserError):
            record.change_ids[0].write({"new_value": "X"})
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    def test_execution_applies_exactly_what_was_approved(self):
        record, order = self._approved_request()
        record.action_execute()
        order.invalidate_recordset()
        self.assertEqual(order.client_order_ref, "PO-1")

    def test_changes_are_still_editable_while_draft(self):
        """The fix must not stop a requester correcting their own draft."""
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        order.action_confirm()
        record = self.env["override.request"].create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.category.id,
                "justification": "x",
                "proposed_changes": "y",
                "instruction_type": "written",
                "change_ids": [
                    (0, 0, {"field_name": "client_order_ref",
                            "new_value": "FIRST"})
                ],
            }
        )
        record.change_ids[0].write({"new_value": "SECOND"})
        self.assertEqual(record.change_ids[0].new_value, "SECOND")
