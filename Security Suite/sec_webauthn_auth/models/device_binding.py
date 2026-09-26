# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Pairing an app on a phone or tablet, and verifying what it signs.

Why this exists alongside WebAuthn
==================================
Passkeys are the better mechanism and remain the default. But a *native app*
cannot reach them without the operating system vendor agreeing that the app
speaks for the domain -- Digital Asset Links on Android, Associated Domains on
Apple platforms. That agreement is validated on the handset by software we do
not ship, cache we cannot flush, and it fails closed with messages like
``RP ID cannot be validated`` that name nothing actionable. Making the daily
sign-in depend on it means a build, a store listing and a vendor's cache sit in
the critical path of getting into the product at all.

So a paired app gets a keypair of its own, issued through this module, and the
platform is not consulted. The security properties that matter are kept:

* The private key is generated **on the device** and never transmitted. This
  server stores the public half and nothing else, exactly as with a passkey.
* The key is held in the platform keystore (Keychain, Android Keystore, DPAPI)
  and is released only after the user passes a biometric or device-credential
  check, so possession of an unlocked handset is required per signature.
* Every signature is bound to one server-issued challenge **and** one
  ``context_ref``, so a confirmation given for one action cannot authorise a
  different one. This is the same binding rule the assertion path enforces.
* A monotonic counter travels with each signature. A counter that repeats or
  goes backwards means two installations are using one key, which is the same
  clone signal WebAuthn's ``signCount`` carries.

What is genuinely weaker, stated plainly: a passkey's private key can be held
in a secure element that the application processor cannot read, whereas this
key is decrypted into process memory for the moment it signs. That is a real
difference on a rooted or jailbroken device. It is not a difference on a device
whose lock screen has been handed over, which is the threat this control is
actually for. Passkeys stay available and stay preferred; ``mechanism`` on the
credential records which one answered, so no approval's evidence ever implies a
stronger proof than the one that was given.

Ed25519 rather than ECDSA: it has no parameter choices to get wrong, no
nonce-reuse failure mode, and ``cryptography`` -- already a hard dependency of
Odoo itself -- implements it. This module therefore adds no new external
dependency; ``webauthn`` remains needed only for the passkey path.
"""

import base64
import hashlib
import logging
import os
import re
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, UserError, ValidationError

_logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard, exercised only on a broken install
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    ED25519_AVAILABLE = True
except ImportError:  # pragma: no cover
    ED25519_AVAILABLE = False
    InvalidSignature = Exception
    Ed25519PublicKey = None
    _logger.warning(
        "cryptography is unavailable, so paired-app signatures cannot be "
        "verified. Odoo lists it as a hard requirement, so this points at a "
        "broken environment rather than a missing optional feature."
    )

# Ten minutes is long enough to walk to the phone and type eight characters,
# short enough that a code read over someone's shoulder is usually dead.
PAIRING_TTL_MINUTES = 10

# Guessing is the attack this resists. Five tries against 2^40 possibilities in
# a ten-minute window is not a meaningful search.
PAIRING_MAX_ATTEMPTS = 5

# Crockford-style: no I, L, O, U. Removing the characters people transcribe
# wrongly buys more usability than the two bits of entropy it costs.
PAIRING_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PAIRING_LENGTH = 8

# Bumped only by a breaking change to what gets signed. The app sends the
# version it used, so a mismatch is a clear refusal rather than a signature
# that silently fails to verify.
SIGNATURE_DOMAIN = "perfecthr-device-v1"

ED25519_PUBLIC_KEY_BYTES = 32
ED25519_SIGNATURE_BYTES = 64


def b64url_decode(value):
    """Decode base64url, tolerating the padding the web platform omits."""
    if not isinstance(value, str):
        raise ValueError("expected a base64url string")
    cleaned = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-=]*", cleaned or ""):
        raise ValueError("not base64url")
    padding = "=" * (-len(cleaned.rstrip("=")) % 4)
    return base64.urlsafe_b64decode(cleaned.rstrip("=") + padding)


def _hash_code(code):
    """Codes are stored as digests, so a database read cannot pair a device."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _normalise_code(raw):
    """Accept what people actually type: spaces, dashes, lower case."""
    return re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()


