# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for cloned-authenticator detection (P2-3, US-6.2).

The signature re-check is patched in these tests rather than driven with real
crypto: producing a validly-signed assertion with a regressed counter would mean
implementing an authenticator. What is tested is the decision logic on top,
which is where the interesting failure modes are — in particular that a forged
low-counter response cannot be used to revoke somebody else's key.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCloneDetection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.owner = cls.env["res.users"].create(
            {"name": "Key Owner", "login": "clone_owner"}
        )

    def _credential(self, credential_id="clone-test", counter=10):
        credential = self.Credential.sudo().create(
            {
                "user_id": self.owner.id,
                "credential_id": credential_id,
                "public_key": "cHVibGljLWtleQ",
                "device_label": "Hardware key",
                "rp_id": "erp.example.com",
            }
        )
        credential._record_successful_assertion(counter)
        return credential

    # --- Error classification ---------------------------------------------
    def test_counter_error_is_recognised(self):
        credential = self._credential()
        self.assertTrue(
            credential._is_counter_regression_error(
                Exception("Response sign count of 3 was not greater than current count of 9")
            )
        )

    def test_other_errors_are_not_treated_as_regressions(self):
        credential = self._credential()
        for message in (
            "Could not verify authentication signature",
            "Unexpected client data type",
            "User verification is required but user was not verified",
        ):
            self.assertFalse(
                credential._is_counter_regression_error(Exception(message)),
                message,
            )

    # --- The denial-of-service guard --------------------------------------
    def test_forged_low_counter_does_not_revoke_the_credential(self):
        """Otherwise anyone could remotely disable an approver's key."""
        credential = self._credential("dos-target")
        with patch.object(
            type(credential), "_signature_valid_ignoring_counter", return_value=False
        ):
            verdict = credential._handle_counter_regression({}, "challenge")
        self.assertEqual(verdict, "forgery")
        self.assertTrue(credential.active, "A forgery must not revoke the key")
        self.assertFalse(credential.clone_suspected)

    def test_forgery_is_still_alerted_as_critical(self):
        credential = self._credential("dos-alerted")
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with patch.object(
            type(credential), "_signature_valid_ignoring_counter", return_value=False
        ):
            credential._handle_counter_regression({}, "challenge")
        alert = Alert.search([], order="id desc", limit=1)
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(alert.severity, "critical")
        self.assertIn("NOT been revoked", alert.reason)

    # --- Genuine clone -----------------------------------------------------
    def test_validly_signed_regression_revokes_the_credential(self):
        credential = self._credential("real-clone")
        with patch.object(
            type(credential), "_signature_valid_ignoring_counter", return_value=True
        ):
            verdict = credential._handle_counter_regression({}, "challenge")
        self.assertEqual(verdict, "clone")
        self.assertFalse(credential.active)
        self.assertTrue(credential.clone_suspected)
        self.assertTrue(credential.clone_detected_at)

    def test_clone_raises_a_critical_alert_naming_the_owner(self):
        credential = self._credential("clone-alert")
        Alert = self.env["anomaly.alert"].sudo()
        with patch.object(
            type(credential), "_signature_valid_ignoring_counter", return_value=True
        ):
            credential._handle_counter_regression({}, "challenge")
        alert = Alert.search([], order="id desc", limit=1)
        self.assertEqual(alert.severity, "critical")
        self.assertIn("clone_owner", alert.reason)

    def test_revoked_clone_cannot_be_used_again(self):
        credential = self._credential("clone-blocked")
        with patch.object(
            type(credential), "_signature_valid_ignoring_counter", return_value=True
        ):
            credential._handle_counter_regression({}, "challenge")
        self.assertNotIn(
            credential, self.Credential.enrolled_for(self.owner)
        )

    # --- Authenticators without counters ----------------------------------
    def test_constant_zero_counter_is_not_a_regression(self):
        """Synced passkeys report zero forever; revoking them would be wrong."""
        credential = self.Credential.sudo().create(
            {
                "user_id": self.owner.id,
                "credential_id": "passkey",
                "public_key": "a2V5",
                "device_label": "Phone passkey",
                "rp_id": "erp.example.com",
            }
        )
        credential._record_successful_assertion(0)
        credential._record_successful_assertion(0)
        self.assertTrue(credential.active)
        self.assertFalse(credential.clone_suspected)
        self.assertFalse(credential.counter_supported)

    def test_counter_supported_stays_true_for_real_counters(self):
        credential = self._credential("counting-key", counter=5)
        self.assertTrue(credential.counter_supported)
        credential._record_successful_assertion(6)
        self.assertTrue(credential.counter_supported)
        self.assertEqual(credential.sign_counter, 6)

    def test_last_counter_seen_is_recorded(self):
        credential = self._credential("counter-seen", counter=3)
        credential._record_successful_assertion(9)
        self.assertEqual(credential.last_counter_seen, 9)

    # --- Reporting ---------------------------------------------------------
    def test_report_lists_credentials_without_clone_detection(self):
        credential = self.Credential.sudo().create(
            {
                "user_id": self.owner.id,
                "credential_id": "reported-passkey",
                "public_key": "a2V5",
                "device_label": "Synced passkey",
                "rp_id": "erp.example.com",
            }
        )
        credential._record_successful_assertion(0)
        report = self.Credential.clone_detection_report()
        devices = [
            entry["device"]
            for entry in report["credentials_without_clone_detection"]
        ]
        self.assertIn("Synced passkey", devices)

    def test_report_is_clean_when_no_clones_suspected(self):
        self._credential("clean-key")
        self.assertTrue(self.Credential.clone_detection_report()["clean"])

    def test_report_lists_suspected_clones(self):
        credential = self._credential("suspect-key")
        with patch.object(
            type(credential), "_signature_valid_ignoring_counter", return_value=True
        ):
            credential._handle_counter_regression({}, "challenge")
        report = self.Credential.clone_detection_report()
        self.assertFalse(report["clean"])
        self.assertIn(
            "clone_owner", [e["user"] for e in report["clones_suspected"]]
        )

    def test_owner_is_notified_of_a_clone(self):
        credential = self._credential("notify-key")
        with patch.object(
            type(credential), "_signature_valid_ignoring_counter", return_value=True
        ):
            credential._handle_counter_regression({}, "challenge")
        messages = self.owner.partner_id.message_ids.filtered(
            lambda m: "revoked" in (m.subject or "").lower()
        )
        self.assertTrue(messages, "The key's owner was not notified")
