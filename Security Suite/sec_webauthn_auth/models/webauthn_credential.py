# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""WebAuthn credential storage and enrolment (US-6.1, BRD FR-6.1).

Scope of this task (P2-1): the credential model, the Relying Party
configuration and its preconditions, challenge issuance, and the enrolment UI.
**Cryptographic verification of the registration and authentication ceremonies
is P2-2** and is deliberately not implemented here; ``_verification_ready()``
returns False until it is, and no credential can be stored without it.

Two preconditions are enforced rather than assumed, because both are
irreversible-ish mistakes that are cheap to prevent and expensive to discover:

**A fixed Relying Party ID.** Credentials bind to one origin. Change the domain
later and every enrolled authenticator is dead — including, at the worst
moment, the CEO/Owner's. So the RP ID must be set explicitly before the first
enrolment, and once any credential exists it cannot be changed through the UI.

**HTTPS.** Browsers refuse the WebAuthn API on insecure origins, localhost
excepted. An Odoo reached at ``http://192.168.1.10:8069`` cannot do WebAuthn at
all, no matter how correct this code is. Enrolment therefore refuses to start
over a plain-HTTP origin and says why, rather than producing an opaque browser
error that someone will spend a day debugging in Python.
"""

import base64
import logging
import os
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

PARAM_RP_ID = "sec_webauthn.rp_id"
PARAM_RP_NAME = "sec_webauthn.rp_name"
PARAM_ORIGIN = "sec_webauthn.origin"
PARAM_ALLOW_INSECURE = "sec_webauthn.allow_insecure_origin"

# US-6.2: challenges are single-use and time-limited.
CHALLENGE_TTL_MINUTES = 5


def b64url(raw):
    """Base64url without padding, as the WebAuthn wire format expects."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class WebauthnConfig(models.AbstractModel):
    """Relying Party configuration and its preconditions."""

    _name = "sec.webauthn.config"
    _description = "WebAuthn Relying Party Configuration"

    @api.model
    def _param(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    @api.model
    def rp_id(self):
        return (self._param(PARAM_RP_ID) or "").strip()

    @api.model
    def rp_name(self):
        return self._param(PARAM_RP_NAME) or "Odoo Security Suite"

    @api.model
    def expected_origin(self):
        return (self._param(PARAM_ORIGIN) or "").strip()

    @api.model
    def allow_insecure_origin(self):
        """Only ever True for local development. Never in production."""
        return self._param(PARAM_ALLOW_INSECURE, "False") in ("True", "true", "1")

    @api.model
    def check_ready(self, origin=None):
        """Raise a specific, actionable error if enrolment cannot proceed."""
        rp_id = self.rp_id()
        if not rp_id:
            raise UserError(
                _(
                    "The WebAuthn Relying Party ID has not been set.\n\n"
                    "Set the system parameter '%(param)s' to the single "
                    "canonical domain users will always reach Odoo on, for "
                    "example 'erp.example.com'.\n\n"
                    "Choose carefully: credentials bind to one origin, so "
                    "changing this later invalidates every enrolled "
                    "authenticator and forces everyone to re-enrol.",
                    param=PARAM_RP_ID,
                )
            )
        if origin:
            if origin.startswith("http://") and not self.allow_insecure_origin():
                raise UserError(
                    _(
                        "WebAuthn requires a secure origin. This Odoo is being "
                        "reached over plain HTTP at %(origin)s, and browsers "
                        "refuse the WebAuthn API on insecure origins "
                        "(localhost excepted).\n\n"
                        "Serve Odoo over HTTPS with a certificate your users' "
                        "browsers trust before enrolling authenticators. No "
                        "server-side configuration can work around this.",
                        origin=origin,
                    )
                )
            expected = self.expected_origin()
            if expected and origin.rstrip("/") != expected.rstrip("/"):
                raise UserError(
                    _(
                        "This request came from %(actual)s but the configured "
                        "WebAuthn origin is %(expected)s. Credentials enrolled "
                        "from a different origin would not work.",
                        actual=origin,
                        expected=expected,
                    )
                )
        return True


class WebauthnChallenge(models.Model):
    """A single-use, time-limited challenge (US-6.2)."""

    _name = "sec.webauthn.challenge"
    _description = "WebAuthn Challenge"
    _order = "created_at desc"

    user_id = fields.Many2one(
        comodel_name="res.users", string="User", required=True, index=True,
        ondelete="cascade",
    )
    challenge = fields.Char(
        string="Challenge (base64url)", required=True, index=True, readonly=True,
        help="Random 32-byte value the authenticator must sign.",
    )
    purpose = fields.Selection(
        selection=[
            ("registration", "Credential Registration"),
            ("authentication", "Approval Authentication"),
        ],
        string="Purpose",
        required=True,
        help="A registration challenge must never be accepted for an "
        "authentication ceremony, or vice versa.",
    )
    context_ref = fields.Char(
        string="Context Reference",
        help="What the assertion authorises, as model,id. An assertion is "
        "bound to one specific action; it is not a general-purpose token.",
    )
    created_at = fields.Datetime(
        string="Issued At (UTC)", required=True, default=fields.Datetime.now,
        readonly=True,
    )
    expires_at = fields.Datetime(
        string="Expires At (UTC)", required=True, readonly=True, index=True,
    )
    consumed = fields.Boolean(
        string="Consumed", default=False, readonly=True,
        help="Single use. A replayed challenge is refused even before expiry.",
    )
    consumed_at = fields.Datetime(string="Consumed At", readonly=True)

    @api.model
    def issue(self, user, purpose, context_ref=None):
        """Create a fresh challenge for one user and one purpose."""
        now = fields.Datetime.now()
        return self.sudo().create(
            {
                "user_id": user.id,
                "challenge": b64url(os.urandom(32)),
                "purpose": purpose,
                "context_ref": context_ref,
                "created_at": now,
                "expires_at": now + timedelta(minutes=CHALLENGE_TTL_MINUTES),
            }
        )

    def consume(self):
        """Mark used. Returns False if already used or expired."""
        self.ensure_one()
        if self.consumed:
            _logger.warning(
                "Replay attempt: challenge %s already consumed", self.id
            )
            return False
        if fields.Datetime.now() > self.expires_at:
            _logger.warning("Expired challenge %s presented", self.id)
            return False
        self.sudo().write(
            {"consumed": True, "consumed_at": fields.Datetime.now()}
        )
        return True

    @api.model
    def gc_expired(self):
        """Remove spent and expired challenges. They are not evidence."""
        cutoff = fields.Datetime.now() - timedelta(days=1)
        self.sudo().search([("created_at", "<", cutoff)]).unlink()


class WebauthnCredential(models.Model):
    """One enrolled authenticator belonging to one user."""

    _name = "sec.webauthn.credential"
    _description = "WebAuthn Credential"
    _order = "user_id, enrolled_at desc"

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        index=True,
        ondelete="restrict",
        help="Owner of the authenticator. Restrict on delete so that removing "
        "a user cannot silently orphan approval evidence.",
    )
    mechanism = fields.Selection(
        selection=[
            ("webauthn", "Passkey (WebAuthn)"),
            ("bound_device", "Paired app on a phone or tablet"),
        ],
        string="Proof Mechanism",
        default="webauthn",
        required=True,
        readonly=True,
        index=True,
        help="How this device proves it is itself.\n\n"
        "Passkeys are the W3C standard and run through the browser or the "
        "platform's own credential manager. Paired apps hold a keypair this "
        "system issued them, unlocked by the phone's fingerprint or face.\n\n"
        "Both store only a public key here and both are gated on the user "
        "being present, so either satisfies a strong-authentication rule. The "
        "distinction is recorded rather than flattened so that approval "
        "evidence says which one was actually used.",
    )
    credential_id = fields.Char(
        string="Credential ID",
        required=True,
        index=True,
        readonly=True,
        help="Authenticator-supplied identifier, base64url. Unique. For a "
        "paired app this is the handle issued at pairing.",
    )
    public_key = fields.Text(
        string="Public Key",
        required=True,
        readonly=True,
        help="The public half only. COSE for a passkey, a base64url Ed25519 "
        "key for a paired app. The private key and any biometric data never "
        "leave the device and never transit the network (BRD FR-6.2).",
    )
    sign_counter = fields.Integer(
        string="Signature Counter",
        default=0,
        readonly=True,
        help="Monotonic counter reported by the authenticator. A counter that "
        "goes backwards indicates a cloned authenticator; detection is P2-3.",
    )
    device_label = fields.Char(
        string="Device Label",
        required=True,
        help="What the user calls this device, so they can tell two "
        "authenticators apart when revoking one.",
    )
    authenticator_type = fields.Selection(
        selection=[
            ("platform", "Platform (phone or laptop biometric)"),
            ("cross-platform", "Roaming (hardware security key)"),
            ("unknown", "Unknown"),
        ],
        string="Type",
        default="unknown",
        help="Roaming keys are recommended as the second authenticator for the "
        "CEO/Owner, since they survive loss of the phone.",
    )
    aaguid = fields.Char(
        string="AAGUID", readonly=True,
        help="Authenticator model identifier, where the device reports one.",
    )
    transports = fields.Char(
        string="Transports", readonly=True,
        help="usb, nfc, ble, internal, hybrid.",
    )
    rp_id = fields.Char(
        string="Relying Party ID",
        required=True,
        readonly=True,
        help="The RP ID in force at enrolment. Stored per credential so that a "
        "later change of domain is visible rather than mysterious.",
    )
    enrolled_at = fields.Datetime(
        string="Enrolled At (UTC)", required=True, default=fields.Datetime.now,
        readonly=True,
    )
    last_used_at = fields.Datetime(string="Last Used At", readonly=True)
    active = fields.Boolean(
        string="Active", default=True,
        help="Revoked credentials are deactivated, never deleted: the record "
        "that a credential existed is part of the approval evidence.",
    )
    revoked_reason = fields.Char(string="Revocation Reason")

    _sql_constraints = [
        (
            "credential_id_uniq",
            "unique(credential_id)",
            "That credential is already enrolled.",
        ),
    ]

    @api.constrains("rp_id")
    def _check_rp_id_matches_config(self):
        configured = self.env["sec.webauthn.config"].rp_id()
        for credential in self:
            if configured and credential.rp_id != configured:
                raise ValidationError(
                    _(
                        "Credential was enrolled against Relying Party "
                        "'%(stored)s' but the system is configured for "
                        "'%(configured)s'. It would never authenticate.",
                        stored=credential.rp_id,
                        configured=configured,
                    )
                )

    def write(self, vals):
        """The cryptographic material is immutable once enrolled."""
        locked = {"credential_id", "public_key", "rp_id", "enrolled_at"}
        if locked & set(vals):
            raise UserError(
                _(
                    "A credential's cryptographic material cannot be changed "
                    "after enrolment. Revoke it and enrol a new one."
                )
            )
        # The sign counter is clone-detection state. Letting anyone write it
        # would let an attacker who cloned a key raise the stored counter and
        # erase the evidence of the regression before it is noticed.
        if "sign_counter" in vals and not self.env.context.get(
            "webauthn_counter_update"
        ):
            raise UserError(
                _(
                    "The signature counter is maintained by the verification "
                    "process and cannot be set by hand."
                )
            )
        return super().write(vals)

    # Set by reset_enrolment_for, and honoured by unlink below. Named rather
    # than passed as an argument because unlink takes none, and because a
    # reader of either half should be able to find the other.
    RESET_CONTEXT_KEY = "webauthn_enrolment_reset"

    def unlink(self):
        """Refused, except during a deliberate and audited enrolment reset.

        The rule stands: a credential is evidence for every approval it
        authenticated, so revoking archives rather than deletes. But the
        enrolment gate reads *history*, so an account whose devices have all
        been revoked can never self-enrol again -- correct for a key lost in the
        field, wrong for a replaced handset, and previously with no way out at
        all. ``reset_enrolment_for`` is that way out, and it cannot do its job
        without this.

        Two things keep the exception honest:

        * ``reset_enrolment_for`` writes the audit record **before** calling
          this, naming who reset whom and what was removed. The evidence
          survives in the locker even though the rows do not.
        * The rights are re-checked **here**, not merely at the caller. A
          context key is a request, not an authorisation, and anything holding
          ``sudo()`` could otherwise set it and delete freely.
        """
        if self.env.context.get(self.RESET_CONTEXT_KEY):
            self._require_reset_rights()
            return super().unlink()

        raise UserError(
            _(
                "Credentials are revoked, not deleted. The record that a "
                "credential existed is part of the evidence for every approval "
                "it authenticated. "
                "To let someone enrol from scratch, use Security Suite > "
                "Authenticators > Reset Enrolment. That records who did it and "
                "why before removing anything."
            )
        )

    def action_revoke(self):
        """Deactivate a credential.

        Note the deliberate asymmetry with re-enrolment: revoking is
        self-service because a user who thinks their key is compromised must be
        able to act immediately, and the failure mode is inconvenience.
        Re-enrolling is not self-service (US-6.3, P2-4) because its failure
        mode is an attacker adding their own authenticator.
        """
        for credential in self:
            credential.write(
                {
                    "active": False,
                    "revoked_reason": credential.revoked_reason
                    or _("Revoked by %s", self.env.user.login),
                }
            )
            self.env["sec.anomaly.mixin"]._raise_anomaly(
                alert_type="credential_anomaly",
                name=_("WebAuthn credential revoked"),
                reason=_(
                    "Credential '%(label)s' belonging to %(owner)s was revoked "
                    "by %(actor)s.",
                    label=credential.device_label,
                    owner=credential.user_id.login,
                    actor=self.env.user.login,
                ),
                severity="high",
                record=credential,
            )
        return True

    # ------------------------------------------------------------------
    # Interface consumed by other modules
    # ------------------------------------------------------------------
    # _verification_ready() and _verify_pending_assertion() are implemented in
    # webauthn_verify.py (P2-2), which inherits this model.

    # Which credential actually answered this request. Stamped by whichever
    # verification path succeeded, so evidence records the device that signed
    # rather than an arbitrary one the user happens to own. Someone holding a
    # passkey and a paired phone was previously credited to whichever sorted
    # first, which made the approval trail quietly wrong about the proof given.
    VERIFIED_CREDENTIAL_ATTR = "sec_webauthn_verified_credential_id"

    def _stamp_verified(self):
        """Note on the request that this credential is the one that verified."""
        self.ensure_one()
        try:
            from odoo.http import request

            if request:
                setattr(request, self.VERIFIED_CREDENTIAL_ATTR, self.id)
        except Exception:  # noqa: BLE001 - cron and shell have no request
            pass
        return self

    @api.model
    def _verified_credential(self):
        """The credential stamped this request, or an empty recordset."""
        try:
            from odoo.http import request

            if not request:
                return self.browse()
            stamped = getattr(self, "VERIFIED_CREDENTIAL_ATTR", None)
            credential_id = getattr(request, stamped, None) if stamped else None
        except Exception:  # noqa: BLE001 - no HTTP context
            return self.browse()
        if not credential_id:
            return self.browse()
        return self.sudo().browse(credential_id).exists()

    @api.model
    def enrolled_for(self, user):
        return self.sudo().search(
            [("user_id", "=", user.id), ("active", "=", True)]
        )

    @api.model
    def check_enrolment_sufficient(self, user):
        """BRD FR-6.5: the Nuclear Key holder needs at least two authenticators.

        A single device is a single point of failure on the highest-authority
        approval step in the system. Reported rather than enforced at enrolment
        time, since the second device is often procured separately.
        """
        credentials = self.enrolled_for(user)
        roles = self.env["role.plaza_model"].sudo().search(
            [("active", "=", True), ("group_id", "in", user.groups_id.ids)]
        )
        is_nuclear_key = any(r.is_approval_tier == "tier_3" for r in roles)
        needs_any = any(r.requires_webauthn for r in roles)
        required = 2 if is_nuclear_key else (1 if needs_any else 0)
        return {
            "user": user.login,
            "enrolled": len(credentials),
            "required": required,
            "sufficient": len(credentials) >= required,
            "is_nuclear_key": is_nuclear_key,
        }

    # ------------------------------------------------------------------
    # Starting over
    # ------------------------------------------------------------------
    @api.model
    def reset_enrolment_for(self, user, reason=None):
        """Clear a user's enrolment history so they can enrol from scratch.

        Revoking a credential archives it, deliberately: a revocation is
        evidence and deleting it would erase the record of what someone once
        held. But ``_check_enrolment_permitted`` reads *history*, not active
        credentials, so a user whose devices have all been revoked lands on
        Route 3 -- break-glass recovery, two other approvers -- rather than
        Route 1. That is right for somebody who lost a key in the field, and
        wrong for a new handset, a test account, or a device replaced on
        purpose.

        This is the deliberate way out, and it is destructive, so:

        * **Administrators only.** Anyone able to silently clear an enrolment
          could then enrol their own device and approve in that person's name,
          which is the exact attack the three-route logic exists to prevent.
        * **The audit record is written first.** The anomaly carries who reset
          whom, and what was deleted, so the history survives in the locker even
          though the credential rows do not.
        """
        self._require_reset_rights()
        user.ensure_one()

        history = self.sudo().with_context(active_test=False).search(
            [("user_id", "=", user.id)]
        )
        if not history:
            return 0

        labels = ", ".join(history.mapped("device_label")) or "(unnamed)"
        count = len(history)

        # Before the delete, not after: a reset that fails half way through must
        # not leave the only account of it unwritten.
        self._raise_credential_anomaly(
            user,
            _("Security device enrolment reset"),
            _(
                "%(actor)s cleared the enrolment history of %(subject)s "
                "(%(count)s credential(s): %(labels)s). Reason: %(reason)s. "
                "The user can now enrol a first device without break-glass "
                "recovery.",
                actor=self.env.user.login,
                subject=user.login,
                count=count,
                labels=labels,
                reason=reason or _("not given"),
            ),
            severity="high",
        )
        _logger.warning(
            "WebAuthn enrolment reset: %s cleared %s credential(s) for %s",
            self.env.user.login,
            count,
            user.login,
        )
        history.sudo().with_context(**{self.RESET_CONTEXT_KEY: True}).unlink()
        return count

    @api.model
    def _require_reset_rights(self):
        """Only a security administrator may clear somebody's enrolment."""
        allowed = any(
            self._safe_has_group(xmlid)
            for xmlid in (
                "sec_plaza_rbac.group_security_super_admin",
                "sec_plaza_rbac.group_plaza_admin",
                "base.group_system",
            )
        )
        if not allowed:
            raise UserError(
                _(
                    "Only a security administrator can reset a security device "
                    "enrolment. Anyone able to do this silently could enrol "
                    "their own device and approve in your name."
                )
            )

    @api.model
    def _safe_has_group(self, xmlid):
        """``has_group`` raises on an unknown xmlid, which is routine here:
        sec_plaza_rbac need not be installed on every deployment."""
        try:
            return self.env.user.has_group(xmlid)
        except ValueError:
            return False

    def action_reset_enrolment(self):
        """Action-menu entry on the credential list.

        Resets every user represented in the selection, not just the selected
        rows: clearing one of somebody's three credentials would leave the
        history non-empty and the user still on Route 3, which looks like the
        button did nothing.
        """
        users = self.mapped("user_id")
        total = 0
        for user in users:
            total += self.reset_enrolment_for(
                user, reason=_("Reset from the credential list")
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "warning",
                "title": _("Enrolment reset"),
                "message": _(
                    "%(count)s credential(s) removed for %(users)s. They can "
                    "now enrol a first device again.",
                    count=total,
                    users=", ".join(users.mapped("login")),
                ),
                "sticky": False,
            },
        }
