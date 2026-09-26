# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for break-glass re-enrolment (P2-4, US-6.3)."""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRecovery(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.Recovery = cls.env["sec.webauthn.recovery.request"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.ceo_role = cls.env.ref("sec_plaza_rbac.role_ceo_owner")
        cls.dept_role = cls.env.ref("sec_plaza_rbac.role_dept_head_sales")
        cls.compliance_role = cls.env.ref("sec_plaza_rbac.role_compliance_lead")

        cls.requester = cls._make_user("recovery_requester", cls.ceo_role)
        cls.approver_a = cls._make_user("recovery_approver_a", cls.dept_role)
        cls.approver_b = cls._make_user("recovery_approver_b", cls.compliance_role)
        cls.bystander = cls.env["res.users"].create(
            {"name": "Bystander", "login": "recovery_bystander"}
        )
        for user in (cls.approver_a, cls.approver_b):
            cls._enrol(user, "cred-%s" % user.login)

    @classmethod
    def _make_user(cls, login, role):
        user = cls.env["res.users"].create({"name": login, "login": login})
        user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, role.group_id.id)]}
        )
        return user

    @classmethod
    def _enrol(cls, user, credential_id):
        return cls.env["sec.webauthn.credential"].sudo().create(
            {
                "user_id": user.id,
                "credential_id": credential_id,
                "public_key": "a2V5",
                "device_label": "Key for %s" % user.login,
                "rp_id": "erp.example.com",
            }
        )

    def _request(self, user=None):
        return self.Recovery.with_user(user or self.requester).create(
            {"reason": "Phone lost on the way home."}
        )

    def _approve_as(self, request_record, approver):
        """Approve, standing in for the WebAuthn confirmation."""
        with patch.object(
            type(self.Credential),
            "_verify_pending_assertion",
            return_value=True,
        ):
            request_record.with_user(approver).action_approve()

    # --- Enrolment routing (the heart of P2-4) -----------------------------
    def test_first_enrolment_is_self_service(self):
        fresh = self.env["res.users"].create(
            {"name": "New Joiner", "login": "recovery_new_joiner"}
        )
        self.assertFalse(self.Credential._check_enrolment_permitted(fresh))

    def test_replacement_without_grant_is_refused(self):
        """Credentials existed, none usable: not self-service."""
        credential = self._enrol(self.requester, "lost-key")
        credential.action_revoke()
        with self.assertRaises(UserError) as caught:
            self.Credential._check_enrolment_permitted(self.requester)
        self.assertIn("break-glass", str(caught.exception).lower())

    def test_adding_a_device_requires_proving_the_current_one(self):
        self._enrol(self.bystander, "working-key")
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=False,
            ):
                with self.assertRaises(UserError):
                    self.Credential._check_enrolment_permitted(self.bystander)

    def test_adding_a_device_succeeds_with_confirmation(self):
        self._enrol(self.bystander, "working-key-2")
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=True,
            ):
                self.assertFalse(
                    self.Credential._check_enrolment_permitted(self.bystander)
                )

    def test_approved_grant_permits_replacement(self):
        credential = self._enrol(self.requester, "dead-key")
        credential.action_revoke()
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        self._approve_as(request_record, self.approver_b)
        self.assertEqual(request_record.state, "approved")
        grant = self.Credential._check_enrolment_permitted(self.requester)
        self.assertEqual(grant, request_record)

    # --- Independence -------------------------------------------------------
    def test_requester_cannot_approve_their_own_request(self):
        request_record = self._request()
        with self.assertRaises(UserError) as caught:
            self._approve_as(request_record, self.requester)
        self.assertIn("your own", str(caught.exception).lower())

    def test_two_distinct_approvers_are_required(self):
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        self.assertEqual(request_record.state, "pending")
        self._approve_as(request_record, self.approver_b)
        self.assertEqual(request_record.state, "approved")

    def test_same_approver_cannot_approve_twice(self):
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        with self.assertRaises(UserError):
            self._approve_as(request_record, self.approver_a)

    def test_non_tier_holder_cannot_approve(self):
        request_record = self._request()
        with self.assertRaises(UserError):
            self._approve_as(request_record, self.bystander)

    def test_approver_without_an_authenticator_is_not_eligible(self):
        """An approver who cannot produce an assertion cannot confirm."""
        unarmed = self._make_user("recovery_unarmed", self.dept_role)
        eligible = self.Recovery._eligible_approvers(self.requester)
        self.assertNotIn(unarmed, eligible)
        self.assertIn(self.approver_a, eligible)

    def test_approval_requires_webauthn_confirmation(self):
        request_record = self._request()
        with patch.object(
            type(self.Credential), "_verification_ready", return_value=True
        ):
            with patch.object(
                type(self.Credential),
                "_verify_pending_assertion",
                return_value=False,
            ):
                with self.assertRaises(UserError):
                    request_record.with_user(self.approver_a).action_approve()

    # --- Rejection and expiry ----------------------------------------------
    def test_single_rejection_ends_the_request(self):
        request_record = self._request()
        request_record.with_user(self.approver_a).action_reject(reason="Not genuine.")
        self.assertEqual(request_record.state, "rejected")
        with self.assertRaises(UserError):
            self._approve_as(request_record, self.approver_b)

    def test_grant_expires(self):
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        self._approve_as(request_record, self.approver_b)
        request_record.sudo().write(
            {"expires_at": fields.Datetime.now() - timedelta(hours=1)}
        )
        self.assertFalse(self.Recovery.active_grant_for(self.requester))

    def test_expiry_cron_closes_stale_windows(self):
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        self._approve_as(request_record, self.approver_b)
        request_record.sudo().write(
            {"expires_at": fields.Datetime.now() - timedelta(hours=1)}
        )
        self.Recovery.cron_expire_grants()
        self.assertEqual(request_record.state, "expired")

    def test_grant_is_single_use(self):
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        self._approve_as(request_record, self.approver_b)
        credential = self._enrol(self.requester, "replacement-key")
        request_record.consume(credential)
        self.assertEqual(request_record.state, "consumed")
        self.assertFalse(self.Recovery.active_grant_for(self.requester))

    # --- Audit trail (US-6.3, second criterion) ----------------------------
    def test_request_raises_an_alert(self):
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self._request()
        self.assertGreater(Alert.search_count([]), before)

    def test_approval_alert_names_the_approvers(self):
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        self._approve_as(request_record, self.approver_b)
        alert = self.env["anomaly.alert"].sudo().search(
            [("name", "like", "APPROVED")], order="id desc", limit=1
        )
        self.assertTrue(alert)
        self.assertIn("recovery_approver_a", alert.reason)
        self.assertIn("recovery_approver_b", alert.reason)
        self.assertEqual(alert.severity, "critical")

    def test_approvals_are_append_only(self):
        request_record = self._request()
        self._approve_as(request_record, self.approver_a)
        approval = request_record.approval_ids[0]
        with self.assertRaises(UserError):
            approval.write({"decision": "reject"})
        with self.assertRaises(UserError):
            approval.unlink()

    def test_too_few_eligible_approvers_raises_a_critical_alert(self):
        """An unsatisfiable recovery path is an availability risk, not silence."""
        self.Credential.sudo().search(
            [("user_id", "in", (self.approver_a | self.approver_b).ids)]
        ).action_revoke()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        self._request()
        alert = Alert.search([], order="id desc", limit=1)
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(alert.severity, "critical")