class SecDevicePairing(models.Model):
    """A one-time code that lets one app instance bind itself to one account.

    The code is a bearer credential for the length of its life, so it is
    treated like one: hashed at rest, single use, short TTL, attempt-limited,
    and issued only from an authenticated session. Presenting it also requires
    the account's login, so a stolen code alone binds nothing.
    """

    _name = "sec.device.pairing"
    _description = "Device Pairing Code"
    _order = "created_at desc"

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        index=True,
        ondelete="cascade",
        help="The account this code will bind a device to.",
    )
    code_hash = fields.Char(
        string="Code Digest",
        required=True,
        index=True,
        readonly=True,
        help="SHA-256 of the pairing code. The code itself is shown once, at "
        "issue, and is not recoverable from this record.",
    )
    created_at = fields.Datetime(
        string="Issued At (UTC)",
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    expires_at = fields.Datetime(
        string="Expires At (UTC)", required=True, readonly=True, index=True,
    )
    consumed = fields.Boolean(string="Used", default=False, readonly=True)
    consumed_at = fields.Datetime(string="Used At", readonly=True)
    attempts = fields.Integer(
        string="Failed Attempts",
        default=0,
        readonly=True,
        help="Presentations that did not match. The code dies at "
        "%s." % PAIRING_MAX_ATTEMPTS,
    )
    credential_id = fields.Many2one(
        comodel_name="sec.webauthn.credential",
        string="Resulting Device",
        readonly=True,
        ondelete="set null",
        help="What this code produced, kept so the pairing is auditable.",
    )
    source_ip = fields.Char(string="Issued From", readonly=True)

    # ------------------------------------------------------------------
    # Issuing
    # ------------------------------------------------------------------
    @api.model
    def issue_for(self, user):
        """Mint a code for ``user`` and return it in the clear, once.

        Any code the user already holds is expired first. Two live codes for
        one account doubles the guessing surface for no benefit, and a user who
        clicked twice means the first one is not being used.
        """
        now = fields.Datetime.now()
        self.sudo().search(
            [
                ("user_id", "=", user.id),
                ("consumed", "=", False),
                ("expires_at", ">", now),
            ]
        ).write({"expires_at": now})

        code = "".join(
            secrets.choice(PAIRING_ALPHABET) for _i in range(PAIRING_LENGTH)
        )
        record = self.sudo().create(
            {
                "user_id": user.id,
                "code_hash": _hash_code(code),
                "created_at": now,
                "expires_at": now + timedelta(minutes=PAIRING_TTL_MINUTES),
                "source_ip": self.env["sec.anomaly.mixin"]._current_source_ip(),
            }
        )
        _logger.info(
            "Pairing code issued for %s, expires %s",
            user.login,
            record.expires_at,
        )
        return {
            "code": code,
            "formatted": "%s-%s" % (code[:4], code[4:]),
            "expires_at": fields.Datetime.to_string(record.expires_at),
            "minutes": PAIRING_TTL_MINUTES,
        }

    # ------------------------------------------------------------------
    # Redeeming
    # ------------------------------------------------------------------
    @api.model
    def redeem(self, login, code):
        """Resolve a login and code to the user, or refuse.

        Returns the ``res.users`` record on success. Every failure raises the
        *same* message: distinguishing "no such account" from "wrong code"
        would turn this endpoint into a way to enumerate logins.
        """
        refusal = _(
            "That pairing code is not valid for this account. Codes last "
            "%(minutes)s minutes and work once. Generate a fresh one from "
            "Perfect HR in your browser, under Security Suite > "
            "Authenticators > Pair a Device.",
            minutes=PAIRING_TTL_MINUTES,
        )
        normalised = _normalise_code(code)
        if not login or len(normalised) != PAIRING_LENGTH:
            raise AccessDenied(refusal)

        user = (
            self.env["res.users"]
            .sudo()
            .search([("login", "=", login.strip())], limit=1)
        )
        if not user:
            raise AccessDenied(refusal)

        now = fields.Datetime.now()
        candidates = self.sudo().search(
            [
                ("user_id", "=", user.id),
                ("consumed", "=", False),
                ("expires_at", ">", now),
                ("attempts", "<", PAIRING_MAX_ATTEMPTS),
            ]
        )
        digest = _hash_code(normalised)
        # compare_digest across every live candidate, so the time taken does
        # not reveal how many codes are outstanding or which one matched.
        matched = candidates.filtered(
            lambda p: secrets.compare_digest(p.code_hash, digest)
        )
        if not matched:
            # Charge the attempt to every live code, so a guesser cannot get
            # extra tries by racing two codes against one account.
            for pairing in candidates:
                pairing.sudo().write({"attempts": pairing.attempts + 1})
            _logger.warning("Failed pairing attempt for %s", user.login)
            raise AccessDenied(refusal)
        return matched[0]

    def mark_used(self, credential):
        self.ensure_one()
        self.sudo().write(
            {
                "consumed": True,
                "consumed_at": fields.Datetime.now(),
                "credential_id": credential.id,
            }
        )

    @api.model
    def gc_expired(self):
        """Spent codes are not evidence; the credential they made is."""
        cutoff = fields.Datetime.now() - timedelta(days=1)
        self.sudo().search([("created_at", "<", cutoff)]).unlink()


class WebauthnCredentialBoundDevice(models.Model):
    """Pairing and signature verification for apps holding an issued keypair."""

    _inherit = "sec.webauthn.credential"

    # ------------------------------------------------------------------
    # Capability
    # ------------------------------------------------------------------
    @api.model
    def _device_binding_ready(self):
        """Paired apps work without ``webauthn`` and without an RP ID.

        Deliberately independent of ``_verification_ready()``. The whole point
        of this path is that it does not inherit the passkey path's
        preconditions, so a deployment that cannot do WebAuthn at all can still
        authenticate a phone.
        """
        return ED25519_AVAILABLE

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------
    @api.model
    def pair_bound_device(
        self, login, code, public_key, device_label, platform=None
    ):
        """Bind a device that presented a valid code. Returns its handle."""
        if not self._device_binding_ready():
            raise UserError(
                _(
                    "This server cannot verify paired-app signatures, so "
                    "pairing is refused rather than producing a device that "
                    "could never sign in."
                )
            )
        pairing = self.env["sec.device.pairing"].redeem(login, code)
        user = pairing.user_id

        try:
            raw = b64url_decode(public_key)
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                _("The device sent a public key this server cannot read.")
            ) from exc
        if len(raw) != ED25519_PUBLIC_KEY_BYTES:
            raise ValidationError(
                _(
                    "Expected a %(want)s-byte Ed25519 public key, got "
                    "%(got)s bytes.",
                    want=ED25519_PUBLIC_KEY_BYTES,
                    got=len(raw),
                )
            )
        try:
            Ed25519PublicKey.from_public_bytes(raw)
        except Exception as exc:  # noqa: BLE001 - any rejection is a refusal
            raise ValidationError(
                _("That public key is not a usable Ed25519 key.")
            ) from exc

        normalised = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        existing = self.sudo().search(
            [("public_key", "=", normalised), ("mechanism", "=", "bound_device")],
            limit=1,
        )
        if existing:
            # Re-pairing the same installation would leave two rows claiming
            # one key, and "two devices" would be satisfiable by one phone.
            raise ValidationError(
                _(
                    "This app is already paired to %(login)s. Remove it under "
                    "Security Suite > Authenticators before pairing it again.",
                    login=existing.user_id.login,
                )
            )

        credential = (
            self.sudo()
            .create(
                {
                    "user_id": user.id,
                    "mechanism": "bound_device",
                    "credential_id": b64url_device_handle(),
                    "public_key": normalised,
                    "device_label": (device_label or "").strip()
                    or _("Paired device"),
                    "authenticator_type": "platform",
                    "transports": "internal",
                    "aaguid": (platform or "")[:64],
                    "rp_id": self.env["sec.webauthn.config"].rp_id() or "-",
                    "sign_counter": 0,
                }
            )
        )
        pairing.mark_used(credential)
        _logger.info(
            "Paired device %s for %s (%s)",
            credential.device_label,
            user.login,
            platform or "unknown platform",
        )
        return {
            "device_handle": credential.credential_id,
            "device_label": credential.device_label,
            "user_login": user.login,
            "user_name": user.name,
        }

    # ------------------------------------------------------------------
    # Challenge / response
    # ------------------------------------------------------------------
    @api.model
    def issue_device_challenge(self, user, context_ref, purpose="authentication"):
        """A challenge the paired app is to sign. Returns None if none paired."""
        devices = self.bound_devices_for(user)
        if not devices:
            return None
        challenge = self.env["sec.webauthn.challenge"].issue(
            user, purpose, context_ref=context_ref
        )
        return {
            "version": SIGNATURE_DOMAIN,
            "challenge": challenge.challenge,
            "context_ref": context_ref or "",
            "devices": [
                {"handle": d.credential_id, "label": d.device_label}
                for d in devices
            ],
        }

    @api.model
    def bound_devices_for(self, user):
        return self.enrolled_for(user).filtered(
            lambda c: c.mechanism == "bound_device"
        )

    @api.model
    def _signed_payload(self, challenge, context_ref, handle, counter):
        """The exact bytes both sides sign.

        Newline-joined because every field is base64url, a model,id reference
        or a decimal integer -- none can contain a newline, so the encoding is
        unambiguous without length prefixes. The leading domain tag stops a
        signature made for this protocol being replayed into another one that
        happens to sign similar-looking data.
        """
        parts = [
            SIGNATURE_DOMAIN,
            challenge or "",
            context_ref or "",
            handle or "",
            str(int(counter)),
        ]
        return "\n".join(parts).encode("utf-8")

    @api.model
    def verify_device_signature(self, user, payload, context_ref=None):
        """Verify one signature from a paired app.

        Returns the credential on success. Raises on every failure, because a
        caller that treated a falsy return as "not confirmed" and carried on
        would be the whole control quietly disabled.
        """
        if not self._device_binding_ready():
            raise UserError(
                _("This server cannot verify paired-app signatures.")
            )
        payload = payload or {}
        handle = (payload.get("device_handle") or "").strip()
        signature_b64 = payload.get("signature") or ""
        challenge_value = (payload.get("challenge") or "").strip()
        counter = payload.get("counter")

        generic = _(
            "That confirmation could not be verified. Open Perfect HR on your "
            "paired device and try again."
        )

        device = self.sudo().search(
            [
                ("credential_id", "=", handle),
                ("user_id", "=", user.id),
                ("mechanism", "=", "bound_device"),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not device:
            _logger.warning(
                "Signature presented for unknown device handle, user %s",
                user.login,
            )
            raise AccessDenied(generic)

        challenge = (
            self.env["sec.webauthn.challenge"]
            .sudo()
            .search(
                [
                    ("challenge", "=", challenge_value),
                    ("user_id", "=", user.id),
                    ("consumed", "=", False),
                ],
                limit=1,
            )
        )
        if not challenge:
            raise AccessDenied(generic)
        # Bind before verifying. A signature over the wrong context must not be
        # able to consume a challenge issued for the right one.
        if context_ref and challenge.context_ref != context_ref:
            raise AccessDenied(generic)

        try:
            counter = int(counter)
        except (TypeError, ValueError) as exc:
            raise AccessDenied(generic) from exc
        if counter <= device.sign_counter:
            # Same signal as a WebAuthn signCount regression: two installations
            # hold one key. Refuse and raise it, rather than let the older of
            # the two keep working.
            device._raise_clone_anomaly(counter)
            raise AccessDenied(
                _(
                    "This device's counter went backwards, which means its key "
                    "exists in more than one place. It has been refused and a "
                    "security alert raised. Pair the device again."
                )
            )

        try:
            signature = b64url_decode(signature_b64)
            public_key = Ed25519PublicKey.from_public_bytes(
                b64url_decode(device.public_key)
            )
        except (ValueError, TypeError) as exc:
            raise AccessDenied(generic) from exc
        if len(signature) != ED25519_SIGNATURE_BYTES:
            raise AccessDenied(generic)

        message = self._signed_payload(
            challenge_value, challenge.context_ref, handle, counter
        )
        try:
            public_key.verify(signature, message)
        except InvalidSignature as exc:
            _logger.warning(
                "Bad paired-device signature for %s on %s",
                user.login,
                challenge.context_ref or "(no context)",
            )
            raise AccessDenied(generic) from exc

        if not challenge.consume():
            raise AccessDenied(generic)
        # The literal the base write() guard looks for; see webauthn_credential.
        device.sudo().with_context(webauthn_counter_update=True).write(
            {"sign_counter": counter, "last_used_at": fields.Datetime.now()}
        )
        _logger.info(
            "Paired device %s confirmed %s for %s",
            device.device_label,
            challenge.context_ref or "sign-in",
            user.login,
        )
        return device._stamp_verified()

    def _raise_clone_anomaly(self, presented):
        """Record a counter regression as the clone signal it is.

        On a **separate cursor**, because the caller raises immediately after
        this and that rolls the transaction back. An alert written on the same
        cursor would roll back with it, and every clone signal would vanish
        precisely when it mattered -- the same trap ``freeze_mixin`` documents.

        The device is refused but deliberately **not** revoked. The WebAuthn
        path does revoke on a clone, and can afford to: those credentials are
        used for approvals. This one is used to sign in, so auto-revoking on a
        counter regression would lock somebody out of the product entirely, and
        the most likely benign cause -- a restored device backup -- would do it
        to a user who has done nothing wrong. Refuse, alert at critical, and
        let an administrator decide.
        """
        self.ensure_one()
        try:
            with self.pool.cursor() as new_cr:
                env = self.env(cr=new_cr)
                env["sec.anomaly.mixin"]._raise_anomaly(
                    # credential_anomaly is the suite's category for this; there
                    # is no separate "cloned" type and inventing one would break
                    # the forensic report's selection.
                    alert_type="credential_anomaly",
                    name=_("Paired device counter went backwards"),
                    reason=_(
                        "Device '%(label)s' belonging to %(login)s presented "
                        "counter %(got)s, having already reached %(have)s. The "
                        "key is in use from more than one installation.",
                        label=self.device_label,
                        login=self.user_id.login,
                        got=presented,
                        have=self.sign_counter,
                    ),
                    severity="critical",
                    user=self.user_id,
                    source_ref="%s,%s" % (self._name, self.id),
                )
        except Exception:  # noqa: BLE001 - never let alerting swallow the refusal
            _logger.exception(
                "Could not record clone anomaly for credential %s", self.id
            )


def b64url_device_handle():
    """A 32-byte opaque handle, in the same shape as a credential ID."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
