# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for WebAuthn-gated sequential approval (P2-6, US-5.2, FR-5.3)."""

import base64
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTierApproval(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["override.request"]
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.partner = cls.env["res.partner"].create({"name": "Tier Customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Tier Product", "list_price": 100.0}
        )
        cls.category = cls.env.ref("sec_override_engine.reason_data_entry_error")

        cls.dept_head = cls._make_approver(
            "tier_dept_head", "sec_plaza_rbac.role_dept_head_sales"
        )
        cls.compliance = cls._make_approver(
            "tier_compliance", "sec_plaza_rbac.role_compliance_lead"
        )
        cls.ceo = cls._make_approver("tier_ceo", "sec_plaza_rbac.role_ceo_owner")
        cls.requester = cls.env["res.users"].create(
            {"name": "Requester", "login": "tier_requester"}
        )

    @classmethod
    def _make_approver(cls, login, role_xmlid):
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
                "device_label": "Key for %s" % login,
                "rp_id": "erp.example.com",
            }
        )
        return user

    def _submitted_request(self):
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
        record = self.Request.create(
            {
                "res_model": "sale.order",
                "res_id": order.id,
                "reason_category_id": self.category.id,
                "justification": "Keyed 10,000 instead of 1,000.",
                "proposed_changes": "price_unit 10000 -> 1000",
                "instruction_type": "written",
                "attachment_ids": [(4, attachment.id)],
            }
        )
        record.action_submit()
        return record

    def _approve_as(self, record, user, confirmed=True):
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=confirmed,
            ):
                record.with_user(user).validate_tier()

    # --- FR-5.3: no approval without WebAuthn ------------------------------
    def test_approval_without_assertion_is_refused(self):
        record = self._submitted_request()
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=False,
            ):
                with self.assertRaises(UserError) as caught:
                    record.with_user(self.dept_head).validate_tier()
        self.assertIn("security key", str(caught.exception).lower())

    def test_refused_approval_raises_a_critical_alert(self):
        record = self._submitted_request()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=False,
            ):
                with self.assertRaises(UserError):
                    record.with_user(self.dept_head).validate_tier()
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(
            Alert.search([], order="id desc", limit=1).severity, "critical"
        )

    def test_approval_refused_when_verification_unavailable(self):
        """No silent downgrade to a password-only decision."""
        record = self._submitted_request()
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=False
        ):
            with self.assertRaises(UserError) as caught:
                record.with_user(self.dept_head).validate_tier()
        self.assertIn("refused", str(caught.exception).lower())

    def test_no_approval_record_is_written_when_refused(self):
        record = self._submitted_request()
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=False,
            ):
                with self.assertRaises(UserError):
                    record.with_user(self.dept_head).validate_tier()
        self.assertFalse(record.approval_ids)

    # --- Assertion must be bound to THIS request ---------------------------
    def test_context_ref_names_the_request(self):
        record = self._submitted_request()
        self.assertEqual(
            record._webauthn_context_ref(), "override.request,%s" % record.id
        )

    def test_assertion_for_another_request_does_not_authorise_this_one(self):
        first = self._submitted_request()
        second = self._submitted_request()
        Credential = self.env["sec.webauthn.credential"]

        def only_first(context_ref=None):
            return context_ref == first._webauthn_context_ref()

        with patch.object(
            type(Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(Credential),
                "_verify_pending_assertion",
                side_effect=lambda context_ref=None: only_first(context_ref),
            ):
                with self.assertRaises(UserError):
                    second.with_user(self.dept_head).validate_tier()

    # --- Sequencing (US-5.2, first criterion) ------------------------------
    def test_second_tier_cannot_approve_before_the_first(self):
        record = self._submitted_request()
        with self.assertRaises(UserError) as caught:
            self._approve_as(record, self.compliance)
        self.assertIn("not yet your tier", str(caught.exception).lower())

    def test_ceo_cannot_approve_first(self):
        record = self._submitted_request()
        with self.assertRaises(UserError):
            self._approve_as(record, self.ceo)

    def test_full_sequence_completes_the_request(self):
        record = self._submitted_request()
        self._approve_as(record, self.dept_head)
        self.assertEqual(record.state, "pending")
        self._approve_as(record, self.compliance)
        self.assertEqual(record.state, "pending")
        self._approve_as(record, self.ceo)
        self.assertEqual(record.state, "approved")
        self.assertTrue(record.approved_at)

    def test_non_reviewer_cannot_approve(self):
        record = self._submitted_request()
        with self.assertRaises(UserError):
            self._approve_as(record, self.requester)

    # --- Evidence ----------------------------------------------------------
    def test_each_tier_writes_an_approval_record(self):
        record = self._submitted_request()
        self._approve_as(record, self.dept_head)
        self.assertEqual(len(record.approval_ids), 1)
        approval = record.approval_ids[0]
        self.assertEqual(approval.approver_id, self.dept_head)
        self.assertEqual(approval.decision, "approve")
        self.assertTrue(approval.strongly_authenticated)
        self.assertTrue(approval.credential_id)

    def test_approval_records_are_append_only(self):
        record = self._submitted_request()
        self._approve_as(record, self.dept_head)
        approval = record.approval_ids[0]
        with self.assertRaises(UserError):
            approval.write({"decision": "reject"})
        with self.assertRaises(UserError):
            approval.unlink()

    def test_all_approvals_strong_is_true_for_a_clean_run(self):
        record = self._submitted_request()
        self._approve_as(record, self.dept_head)
        self._approve_as(record, self.compliance)
        self._approve_as(record, self.ceo)
        self.assertTrue(record.all_approvals_strong)
        self.assertEqual(record.approval_count, 3)

    def test_weak_approval_report_is_clean(self):
        record = self._submitted_request()
        self._approve_as(record, self.dept_head)
        self.assertTrue(self.Request.approvals_without_strong_auth()["clean"])

    # --- Rejection ---------------------------------------------------------
    def test_rejection_ends_the_workflow(self):
        record = self._submitted_request()
        record.with_user(self.dept_head).reject_tier()
        self.assertEqual(record.state, "rejected")

    def test_rejection_is_recorded_with_the_actor(self):
        record = self._submitted_request()
        record.with_user(self.dept_head).reject_tier()
        rejection = record.approval_ids.filtered(
            lambda a: a.decision == "reject"
        )
        self.assertTrue(rejection)
        self.assertEqual(rejection[0].approver_id, self.dept_head)

    def test_rejection_does_not_require_a_security_key(self):
        """Friction on 'no' would discourage the safe answer."""
        record = self._submitted_request()
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=False
        ):
            record.with_user(self.dept_head).reject_tier()
        self.assertEqual(record.state, "rejected")

    def test_approval_impossible_once_rejected(self):
        record = self._submitted_request()
        record.with_user(self.dept_head).reject_tier()
        with self.assertRaises(UserError):
            self._approve_as(record, self.compliance)
