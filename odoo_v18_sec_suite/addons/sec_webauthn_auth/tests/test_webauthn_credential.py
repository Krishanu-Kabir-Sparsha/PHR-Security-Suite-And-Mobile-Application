# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for credential storage, challenges and enrolment sufficiency."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebauthnCredential(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.Challenge = cls.env["sec.webauthn.challenge"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.user = cls.env["res.users"].create(
            {"name": "Approver", "login": "wa_approver"}
        )

    def _credential(self, credential_id="cred-1", user=None):
        return self.Credential.sudo().create(
            {
                "user_id": (user or self.user).id,
                "credential_id": credential_id,
                "public_key": "cG9zc2libHktYS1rZXk",
                "device_label": "Work phone",
                "rp_id": "erp.example.com",
            }
        )

    # --- Storage rules -----------------------------------------------------
    def test_only_public_material_is_stored(self):
        credential = self._credential()
        self.assertNotIn("private_key", credential._fields)
        self.assertNotIn("biometric", str(list(credential._fields)))

    def test_credential_id_is_unique(self):
        self._credential("dup")
        with self.assertRaises(Exception):
            self._credential("dup")

    def test_cryptographic_material_is_immutable(self):
        credential = self._credential()
        with self.assertRaises(UserError):
            credential.write({"public_key": "c29tZXRoaW5nLWVsc2U"})
        with self.assertRaises(UserError):
            credential.write({"credential_id": "swapped"})

    def test_label_remains_editable(self):
        credential = self._credential()
        credential.device_label = "Old work phone"
        self.assertEqual(credential.device_label, "Old work phone")

    def test_credentials_cannot_be_deleted(self):
        credential = self._credential()
        with self.assertRaises(UserError):
            credential.unlink()

    def test_revoke_deactivates_and_alerts(self):
        credential = self._credential()
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        credential.action_revoke()
        self.assertFalse(credential.active)
        self.assertGreater(Alert.search_count([]), before)

    def test_credential_for_wrong_rp_is_rejected(self):
        with self.assertRaises(Exception):
            self.Credential.sudo().create(
                {
                    "user_id": self.user.id,
                    "credential_id": "wrong-rp",
                    "public_key": "a2V5",
                    "device_label": "Stale",
                    "rp_id": "old.example.com",
                }
            )

    # --- Challenges (US-6.2) ----------------------------------------------
    def test_challenge_is_single_use(self):
        challenge = self.Challenge.issue(self.user, "registration")
        self.assertTrue(challenge.consume())
        self.assertFalse(challenge.consume())

    def test_challenge_expires(self):
        challenge = self.Challenge.issue(self.user, "registration")
        challenge.sudo().write(
            {"expires_at": fields.Datetime.now() - timedelta(minutes=1)}
        )
        self.assertFalse(challenge.consume())

    def test_challenge_ttl_is_five_minutes(self):
        challenge = self.Challenge.issue(self.user, "registration")
        delta = challenge.expires_at - challenge.created_at
        self.assertEqual(delta, timedelta(minutes=5))

    def test_challenges_are_random(self):
        one = self.Challenge.issue(self.user, "registration")
        two = self.Challenge.issue(self.user, "registration")
        self.assertNotEqual(one.challenge, two.challenge)

    def test_challenge_carries_its_purpose(self):
        """A registration challenge must never satisfy an authentication."""
        challenge = self.Challenge.issue(self.user, "authentication")
        self.assertEqual(challenge.purpose, "authentication")

    # --- Enrolment sufficiency (BRD FR-6.5) --------------------------------
    def test_nuclear_key_holder_needs_two_authenticators(self):
        ceo_role = self.env.ref("sec_plaza_rbac.role_ceo_owner")
        self.user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, ceo_role.group_id.id)]}
        )
        status = self.Credential.check_enrolment_sufficient(self.user)
        self.assertTrue(status["is_nuclear_key"])
        self.assertEqual(status["required"], 2)
        self.assertFalse(status["sufficient"])

        self._credential("ceo-phone")
        self.assertFalse(
            self.Credential.check_enrolment_sufficient(self.user)["sufficient"]
        )
        self._credential("ceo-hardware-key")
        self.assertTrue(
            self.Credential.check_enrolment_sufficient(self.user)["sufficient"]
        )

    def test_ordinary_user_needs_none(self):
        status = self.Credential.check_enrolment_sufficient(self.user)
        self.assertEqual(status["required"], 0)
        self.assertTrue(status["sufficient"])

    def test_tier_one_approver_needs_one(self):
        role = self.env.ref("sec_plaza_rbac.role_dept_head_sales")
        self.user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, role.group_id.id)]}
        )
        self.assertEqual(
            self.Credential.check_enrolment_sufficient(self.user)["required"], 1
        )

    def test_enrolment_report_lists_outstanding_users(self):
        role = self.env.ref("sec_plaza_rbac.role_compliance_lead")
        self.user.with_context(plaza_bypass_grant_check=True).write(
            {"groups_id": [(4, role.group_id.id)]}
        )
        report = self.env["res.users"].webauthn_enrolment_report()
        self.assertFalse(report["ready"])
        self.assertIn(
            "wa_approver", [f["user"] for f in report["outstanding"]]
        )

    # --- The P2-2 seam ------------------------------------------------------
    def test_verification_readiness_tracks_the_library(self):
        """Updated in P2-2. Before it, this asserted readiness was False.

        Kept as a readiness assertion rather than deleted, because the property
        that matters is unchanged: the system never claims verification it
        cannot perform. What changed is that it can now perform it.
        """
        from ..models import webauthn_verify

        self.assertEqual(
            self.Credential._verification_ready(),
            webauthn_verify.WEBAUTHN_LIB_AVAILABLE,
        )

    def test_no_assertion_is_never_reported_as_verified(self):
        self.assertFalse(self.Credential._verify_pending_assertion())
