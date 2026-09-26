# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for pairing an app and verifying what it signs.

These are the tests that matter most in this module, because this path is what
a user's daily sign-in now rests on and because it is our own protocol rather
than a standard someone else has already attacked. So the cases below are
mostly about the ways a signature must *not* be accepted: replayed, rebound to
a different action, presented with a stale counter, or offered by a device that
belongs to somebody else.
"""

import base64

from odoo import fields
from odoo.exceptions import AccessDenied, ValidationError
from odoo.tests.common import TransactionCase, tagged

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    CRYPTO = True
except ImportError:  # pragma: no cover
    CRYPTO = False


def b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@tagged("post_install", "-at_install")
class TestDeviceBinding(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Credential = cls.env["sec.webauthn.credential"]
        cls.Pairing = cls.env["sec.device.pairing"]
        cls.Challenge = cls.env["sec.webauthn.challenge"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "sec_webauthn.rp_id", "erp.example.com"
        )
        cls.user = cls.env["res.users"].create(
            {"name": "Paired Person", "login": "db_person"}
        )
        cls.other = cls.env["res.users"].create(
            {"name": "Someone Else", "login": "db_other"}
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _keypair(self):
        private = Ed25519PrivateKey.generate()
        return private, b64url(private.public_key().public_bytes_raw())

    def _pair(self, user=None, private=None):
        """Pair a device the way the controller does, and return its key."""
        user = user or self.user
        issued = self.Pairing.issue_for(user)
        if private is None:
            private, public = self._keypair()
        else:
            public = b64url(private.public_key().public_bytes_raw())
        result = self.Credential.pair_bound_device(
            login=user.login,
            code=issued["code"],
            public_key=public,
            device_label="Test phone",
            platform="android",
        )
        return private, result["device_handle"]

    def _sign(self, private, challenge, context_ref, handle, counter):
        message = self.Credential._signed_payload(
            challenge, context_ref, handle, counter
        )
        return {
            "device_handle": handle,
            "challenge": challenge,
            "counter": counter,
            "signature": b64url(private.sign(message)),
        }

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------
    def test_pairing_stores_only_the_public_key(self):
        """The private half must never reach this server, by construction."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        credential = self.Credential.sudo().search(
            [("credential_id", "=", handle)]
        )
        self.assertEqual(credential.mechanism, "bound_device")
        self.assertEqual(
            credential.public_key,
            b64url(private.public_key().public_bytes_raw()),
        )
        # There is nowhere for a private key to be, and that is the point.
        self.assertNotIn("private_key", credential._fields)

    def test_a_code_works_once(self):
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        issued = self.Pairing.issue_for(self.user)
        _p1, public1 = self._keypair()
        _p2, public2 = self._keypair()
        self.Credential.pair_bound_device(
            login=self.user.login,
            code=issued["code"],
            public_key=public1,
            device_label="First",
        )
        with self.assertRaises(AccessDenied):
            self.Credential.pair_bound_device(
                login=self.user.login,
                code=issued["code"],
                public_key=public2,
                device_label="Second",
            )

    def test_a_code_does_not_work_for_another_account(self):
        """A stolen code alone binds nothing; the login must match."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        issued = self.Pairing.issue_for(self.user)
        _private, public = self._keypair()
        with self.assertRaises(AccessDenied):
            self.Credential.pair_bound_device(
                login=self.other.login,
                code=issued["code"],
                public_key=public,
                device_label="Wrong account",
            )

    def test_an_expired_code_is_refused(self):
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        issued = self.Pairing.issue_for(self.user)
        self.Pairing.sudo().search(
            [("user_id", "=", self.user.id)]
        ).write({"expires_at": fields.Datetime.now()})
        _private, public = self._keypair()
        with self.assertRaises(AccessDenied):
            self.Credential.pair_bound_device(
                login=self.user.login,
                code=issued["code"],
                public_key=public,
                device_label="Too late",
            )

    def test_guessing_is_limited(self):
        """Five wrong presentations kill the code, however many remain."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        issued = self.Pairing.issue_for(self.user)
        _private, public = self._keypair()
        for _attempt in range(5):
            with self.assertRaises(AccessDenied):
                self.Credential.pair_bound_device(
                    login=self.user.login,
                    code="ZZZZZZZZ",
                    public_key=public,
                    device_label="Guess",
                )
        # Even the right code no longer works.
        with self.assertRaises(AccessDenied):
            self.Credential.pair_bound_device(
                login=self.user.login,
                code=issued["code"],
                public_key=public,
                device_label="Real",
            )

    def test_issuing_a_code_kills_the_previous_one(self):
        """Two live codes double the guessing surface for no benefit."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        first = self.Pairing.issue_for(self.user)
        self.Pairing.issue_for(self.user)
        _private, public = self._keypair()
        with self.assertRaises(AccessDenied):
            self.Credential.pair_bound_device(
                login=self.user.login,
                code=first["code"],
                public_key=public,
                device_label="Stale",
            )

    def test_a_malformed_key_is_refused(self):
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        issued = self.Pairing.issue_for(self.user)
        with self.assertRaises(ValidationError):
            self.Credential.pair_bound_device(
                login=self.user.login,
                code=issued["code"],
                public_key=b64url(b"too-short"),
                device_label="Bad key",
            )

    def test_one_key_cannot_be_paired_twice(self):
        """Otherwise one phone could satisfy a two-device rule on its own."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, _handle = self._pair()
        issued = self.Pairing.issue_for(self.user)
        with self.assertRaises(ValidationError):
            self.Credential.pair_bound_device(
                login=self.user.login,
                code=issued["code"],
                public_key=b64url(private.public_key().public_bytes_raw()),
                device_label="Clone",
            )

    # ------------------------------------------------------------------
    # Signatures
    # ------------------------------------------------------------------
    def test_a_good_signature_verifies(self):
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        challenge = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        payload = self._sign(
            private, challenge["challenge"], "override.request,7", handle, 1
        )
        credential = self.Credential.verify_device_signature(
            self.user, payload, context_ref="override.request,7"
        )
        self.assertEqual(credential.credential_id, handle)
        self.assertEqual(credential.sign_counter, 1)

    def test_a_challenge_is_single_use(self):
        """A replayed signature must be refused even inside its lifetime."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        challenge = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        payload = self._sign(
            private, challenge["challenge"], "override.request,7", handle, 1
        )
        self.Credential.verify_device_signature(
            self.user, payload, context_ref="override.request,7"
        )
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user, payload, context_ref="override.request,7"
            )

    def test_a_signature_is_bound_to_one_action(self):
        """Confirming a sign-in must not approve an override.

        The most important test here. Without the context in the signed bytes,
        any confirmation the user gives would be a general-purpose token for
        whatever the caller chose to do with it.
        """
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        challenge = self.Credential.issue_device_challenge(
            self.user, "perfecthr.mobile.session,login"
        )
        payload = self._sign(
            private,
            challenge["challenge"],
            "perfecthr.mobile.session,login",
            handle,
            1,
        )
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user, payload, context_ref="override.request,7"
            )

    def test_signing_the_wrong_context_does_not_verify(self):
        """Even with the right challenge, the bytes must match what was issued."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        challenge = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        payload = self._sign(
            private, challenge["challenge"], "override.request,999", handle, 1
        )
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user, payload, context_ref="override.request,7"
            )

    def test_another_persons_device_cannot_sign_for_you(self):
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        _mine, _my_handle = self._pair(user=self.user)
        their_private, their_handle = self._pair(user=self.other)
        challenge = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        payload = self._sign(
            their_private,
            challenge["challenge"],
            "override.request,7",
            their_handle,
            1,
        )
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user, payload, context_ref="override.request,7"
            )

    def test_a_forged_signature_is_refused(self):
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        _private, handle = self._pair()
        other_private = Ed25519PrivateKey.generate()
        challenge = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        payload = self._sign(
            other_private,
            challenge["challenge"],
            "override.request,7",
            handle,
            1,
        )
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user, payload, context_ref="override.request,7"
            )

    def test_a_counter_that_does_not_advance_is_a_clone_signal(self):
        """Two installations holding one key is what this detects."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        first = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        self.Credential.verify_device_signature(
            self.user,
            self._sign(
                private, first["challenge"], "override.request,7", handle, 5
            ),
            context_ref="override.request,7",
        )
        second = self.Credential.issue_device_challenge(
            self.user, "override.request,8"
        )
        Alert = self.env["anomaly.alert"].sudo()
        before = Alert.search_count([])
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user,
                self._sign(
                    private, second["challenge"], "override.request,8", handle, 5
                ),
                context_ref="override.request,8",
            )
        # Written on a separate cursor precisely so the refusal's rollback
        # cannot erase it; that commit is visible from this transaction under
        # READ COMMITTED, which is what makes this assertion the real check.
        self.assertGreater(Alert.search_count([]), before)
        alert = Alert.search(
            [("alert_type", "=", "credential_anomaly")], order="id desc", limit=1
        )
        self.assertEqual(alert.severity, "critical")

    def test_a_clone_signal_does_not_lock_the_user_out(self):
        """Refused and alerted, but not revoked.

        Auto-revoking here would take away the user's only way into the product
        on the strength of a signal whose most likely benign cause is a restored
        device backup. The passkey path can afford to revoke because those
        credentials approve; this one signs in.
        """
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        first = self.Credential.issue_device_challenge(self.user, "ctx,1")
        self.Credential.verify_device_signature(
            self.user,
            self._sign(private, first["challenge"], "ctx,1", handle, 5),
            context_ref="ctx,1",
        )
        second = self.Credential.issue_device_challenge(self.user, "ctx,2")
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user,
                self._sign(private, second["challenge"], "ctx,2", handle, 3),
                context_ref="ctx,2",
            )
        device = self.Credential.sudo().search([("credential_id", "=", handle)])
        self.assertTrue(device.active)

    def test_a_revoked_device_cannot_sign(self):
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        challenge = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        self.Credential.sudo().search(
            [("credential_id", "=", handle)]
        ).write({"active": False})
        with self.assertRaises(AccessDenied):
            self.Credential.verify_device_signature(
                self.user,
                self._sign(
                    private, challenge["challenge"], "override.request,7", handle, 1
                ),
                context_ref="override.request,7",
            )

    # ------------------------------------------------------------------
    # How the two mechanisms sit beside each other
    # ------------------------------------------------------------------
    def test_a_paired_device_is_never_offered_to_a_browser(self):
        """No credential manager can satisfy one, so listing it strands the user."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        self._pair()
        self.Credential.sudo().create(
            {
                "user_id": self.user.id,
                "mechanism": "webauthn",
                "credential_id": "passkey-1",
                "public_key": "cG9zc2libHktYS1rZXk",
                "device_label": "Laptop",
                "rp_id": "erp.example.com",
            }
        )
        options = (
            self.Credential.with_user(self.user)
            .sudo()
            .issue_authentication_challenge(context_ref="override.request,7")
        )
        listed = {c["id"] for c in options["allowCredentials"]}
        self.assertEqual(listed, {"passkey-1"})

    def test_both_mechanisms_count_toward_the_two_device_rule(self):
        """A Tier 3 approver's second device may legitimately be their phone."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        self._pair()
        self.Credential.sudo().create(
            {
                "user_id": self.user.id,
                "mechanism": "webauthn",
                "credential_id": "passkey-2",
                "public_key": "cG9zc2libHktYS1rZXk",
                "device_label": "Laptop",
                "rp_id": "erp.example.com",
            }
        )
        status = self.Credential.check_enrolment_sufficient(self.user)
        self.assertEqual(status["enrolled"], 2)

    def test_the_verifying_device_is_the_one_stamped(self):
        """Evidence must name the device that signed, not any device owned."""
        if not CRYPTO:
            self.skipTest("cryptography unavailable")
        private, handle = self._pair()
        challenge = self.Credential.issue_device_challenge(
            self.user, "override.request,7"
        )
        verified = self.Credential.verify_device_signature(
            self.user,
            self._sign(
                private, challenge["challenge"], "override.request,7", handle, 1
            ),
            context_ref="override.request,7",
        )
        self.assertEqual(verified.mechanism, "bound_device")
        self.assertEqual(verified.credential_id, handle)

    def test_binding_does_not_need_the_webauthn_library(self):
        """The whole point: this path inherits none of the passkey stack's
        preconditions, so a deployment that cannot do WebAuthn can still
        authenticate a phone."""
        self.assertEqual(
            self.Credential._device_binding_ready(), CRYPTO
        )
