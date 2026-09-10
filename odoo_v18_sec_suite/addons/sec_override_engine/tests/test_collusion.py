# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for collusion prevention (P2-7, US-5.3, BRD FR-5.1 / FR-5.2)."""

import base64
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCollusion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["override.request"]
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.partner = cls.env["res.partner"].create({"name": "Collusion Customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Collusion Product", "list_price": 100.0}
        )
        cls.category = cls.env.ref("sec_override_engine.reason_data_entry_error")

        cls.dept_role = cls.env.ref("sec_plaza_rbac.role_dept_head_sales")
        cls.compliance_role = cls.env.ref("sec_plaza_rbac.role_compliance_lead")
        cls.ceo_role = cls.env.ref("sec_plaza_rbac.role_ceo_owner")

        cls.dept_head = cls._make_user("col_dept", [cls.dept_role])
        cls.compliance = cls._make_user("col_compliance", [cls.compliance_role])
        cls.ceo = cls._make_user("col_ceo", [cls.ceo_role])
        # One person holding two tier roles: the FR-5.1 scenario.
        cls.two_hatted = cls._make_user(
            "col_two_hats", [cls.dept_role, cls.compliance_role]
        )
        cls.requester = cls._make_user("col_requester", [cls.dept_role])

    @classmethod
    def _make_user(cls, login, roles):
        user = cls.env["res.users"].create({"name": login, "login": login})
        user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, r.group_id.id) for r in roles]}
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

    def _submitted(self, requester=None):
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
        attachment = self.env["ir.attachment"].create(
            {"name": "src.pdf", "datas": base64.b64encode(b"x")}
        )
        record = self.Request.with_user(requester or self.requester).create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.category.id,
                "justification": "Keyed wrong.",
                "proposed_changes": "price_unit 10000 -> 1000",
                "instruction_type": "written",
                "attachment_ids": [(4, attachment.id)],
            }
        )
        record.action_submit()
        return record

    def _approve(self, record, user):
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=True,
            ):
                record.with_user(user).validate_tier()

    # --- FR-5.1: the requester is never an approver ------------------------
    def test_requester_cannot_approve_their_own_request(self):
        record = self._submitted(requester=self.requester)
        with self.assertRaises(UserError) as caught:
            self._approve(record, self.requester)
        self.assertIn("cannot approve", str(caught.exception).lower())

    def test_requester_self_approval_raises_a_critical_alert(self):
        record = self._submitted(requester=self.requester)
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(UserError):
            self._approve(record, self.requester)
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    # --- FR-5.1: one person cannot satisfy two tiers -----------------------
    def test_two_hatted_user_cannot_approve_twice(self):
        """The exact gap base_tier_validation leaves open."""
        record = self._submitted()
        self._approve(record, self.two_hatted)
        with self.assertRaises(UserError) as caught:
            self._approve(record, self.two_hatted)
        self.assertIn("already approved", str(caught.exception).lower())

    def test_second_approval_by_same_user_writes_no_record(self):
        record = self._submitted()
        self._approve(record, self.two_hatted)
        with self.assertRaises(UserError):
            self._approve(record, self.two_hatted)
        self.assertEqual(record.distinct_approver_count, 1)
        self.assertEqual(len(record.approval_ids), 1)

    def test_duplicate_approval_blocked_at_model_level_too(self):
        """Holds even if a future caller reaches the model directly."""
        record = self._submitted()
        self._approve(record, self.dept_head)
        with self.assertRaises(ValidationError):
            self.env["override.approval"].sudo().create(
                {
                    "request_id": record.id,
                    "tier_sequence": 20,
                    "tier_name": "Tier 2",
                    "approver_id": self.dept_head.id,
                    "decision": "approve",
                    "decided_at": "2026-09-03 10:00:00",
                    "strongly_authenticated": True,
                }
            )

    # --- FR-5.2: paired accounts ------------------------------------------
    def test_two_logins_sharing_a_contact_cannot_both_approve(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        paired = self.env["res.users"].create(
            {
                "name": "Paired Login",
                "login": "col_paired",
                "partner_id": self.dept_head.partner_id.id,
            }
        )
        paired.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, self.compliance_role.group_id.id)]}
        )
        self.env["sec.webauthn.credential"].sudo().create(
            {
                "user_id": paired.id,
                "credential_id": "cred-paired",
                "public_key": "a2V5",
                "device_label": "Paired key",
                "rp_id": "erp.example.com",
            }
        )
        with self.assertRaises(UserError) as caught:
            self._approve(record, paired)
        self.assertIn("same contact", str(caught.exception).lower())

    # --- Three genuinely distinct people still works -----------------------
    def test_three_distinct_approvers_complete_the_override(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        self._approve(record, self.compliance)
        self._approve(record, self.ceo)
        self.assertEqual(record.state, "approved")
        self.assertEqual(record.distinct_approver_count, 3)

    # --- US-5.3: the execution gate ----------------------------------------
    def test_execution_blocked_with_no_approvals(self):
        record = self._submitted()
        with self.assertRaises(UserError):
            record._assert_executable()

    def test_execution_blocked_with_two_approvals(self):
        """Two tiers without the Nuclear Key must not be enough."""
        record = self._submitted()
        self._approve(record, self.dept_head)
        self._approve(record, self.compliance)
        with self.assertRaises(UserError) as caught:
            record._assert_executable()
        self.assertIn("distinct approver", str(caught.exception).lower())

    def test_execution_allowed_with_all_three(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        self._approve(record, self.compliance)
        self._approve(record, self.ceo)
        self.assertTrue(record._assert_executable())

    def test_blocked_execution_raises_a_critical_alert(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(UserError):
            record._assert_executable()
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    def test_execution_gate_rejects_a_weakly_authenticated_approval(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        self._approve(record, self.compliance)
        self._approve(record, self.ceo)
        # Simulate an approval that was somehow recorded unconfirmed.
        self.env.cr.execute(
            "UPDATE override_approval SET strongly_authenticated = false "
            "WHERE request_id = %s AND id = ("
            "  SELECT MIN(id) FROM override_approval WHERE request_id = %s)",
            (record.id, record.id),
        )
        record.invalidate_recordset()
        record.approval_ids.invalidate_recordset()
        with self.assertRaises(UserError) as caught:
            record._assert_executable()
        self.assertIn("webauthn", str(caught.exception).lower())

    def test_execution_gate_re_derives_rather_than_trusting_state(self):
        """State is a conclusion; the gate re-checks the underlying records."""
        record = self._submitted()
        self._approve(record, self.dept_head)
        record.sudo().write({"state": "approved"})
        with self.assertRaises(UserError):
            record._assert_executable()

    # --- Non-blocking signal -----------------------------------------------
    def test_same_source_address_is_flagged_not_blocked(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        self._approve(record, self.compliance)
        # Both approvals recorded from the same address.
        record.approval_ids.sudo()._write({"source_ip": "10.0.0.5"})
        record.invalidate_recordset()
        record._flag_independence_signals()
        self.assertTrue(record.collusion_signal)
        self.assertEqual(record.state, "pending")

    def test_independence_report_lists_flagged_requests(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        self._approve(record, self.compliance)
        self._approve(record, self.ceo)
        record.sudo().write({"collusion_signal": True})
        report = self.Request.independence_report()
        self.assertFalse(report["clean"])
        self.assertIn(record.name, report["same_address_approvals"])

    def test_report_clean_for_a_normal_override(self):
        record = self._submitted()
        self._approve(record, self.dept_head)
        self._approve(record, self.compliance)
        self._approve(record, self.ceo)
        self.assertTrue(self.Request.independence_report()["clean"])
