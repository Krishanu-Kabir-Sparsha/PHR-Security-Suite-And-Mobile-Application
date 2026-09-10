# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Cloned-authenticator detection via sign-counter regression (P2-3, US-6.2).

The acceptance criterion: "Sign counter is checked on every assertion to detect
cloned authenticators; a regression triggers an automatic security alert and
blocks the approval."

Three things make this less simple than it sounds, and each is handled below.

**1. A regression must not be a denial-of-service vector.**
py_webauthn checks the sign counter *before* it verifies the signature. So an
attacker who knows a victim's credential ID can post a garbage assertion
carrying a low counter and trigger the regression path without ever possessing
the key. If that path revoked the credential, anyone could remotely disable the
CEO/Owner's authenticator — and the highest-authority approval in the system
would be unavailable exactly when someone wanted it unavailable.

So a suspected regression is re-verified with the counter check neutralised, to
force the library through signature verification. Only a regression carrying a
*valid signature* means the real key produced it, which is what a clone implies.
An invalid signature is a forgery attempt: refused and alerted, credential
untouched.

**2. Many authenticators do not implement counters at all.**
Synced passkeys and most platform authenticators report a constant zero. Zero
against zero is not a regression, it is an absence of evidence. Treating it as a
clone would revoke almost every phone credential on first reuse. Such
credentials are marked as offering no clone detection, which is a real
reduction in assurance and is reported rather than hidden.

