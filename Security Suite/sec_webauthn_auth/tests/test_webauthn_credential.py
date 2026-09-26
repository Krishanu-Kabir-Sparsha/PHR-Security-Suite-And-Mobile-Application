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

    # --- Transports: where the credential actually lives -------------------
    def test_allow_credentials_carries_transports(self):
        """Without them the platform cannot route to the right authenticator.

        Windows asked for a USB key to use a Windows Hello credential sitting on
        the same machine, because the descriptor said nothing about where the
        key was. The transports are recorded at enrolment and simply were not
        being sent.
        """
        credential = self.Credential.sudo().create(
            {
                "user_id": self.user.id,
                "credential_id": "cred-internal",
                "public_key": "cG9zc2libHktYS1rZXk",
                "device_label": "Windows Hello",
                "transports": "internal,hybrid",
                "rp_id": "erp.example.com",
            }
        )
        descriptor = self.Credential._credential_descriptor(credential)
        self.assertEqual(descriptor["type"], "public-key")
        self.assertEqual(descriptor["id"], "cred-internal")
        self.assertEqual(descriptor["transports"], ["internal", "hybrid"])

    def test_unknown_transports_are_omitted_not_guessed(self):
        """An empty list means "try everything", which is the old behaviour.
        A wrong one actively hides the authenticator that would have worked."""
        credential = self.Credential.sudo().create(
            {
                "user_id": self.user.id,
                "credential_id": "cred-unknown",
                "public_key": "cG9zc2libHktYS1rZXk",
                "device_label": "Legacy",
                "rp_id": "erp.example.com",
            }
        )
        descriptor = self.Credential._credential_descriptor(credential)
        self.assertNotIn("transports", descriptor)

    def test_transports_read_from_either_response_shape(self):
        """Android returns them at response.transports; the browser page here
        builds its payload by hand and puts them at the top level. Reading only
        one shape stores nothing and reintroduces the USB-key prompt."""
        native = {"response": {"transports": ["internal"]}}
        browser = {"transports": ["usb", "nfc"]}
        self.assertEqual(
            self.Credential._transports_from(native), ["internal"]
        )
        self.assertEqual(
            self.Credential._transports_from(browser), ["usb", "nfc"]
        )
        self.assertEqual(self.Credential._transports_from({}), [])
        self.assertEqual(self.Credential._transports_from(None), [])

    # --- Starting over -----------------------------------------------------
    def test_reset_enrolment_needs_administrator_rights(self):
        """Anyone able to clear an enrolment silently could then enrol their own
        device and approve in that person's name."""
        ordinary = self.env["res.users"].create(
            {"name": "Ordinary", "login": "wa_ordinary"}
        )
        with self.assertRaises(UserError):
            self.Credential.with_user(ordinary).reset_enrolment_for(self.user)

    def test_reset_clears_archived_history_too(self):
        """This is the whole point. Revocation archives rather than deletes, and
        the enrolment gate reads history, so an archived credential still sends
        the user to break-glass recovery."""
        active = self._credential("cred-active")
        revoked = self._credential("cred-revoked")
        revoked.sudo().active = False

        removed = self.Credential.reset_enrolment_for(
            self.user, reason="Handset replaced"
        )

        self.assertEqual(removed, 2)
        self.assertFalse(active.exists())
        self.assertFalse(revoked.exists())
        self.assertFalse(
            self.Credential.sudo()
            .with_context(active_test=False)
            .search([("user_id", "=", self.user.id)])
        )

    def test_reset_on_a_user_with_no_history_is_a_no_op(self):
        fresh = self.env["res.users"].create(
            {"name": "Fresh", "login": "wa_fresh"}
        )
        self.assertEqual(self.Credential.reset_enrolment_for(fresh), 0)

    # --- The reset wizard --------------------------------------------------
    def test_wizard_previews_what_will_be_deleted(self):
        """"Reset" reads like clearing a form until you find out it was not.

        The count includes revoked credentials on purpose: those are precisely
        what keeps the user on the break-glass route, so a preview that hid them
        would understate both what this does and why it is needed.
        """
        self._credential("cred-live")
        revoked = self._credential("cred-dead")
        revoked.sudo().active = False

        wizard = self.env["sec.webauthn.reset.wizard"].create(
            {"user_id": self.user.id, "reason": "Handset replaced"}
        )
        self.assertEqual(wizard.credential_count, 2)
        self.assertIn("[revoked]", wizard.credential_summary)

    def test_wizard_refuses_when_there_is_nothing_to_clear(self):
        """Otherwise it reports success for an operation that did nothing."""
        fresh = self.env["res.users"].create(
            {"name": "Untouched", "login": "wa_untouched"}
        )
        wizard = self.env["sec.webauthn.reset.wizard"].create(
            {"user_id": fresh.id, "reason": "Testing"}
        )
        with self.assertRaises(UserError):
            wizard.action_reset()

    def test_wizard_clears_the_history(self):
        self._credential("cred-a")
        revoked = self._credential("cred-b")
        revoked.sudo().active = False

        wizard = self.env["sec.webauthn.reset.wizard"].create(
            {"user_id": self.user.id, "reason": "Starting fresh for testing"}
        )
        wizard.action_reset()

        self.assertFalse(
            self.Credential.sudo()
            .with_context(active_test=False)
            .search([("user_id", "=", self.user.id)])
        )

    # --- The unlink guard, and its one exception ---------------------------
    def test_credentials_cannot_be_deleted_normally(self):
        """A credential is evidence for every approval it authenticated."""
        credential = self._credential("cred-evidence")
        with self.assertRaises(UserError):
            credential.unlink()
        self.assertTrue(credential.exists())

    def test_the_refusal_says_where_the_sanctioned_route_is(self):
        """Otherwise an administrator with a genuine need concludes there is no
        way to do it and starts deleting rows in the database."""
        credential = self._credential("cred-signpost")
        with self.assertRaises(UserError) as caught:
            credential.unlink()
        self.assertIn("Reset Enrolment", str(caught.exception))

    def test_the_reset_context_alone_is_not_authorisation(self):
        """A context key is a request, not a permission.

        Re-checked inside unlink rather than trusted from the caller, because
        anything holding sudo() could otherwise set it and delete freely.
        """
        ordinary = self.env["res.users"].create(
            {"name": "Ordinary Two", "login": "wa_ordinary_two"}
        )
        credential = self._credential("cred-forged")
        Key = self.Credential.RESET_CONTEXT_KEY
        with self.assertRaises(UserError):
            credential.with_user(ordinary).with_context(**{Key: True}).unlink()
        self.assertTrue(credential.exists())
