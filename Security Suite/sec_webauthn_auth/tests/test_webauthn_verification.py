# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for ceremony verification (P2-2, US-6.1 / US-6.2).

These do not attempt to forge a valid attestation: producing one would mean
reimplementing the authenticator, and a test that mocks the library into
returning success proves only that the mock works. What is tested here is
everything around the library call, which is where our own mistakes live —
challenge binding, replay, purpose confusion, credential ownership, counter
handling, and the refusal paths.

End-to-end verification against a real authenticator is a manual test; it is
recorded in PROGRESS.md as such rather than pretended to be automated.
"""

import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..models import webauthn_verify


def _client_data(challenge, ceremony="webauthn.get"):
    """Minimal clientDataJSON, base64url encoded, as the browser would send."""
    from webauthn.helpers import bytes_to_base64url

    payload = json.dumps(
        {"type": ceremony, "challenge": challenge, "origin": "https://erp.example.com"}
    ).encode()
    return bytes_to_base64url(payload)


@tagged("post_install", "-at_install")
class TestWebauthnVerification(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.Challenge = cls.env["sec.webauthn.challenge"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.origin", "https://erp.example.com"
        )

    def _credential(self, credential_id="cred-verify-1"):
        return self.Credential.sudo().create(
            {
                "user_id": self.env.user.id,
                "credential_id": credential_id,
                "public_key": "cHVibGljLWtleQ",
                "device_label": "Test key",
                "rp_id": "erp.example.com",
            }
        )

    # --- Capability reporting ---------------------------------------------
    def test_verification_reports_ready_when_library_present(self):
        self.assertEqual(
            self.Credential._verification_ready(),
            webauthn_verify.WEBAUTHN_LIB_AVAILABLE,
        )

    def test_missing_library_refuses_rather_than_degrades(self):
        with patch.object(webauthn_verify, "WEBAUTHN_LIB_AVAILABLE", False):
            with self.assertRaises(UserError):
                self.Credential._require_library()

    # --- Challenge binding -------------------------------------------------
    def test_unknown_challenge_is_refused_and_alerted(self):
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(UserError):
            self.Credential._take_challenge(
                self.env.user, _client_data("never-issued"), "authentication"
            )
        self.assertGreater(Alert.search_count([]), before)

    def test_registration_challenge_cannot_satisfy_authentication(self):
        """Purpose confusion would let an enrolment double as an approval."""
        challenge = self.Challenge.issue(self.env.user, "registration")
        with self.assertRaises(UserError):
            self.Credential._take_challenge(
                self.env.user,
                _client_data(challenge.challenge),
                "authentication",
            )

    def test_challenge_issued_to_another_user_is_refused(self):
        other = self.env["res.users"].create(
            {"name": "Other", "login": "wa_other_user"}
        )
        challenge = self.Challenge.issue(other, "authentication")
        with self.assertRaises(UserError):
            self.Credential._take_challenge(
                self.env.user,
                _client_data(challenge.challenge),
                "authentication",
            )

    def test_challenge_is_consumed_on_use(self):
        challenge = self.Challenge.issue(self.env.user, "authentication")
        self.Credential._take_challenge(
            self.env.user, _client_data(challenge.challenge), "authentication"
        )
        self.assertTrue(challenge.consumed)

    def test_replayed_challenge_is_refused_and_alerted(self):
        challenge = self.Challenge.issue(self.env.user, "authentication")
        data = _client_data(challenge.challenge)
        self.Credential._take_challenge(self.env.user, data, "authentication")
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(UserError):
            self.Credential._take_challenge(self.env.user, data, "authentication")
        self.assertGreater(Alert.search_count([]), before)

    def test_assertion_is_bound_to_one_action(self):
        """A confirmation for one approval must not authorise another."""
        challenge = self.Challenge.issue(
            self.env.user, "authentication", context_ref="override.request,1"
        )
        with self.assertRaises(UserError) as caught:
            self.Credential._take_challenge(
                self.env.user,
                _client_data(challenge.challenge),
                "authentication",
                context_ref="override.request,2",
            )
        self.assertIn("different action", str(caught.exception))

    def test_malformed_client_data_is_refused(self):
        with self.assertRaises(UserError):
            self.Credential._take_challenge(
                self.env.user, "not-valid-base64url-json", "authentication"
            )

    # --- Assertion prerequisites ------------------------------------------
    def test_assertion_from_unenrolled_credential_is_critical(self):
        challenge = self.Challenge.issue(self.env.user, "authentication")
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(UserError):
            self.Credential.verify_authentication(
                {
                    "rawId": "never-enrolled",
                    "response": {"clientDataJSON": _client_data(challenge.challenge)},
                }
            )
        alert = Alert.search([], order="id desc", limit=1)
        self.assertGreater(Alert.search_count([]), before)
        self.assertEqual(alert.severity, "critical")

    def test_revoked_credential_cannot_authenticate(self):
        credential = self._credential("to-be-revoked")
        credential.action_revoke()
        challenge = self.Challenge.issue(self.env.user, "authentication")
        with self.assertRaises(UserError):
            self.Credential.verify_authentication(
                {
                    "rawId": "to-be-revoked",
                    "response": {"clientDataJSON": _client_data(challenge.challenge)},
                }
            )

    def test_challenge_issuance_requires_an_enrolled_device(self):
        user = self.env["res.users"].create(
            {"name": "Unenrolled", "login": "wa_unenrolled"}
        )
        with self.assertRaises(UserError):
            self.Credential.with_user(user).issue_authentication_challenge()

    def test_issued_options_list_only_this_users_credentials(self):
        credential = self._credential("mine")
        options = self.Credential.issue_authentication_challenge(
            context_ref="sec.stream.lock,1"
        )
        ids = [c["id"] for c in options["allowCredentials"]]
        self.assertIn("mine", ids)
        self.assertEqual(options["userVerification"], "required")
        self.assertEqual(options["rpId"], "erp.example.com")

    # --- Sign counter ------------------------------------------------------
    def test_sign_counter_cannot_be_written_by_hand(self):
        """Otherwise a cloner could erase the regression before it is seen."""
        credential = self._credential("counter-guard")
        with self.assertRaises(UserError):
            credential.write({"sign_counter": 9999})

    def test_successful_assertion_advances_the_counter(self):
        credential = self._credential("counter-advance")
        credential._record_successful_assertion(42)
        self.assertEqual(credential.sign_counter, 42)
        self.assertTrue(credential.last_used_at)

    def test_counter_never_goes_backwards_on_record(self):
        credential = self._credential("counter-monotonic")
        credential._record_successful_assertion(42)
        credential._record_successful_assertion(7)
        self.assertEqual(credential.sign_counter, 42)

    # --- Pending-assertion marker -----------------------------------------
    def test_no_assertion_means_not_verified(self):
        self.assertFalse(self.Credential._verify_pending_assertion())

    def test_marker_is_scoped_to_its_context(self):
        class FakeRequest:
            sec_webauthn_verified_for = "sec.stream.lock,1"

        with patch.object(webauthn_verify, "WEBAUTHN_LIB_AVAILABLE", True):
            with patch("odoo.http.request", FakeRequest()):
                self.assertTrue(
                    self.Credential._verify_pending_assertion("sec.stream.lock,1")
                )
                self.assertFalse(
                    self.Credential._verify_pending_assertion("sec.stream.lock,2")
                )

    # --- Integration with the P1-6 toggle ----------------------------------
    def test_stream_lock_now_refuses_an_unconfirmed_toggle(self):
        """With verification available, absent confirmation must block."""
        Lock = self.env["sec.stream.lock"]
        self.assertTrue(Lock._webauthn_available())
        if not self.Credential._verification_ready():
            self.skipTest("py_webauthn not installed in this environment")
        with self.assertRaises(UserError):
            Lock._confirm_strong_auth()
