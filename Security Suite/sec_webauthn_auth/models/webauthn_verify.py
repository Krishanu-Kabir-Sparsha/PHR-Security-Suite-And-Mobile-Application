# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Cryptographic verification of the WebAuthn ceremonies (P2-2, US-6.1/US-6.2).

Verification is delegated to ``py_webauthn`` 2.2.0 rather than hand-rolled.
Parsing CBOR attestation objects, validating COSE keys and checking attestation
statements are exactly the kind of code where a subtle error produces something
that looks like it works and accepts forged credentials. This is the one place
in the suite where "prefer a maintained library" is not a style preference.

What this module is responsible for, and what it delegates:

- **Delegated to the library:** clientDataJSON parsing, type/challenge/origin
  checks, rpIdHash comparison, attestation statement verification, COSE public
  key extraction, signature verification.
- **Ours:** binding an assertion to *one specific action* rather than treating
  it as a bearer token, single-use challenge consumption, sign-counter
  regression handling (P2-3 extends this), and refusing to report success for
  any reason other than a verified ceremony.

The assertion binding deserves a note. A verified assertion proves someone
holding the authenticator was present just now. It does **not** by itself prove
what they intended to authorise. If an assertion could be verified once and then
consumed by any privileged action in the same session, a user tricked into
approving something small would have authorised something large. So each
challenge carries a ``context_ref`` naming the exact record and action it
authorises, and verification will only satisfy a caller asking about that same
context.
"""

import base64
import binascii
import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    from webauthn import verify_authentication_response, verify_registration_response
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    from webauthn.helpers.exceptions import (
        InvalidAuthenticationResponse,
        InvalidRegistrationResponse,
    )

    WEBAUTHN_LIB_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on deployment environment
    WEBAUTHN_LIB_AVAILABLE = False
    _logger.warning(
        "py_webauthn is not installed. WebAuthn verification is unavailable; "
        "install it with: pip install webauthn==2.2.0"
    )


class WebauthnCredentialVerification(models.Model):
    """Adds ceremony verification to the credential model."""

    _inherit = "sec.webauthn.credential"

    backed_up = fields.Boolean(
        string="Backed Up",
        readonly=True,
        help="The authenticator reports this credential is synced to a cloud "
        "keychain. Convenient for the user; it also means possession of the "
        "key is no longer strictly bound to one physical device. Worth "
        "knowing for the CEO/Owner tier.",
    )
    device_type = fields.Char(
        string="Credential Device Type",
        readonly=True,
        help="single_device or multi_device, as reported by the authenticator.",
    )
    user_verified_at_enrolment = fields.Boolean(
        string="User Verified at Enrolment",
        readonly=True,
        help="Whether the device checked a biometric or PIN during enrolment.",
    )

    # ------------------------------------------------------------------
    # Capability reporting
    # ------------------------------------------------------------------
    @api.model
    def _verification_ready(self):
        """True once the library is importable. See P2-1 for why this exists."""
        return WEBAUTHN_LIB_AVAILABLE

    @api.model
    def _require_library(self):
        if not WEBAUTHN_LIB_AVAILABLE:
            raise UserError(
                _(
                    "The py_webauthn library is not installed on this server, "
                    "so WebAuthn ceremonies cannot be verified.\n\n"
                    "Install it with: pip install webauthn==2.2.0"
                )
            )

    # ------------------------------------------------------------------
    # Shared challenge handling
    # ------------------------------------------------------------------
    @api.model
    def _take_challenge(self, user, client_data_b64, purpose, context_ref=None):
        """Find, validate and consume the challenge this response answers.

        Looked up by the challenge value carried in clientDataJSON rather than
        by "the user's most recent challenge": with concurrent tabs the most
        recent one is not necessarily the one being answered, and picking the
        wrong record would either fail valid ceremonies or, worse, consume a
        challenge that was still outstanding elsewhere.
        """
        try:
            client_data = json.loads(base64url_to_bytes(client_data_b64))
        except Exception as exc:  # noqa: BLE001 - malformed input is a refusal
            raise UserError(_("Malformed client data in the response.")) from exc

        presented = client_data.get("challenge")
        if not presented:
            raise UserError(_("The response carried no challenge."))

        challenge = (
            self.env["sec.webauthn.challenge"]
            .sudo()
            .search(
                [
                    ("challenge", "=", presented),
                    ("user_id", "=", user.id),
                    ("purpose", "=", purpose),
                ],
                limit=1,
            )
        )
        if not challenge:
            # Either forged, or issued for a different user or purpose. A
            # registration challenge must never satisfy an authentication.
            self._raise_credential_anomaly(
                user,
                _("WebAuthn challenge not recognised"),
                _(
                    "A %(purpose)s response was presented by %(user)s carrying "
                    "a challenge that was never issued to them for that "
                    "purpose.",
                    purpose=purpose,
                    user=user.login,
                ),
            )
            raise UserError(_("That challenge was not issued to you."))

        if context_ref and challenge.context_ref != context_ref:
            raise UserError(
                _(
                    "That confirmation authorises a different action. Each "
                    "approval requires its own confirmation."
                )
            )

        if not challenge.consume():
            self._raise_credential_anomaly(
                user,
                _("WebAuthn challenge replayed or expired"),
                _(
                    "%(user)s presented a challenge that was already used or "
                    "past its five-minute validity.",
                    user=user.login,
                ),
            )
            raise UserError(
                _(
                    "That confirmation has expired or was already used. Please "
                    "try again."
                )
            )
        return challenge

    @api.model
    def _raise_credential_anomaly(self, user, name, reason, severity="high"):
        self.env["sec.anomaly.mixin"]._raise_anomaly(
            alert_type="credential_anomaly",
            name=name,
            reason=reason,
            severity=severity,
            user=user,
        )

    @api.model
    def _expected_origins(self):
        """Every origin a legitimate ceremony can come from.

        A browser sends ``https://<rp_id>``. A native Android app sends
        ``android:apk-key-hash:<base64url of its signing certificate's SHA-256>``
        -- a completely different string, and one the web origin does not cover.
        Without the app origin here, every assertion from the mobile app is
        rejected as coming from the wrong place, which is indistinguishable from
        a genuine attack and gives no clue what is actually wrong.

        The app origin is derived from the same fingerprint that
        ``/.well-known/assetlinks.json`` publishes, so the two cannot drift: if
        Android is willing to use a passkey for this app, this accepts it, and
        if the fingerprint is wrong both fail together.
        """
        config = self.env["sec.webauthn.config"]
        origin = config.expected_origin()
        origins = [origin.rstrip("/")] if origin else ["https://%s" % config.rp_id()]
        return origins + self._android_origins()

    def _android_origins(self):
        """Origins for the native app, from the configured signing fingerprints.

        Empty when no fingerprint is set, which is the correct answer for a
        deployment with no mobile app: an empty list adds nothing and rejects
        nothing that worked before.
        """
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("sec_webauthn.android_sha256")
            or ""
        )
        origins = []
        # Commas or newlines, because a parameter holding two fingerprints gets
        # pasted both ways and neither spelling should be the one that fails.
        for part in re.split(r"[,\n\r]", raw):
            digest = part.strip().replace(":", "").replace(" ", "")
            if not digest:
                continue
            try:
                packed = binascii.unhexlify(digest)
            except (binascii.Error, ValueError):
                _logger.warning(
                    "sec_webauthn.android_sha256 contains a value that is not a "
                    "hex fingerprint and was ignored: %r",
                    part.strip()[:16],
                )
                continue
            if len(packed) != 32:
                # A SHA-1 fingerprint is 20 bytes and is what Play Console shows
                # first; pasting it here would silently accept nothing.
                _logger.warning(
                    "sec_webauthn.android_sha256 expects a SHA-256 fingerprint "
                    "(32 bytes); got %s bytes and ignored it",
                    len(packed),
                )
                continue
            origins.append(
                "android:apk-key-hash:%s"
                % base64.urlsafe_b64encode(packed).decode().rstrip("=")
            )
        return origins

    # ------------------------------------------------------------------
    # Registration ceremony
    # ------------------------------------------------------------------
    @api.model
    def verify_and_store_registration(self, credential_payload, device_label):
        """Verify an attestation and, only then, store the credential."""
        self._require_library()
        env_user = self.env.user
        config = self.env["sec.webauthn.config"]
        config.check_ready()

        # Which of the three enrolment routes applies (P2-4), decided before
        # any cryptography, so a refusal is cheap and the reason is specific.
        grant = self._check_enrolment_permitted(env_user)

        response = (credential_payload or {}).get("response") or {}
        challenge = self._take_challenge(
            env_user, response.get("clientDataJSON"), "registration"
        )

        try:
            verified = verify_registration_response(
                credential=credential_payload,
                expected_challenge=base64url_to_bytes(challenge.challenge),
                expected_rp_id=config.rp_id(),
                expected_origin=self._expected_origins(),
                # User presence is deliberately NOT passed as a keyword here.
                # py_webauthn only grew require_user_presence in 2.5.0, and
                # 2.5.0 requires cryptography>=43.0.3 while Odoo 18 pins
                # cryptography==42.0.8 (and pyopenssl==24.1.0, which caps
                # cryptography<43). We hold Odoo's pins and run py_webauthn
                # 2.2.0, where the presence check is unconditional:
                # verify_registration_response raises on `not auth_data.flags.up`
                # with no way to switch it off. The guarantee is therefore
                # identical, not weakened. On 2.5.0+ the parameter also defaults
                # to True, so an upgrade does not silently relax it either.
                #
                # The device must also check a biometric or PIN. Presence alone
                # proves someone touched the key, not that it was its owner,
                # which is not enough for an approval credential.
                require_user_verification=True,
            )
        except InvalidRegistrationResponse as exc:
            self._raise_credential_anomaly(
                env_user,
                _("WebAuthn enrolment rejected"),
                _(
                    "Attestation verification failed for %(user)s: %(error)s",
                    user=env_user.login,
                    error=exc,
                ),
            )
            raise UserError(
                _("Your device's response could not be verified: %s", exc)
            ) from exc

        credential_id = bytes_to_base64url(verified.credential_id)
        existing = self.sudo().with_context(active_test=False).search(
            [("credential_id", "=", credential_id)], limit=1
        )
        if existing:
            raise UserError(
                _(
                    "That authenticator is already enrolled%(owner)s.",
                    owner=_(" to another user")
                    if existing.user_id != env_user
                    else "",
                )
            )

        transports = self._transports_from(credential_payload)
        credential = self.sudo().create(
            {
                "user_id": env_user.id,
                "credential_id": credential_id,
                "public_key": bytes_to_base64url(verified.credential_public_key),
                "sign_counter": verified.sign_count,
                "device_label": (device_label or "").strip()
                or _("Authenticator enrolled %s", fields.Date.context_today(self)),
                "aaguid": verified.aaguid,
                "transports": ",".join(transports) if transports else False,
                "rp_id": config.rp_id(),
                "authenticator_type": "platform"
                if "internal" in transports
                else ("cross-platform" if transports else "unknown"),
                "device_type": str(getattr(verified.credential_device_type, "value",
                                           verified.credential_device_type)),
                "backed_up": verified.credential_backed_up,
                "user_verified_at_enrolment": verified.user_verified,
            }
        )
        if grant:
            grant.consume(credential)
        self._raise_credential_anomaly(
            env_user,
            _("WebAuthn authenticator enrolled"),
            _(
                "%(user)s enrolled authenticator '%(label)s'. Enrolment is a "
                "privileged event: a credential added without the user's "
                "knowledge would authorise approvals in their name.",
                user=env_user.login,
                label=credential.device_label,
            ),
            severity="medium",
        )
        _logger.info(
            "WebAuthn credential enrolled for %s (aaguid=%s, backed_up=%s)",
            env_user.login,
            verified.aaguid,
            verified.credential_backed_up,
        )
        return credential

    @api.model
    def _check_enrolment_permitted(self, user):
        """Decide which enrolment route applies, or refuse (P2-4, US-6.3).

        Returns an active recovery grant when one was needed and found, or an
        empty recordset when enrolment is permitted without one.
        """
        Recovery = self.env["sec.webauthn.recovery.request"]
        history = self.sudo().with_context(active_test=False).search(
            [("user_id", "=", user.id)]
        )
        active = history.filtered(lambda c: c.active)

        if not history:
            # Route 1: first enrolment. Nothing exists to steal yet.
            return Recovery.browse()

        if active:
            # Route 2: adding a device while one still works. Proving control
            # of the current key is stronger than convening approvers, and
            # FR-6.5 needs this path to be usable so the CEO/Owner can hold two.
            if not self._verification_ready():
                return Recovery.browse()
            if not self._verify_pending_assertion("sec.webauthn.credential,add"):
                raise UserError(
                    _(
                        "Confirm with an authenticator you already have before "
                        "adding another. If none of your devices still work, "
                        "request a break-glass recovery instead."
                    )
                )
            return Recovery.browse()

        # Route 3: credentials existed, none usable. Break-glass.
        grant = Recovery.active_grant_for(user)
        if not grant:
            raise UserError(
                _(
                    "You previously had an authenticator and none is currently "
                    "usable, so enrolling a replacement is not self-service.\n\n"
                    "Raise a break-glass recovery request. Two other approvers "
                    "must confirm it on their own devices before you can enrol.\n\n"
                    "This is deliberate: anyone able to silently add an "
                    "authenticator to your account could approve in your name."
                )
            )
        return grant

    # ------------------------------------------------------------------
    # Authentication ceremony
    # ------------------------------------------------------------------
    @api.model
    def verify_authentication(self, credential_payload, context_ref=None):
        """Verify an assertion bound to one specific action.

        Returns the credential on success. Raises on every failure path; there
        is no code path that returns a falsy value and lets the caller decide,
        because that shape is how "not implemented" got confused with "denied"
        once already (see P1-6 fix in session 7).
        """
        self._require_library()
        env_user = self.env.user
        config = self.env["sec.webauthn.config"]
        config.check_ready()

        response = (credential_payload or {}).get("response") or {}
        challenge = self._take_challenge(
            env_user,
            response.get("clientDataJSON"),
            "authentication",
            context_ref=context_ref,
        )

        raw_id = (credential_payload or {}).get("rawId") or (
            credential_payload or {}
        ).get("id")
        credential = self.sudo().search(
            [
                ("credential_id", "=", raw_id),
                ("user_id", "=", env_user.id),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not credential:
            self._raise_credential_anomaly(
                env_user,
                _("Assertion from unknown or revoked authenticator"),
                _(
                    "%(user)s presented an assertion from a credential that is "
                    "not enrolled to them or has been revoked.",
                    user=env_user.login,
                ),
                severity="critical",
            )
            raise UserError(
                _("That authenticator is not enrolled to your account.")
            )

        try:
            verified = verify_authentication_response(
                credential=credential_payload,
                expected_challenge=base64url_to_bytes(challenge.challenge),
                expected_rp_id=config.rp_id(),
                expected_origin=self._expected_origins(),
                credential_public_key=base64url_to_bytes(credential.public_key),
                credential_current_sign_count=credential.sign_counter,
                require_user_verification=True,
            )
        except InvalidAuthenticationResponse as exc:
            # A counter regression is not just "verification failed": it may
            # mean the key has been cloned. P2-3 classifies it, because the
            # response differs sharply — a clone revokes the credential, a
            # forgery must not.
            if credential._is_counter_regression_error(exc):
                verdict = credential._handle_counter_regression(
                    credential_payload, challenge.challenge
                )
                if verdict == "clone":
                    raise UserError(
                        _(
                            "This approval has been blocked and your security "
                            "key has been revoked.\n\nThe key was used in a "
                            "way that indicates it may have been copied. If "
                            "this was not you, report it now. Enrolling a "
                            "replacement requires approval from the other "
                            "approval tiers."
                        )
                    ) from exc
                raise UserError(
                    _(
                        "Your device's confirmation could not be verified. The "
                        "attempt has been recorded."
                    )
                ) from exc
            self._raise_credential_anomaly(
                env_user,
                _("WebAuthn approval rejected"),
                _(
                    "Assertion verification failed for %(user)s on credential "
                    "'%(label)s': %(error)s",
                    user=env_user.login,
                    label=credential.device_label,
                    error=exc,
                ),
                severity="critical",
            )
            raise UserError(
                _("Your device's confirmation could not be verified: %s", exc)
            ) from exc

        credential._record_successful_assertion(verified.new_sign_count)
        return credential._stamp_verified()

    # _record_successful_assertion is implemented in
    # webauthn_clone_detection.py (P2-3), which also classifies counter
    # regressions rather than treating them as generic failures.

    # ------------------------------------------------------------------
    # Interface used by other modules
    # ------------------------------------------------------------------
    @api.model
    def issue_authentication_challenge(self, context_ref=None):
        """Issue a challenge for one specific action."""
        self._require_library()
        self.env["sec.webauthn.config"].check_ready()
        user = self.env.user
        # Passkeys only. A paired app's key lives in that app and is reachable
        # by no browser and no credential manager, so listing it here would put
        # an entry in allowCredentials that the platform can never satisfy —
        # the user is offered a device, picks it, and the ceremony dies.
        credentials = self.enrolled_for(user).filtered(
            lambda c: c.mechanism == "webauthn"
        )
        if not credentials:
            raise UserError(
                _(
                    "You have no enrolled authenticator, so this action cannot "
                    "be confirmed. Enrol a device first."
                )
            )
        challenge = self.env["sec.webauthn.challenge"].issue(
            user, "authentication", context_ref=context_ref
        )
        return {
            "challenge": challenge.challenge,
            "rpId": self.env["sec.webauthn.config"].rp_id(),
            "timeout": 300000,
            "userVerification": "required",
            "allowCredentials": [
                self._credential_descriptor(c) for c in credentials
            ],
        }

    @api.model
    def _transports_from(self, credential_payload):
        """Transports out of a registration response, whichever shape it is.

        There are two, and both are legitimate. The WebAuthn JSON
        serialization -- what Android's Credential Manager returns -- puts them
        at ``response.transports``. The browser page here builds its payload by
        hand from ``getTransports()`` and puts them at the top level.

        Reading only one shape is not a parse error; it is worse. The credential
        stores no transports, so the next authentication cannot tell the
        platform where the key lives, and the user is asked to plug in a USB
        key for a fingerprint reader they are already touching.
        """
        payload = credential_payload or {}
        response = payload.get("response") or {}
        transports = response.get("transports") or payload.get("transports") or []
        return [str(t) for t in transports if t]

    @api.model
    def _credential_descriptor(self, credential):
        """One allowCredentials entry, including how to reach the device.

        The transports matter far more than they look. Without them the
        platform has no idea *where* the credential lives, so Windows offers
        "insert your security key into the USB port" for a credential that is
        actually Windows Hello on the same machine, and Android offers a QR
        code for one sitting in its own keystore. The user is then asked for
        hardware they do not have, to prove something the device in their hand
        could prove instantly.

        They are recorded at enrolment and simply were not being sent.

        Omitted rather than guessed when unknown: an empty list means "try
        everything", which is the old behaviour, while a wrong one actively
        hides the authenticator that would have worked.
        """
        descriptor = {"type": "public-key", "id": credential.credential_id}
        transports = [
            t.strip()
            for t in (credential.transports or "").split(",")
            if t.strip()
        ]
        if transports:
            descriptor["transports"] = transports
        return descriptor

    @api.model
    def _verify_pending_assertion(self, context_ref=None):
        """Whether an assertion for ``context_ref`` was verified this request.

        Callers gate privileged actions on this. It reads a marker placed on the
        request by the controller after a successful ceremony, rather than
        re-running verification, so that one assertion authorises exactly one
        action.
        """
        if not WEBAUTHN_LIB_AVAILABLE:
            return False
        try:
            from odoo.http import request

            if not request:
                return False
            verified_for = getattr(request, "sec_webauthn_verified_for", None)
        except Exception:  # noqa: BLE001 - no HTTP context, e.g. cron or shell
            return False
        if not verified_for:
            return False
        if context_ref and verified_for != context_ref:
            return False
        return True