**3. Revoke, or refuse just this assertion?**
Revoke. A genuine counter regression means two copies of the private key exist.
Every future assertion from that credential is equally suspect, so refusing only
the current one leaves the attacker free to retry. The owner is notified and
must re-enrol, which under US-6.3 requires independent multi-party approval.
"""

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

try:
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.exceptions import InvalidAuthenticationResponse

    WEBAUTHN_LIB_AVAILABLE = True
except ImportError:  # pragma: no cover
    WEBAUTHN_LIB_AVAILABLE = False


class WebauthnCloneDetection(models.Model):
    _inherit = "sec.webauthn.credential"

    counter_supported = fields.Boolean(
        string="Counter Supported",
        default=True,
        readonly=True,
        help="False when the authenticator reports a constant zero signature "
        "counter, which is normal for synced passkeys. Clone detection is "
        "not possible for such credentials.",
    )
    clone_suspected = fields.Boolean(
        string="Clone Suspected",
        default=False,
        readonly=True,
        help="Set when a signature counter regression was observed with a "
        "valid signature. The credential is revoked at the same time.",
    )
    clone_detected_at = fields.Datetime(
        string="Clone Detected At", readonly=True
    )
    last_counter_seen = fields.Integer(
        string="Last Counter Seen", readonly=True
    )

    # ------------------------------------------------------------------
    # Classification of a failed assertion
    # ------------------------------------------------------------------
    def _is_counter_regression_error(self, error):
        """Whether a library failure was the counter check specifically.

        Matched on the exception text because py_webauthn raises one exception
        class for every failure mode. Deliberately conservative: a false
        negative here degrades to a generic verification failure, which is
        still a refusal. A false positive would send a bad signature down the
        clone path, which the signature re-check below then rejects anyway.
        """
        return "sign count" in str(error).lower()

    def _signature_valid_ignoring_counter(self, credential_payload, challenge_b64):
        """Re-verify with the counter check neutralised.

        Passing 0 as the current count disables only the counter comparison;
        origin, RP ID, challenge, user verification and the cryptographic
        signature are all still checked. A True here means the genuine private
        key signed this assertion.
        """
        self.ensure_one()
        config = self.env["sec.webauthn.config"]
        try:
            verify_authentication_response(
                credential=credential_payload,
                expected_challenge=base64url_to_bytes(challenge_b64),
                expected_rp_id=config.rp_id(),
                expected_origin=self._expected_origins(),
                credential_public_key=base64url_to_bytes(self.public_key),
                credential_current_sign_count=0,
                require_user_verification=True,
            )
            return True
        except InvalidAuthenticationResponse as exc:
            _logger.info(
                "Counter regression on credential %s carried an invalid "
                "signature (%s); treating as forgery, not a clone.",
                self.id,
                exc,
            )
            return False

    def _handle_counter_regression(self, credential_payload, challenge_b64):
        """Decide whether a regression is a clone or a forgery, and respond.

        Returns a short verdict string for the caller's error message.
        """
        self.ensure_one()
        if not self._signature_valid_ignoring_counter(
            credential_payload, challenge_b64
        ):
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="credential_anomaly",
                name=_("Forged assertion attempt"),
                reason=_(
                    "An assertion for credential '%(label)s' (owner %(owner)s) "
                    "carried a regressed signature counter AND an invalid "
                    "signature. This is consistent with someone forging a "
                    "response using a known credential ID, not with a cloned "
                    "key. The credential has NOT been revoked, so that this "
                    "cannot be used to disable an approver's authenticator.",
                    label=self.device_label,
                    owner=self.user_id.login,
                ),
                severity="critical",
                record=self,
                user=self.user_id,
            )
            return "forgery"

        # Valid signature plus a counter that went backwards: two copies of the
        # private key exist.
        self.sudo().with_context(webauthn_counter_update=True).write(
            {
                "clone_suspected": True,
                "clone_detected_at": fields.Datetime.now(),
                "active": False,
                "revoked_reason": _(
                    "Automatically revoked: signature counter regression "
                    "indicates the authenticator may have been cloned."
                ),
            }
        )
        self.env["sec.anomaly.mixin"]._raise_anomaly(
            alert_type="credential_anomaly",
            name=_("CLONED AUTHENTICATOR SUSPECTED"),
            reason=_(
                "Credential '%(label)s' belonging to %(owner)s presented a "
                "validly-signed assertion whose signature counter had gone "
                "backwards. That means two copies of the private key exist. "
                "The credential has been revoked automatically and the "
                "approval was blocked. The owner must re-enrol, which requires "
                "independent multi-party approval. Treat as a security "
                "incident: establish how the key was duplicated before "
                "re-enrolling.",
                label=self.device_label,
                owner=self.user_id.login,
            ),
            severity="critical",
            record=self,
            user=self.user_id,
        )
        _logger.critical(
            "CLONE SUSPECTED: credential %s (%s) revoked after counter "
            "regression with a valid signature",
            self.id,
            self.user_id.login,
        )
        self._notify_owner_of_clone()
        return "clone"

    def _notify_owner_of_clone(self):
        """Tell the credential's owner directly.

        The owner is the one person who can say "that was not me", and they may
        not be watching the surveillance dashboard.
        """
        self.ensure_one()
        try:
            self.user_id.sudo().partner_id.message_post(
                body=_(
                    "<p>Your security key <strong>%(label)s</strong> has been "
                    "revoked automatically.</p><p>An approval attempt used it "
                    "in a way that suggests the key may have been copied. If "
                    "this was not you, report it now. You will need to enrol a "
                    "new device, which requires approval from the other "
                    "approval tiers.</p>",
                    label=self.device_label,
                ),
                subject=_("Security key revoked"),
            )
        except Exception:  # noqa: BLE001 - notification must not break the refusal
            _logger.exception("Could not notify %s of clone", self.user_id.login)

    # ------------------------------------------------------------------
    # Counter bookkeeping
    # ------------------------------------------------------------------
    def _record_successful_assertion(self, new_sign_count):
        """Extend P2-2's bookkeeping with counter-support classification."""
        self.ensure_one()
        vals = {
            "sign_counter": max(new_sign_count, self.sign_counter),
            "last_used_at": fields.Datetime.now(),
            "last_counter_seen": new_sign_count,
        }
        if new_sign_count == 0 and self.sign_counter == 0:
            # Constant zero: this authenticator does not implement a counter.
            if self.counter_supported:
                vals["counter_supported"] = False
                _logger.info(
                    "Credential %s reports no signature counter; clone "
                    "detection is unavailable for it.",
                    self.id,
                )
        self.sudo().with_context(webauthn_counter_update=True).write(vals)

    @api.model
    def clone_detection_report(self):
        """Which credentials offer no clone detection, and which are suspect.

        Consumed by the monthly forensic report (P3-4). The first list is not a
        fault to be fixed so much as a fact the CEO/Owner should know: for those
        credentials, a copied key would not announce itself.
        """
        active = self.sudo().search([("active", "=", True)])
        no_detection = active.filtered(lambda c: not c.counter_supported)
        suspected = self.sudo().with_context(active_test=False).search(
            [("clone_suspected", "=", True)]
        )
        return {
            "credentials_without_clone_detection": [
                {"user": c.user_id.login, "device": c.device_label}
                for c in no_detection
            ],
            "clones_suspected": [
                {
                    "user": c.user_id.login,
                    "device": c.device_label,
                    "detected_at": c.clone_detected_at,
                }
                for c in suspected
            ],
            "clean": not suspected,
        }
