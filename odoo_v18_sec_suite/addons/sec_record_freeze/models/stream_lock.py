# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Independent back-end lock toggles for Sales and Purchase.

Implements BRD FR-3.3 and PRD US-3.2.

This is a *different and stronger* control than the confirm-state freeze in
``freeze_mixin.py``, and the difference matters:

- The freeze stops edits to records that are **confirmed**. Draft work carries
  on normally. It is the everyday control.
- A stream lock stops edits to **everything** in that stream, draft included,
  for everyone except a Super Administrator. It is a lockdown switch: the thing
  you pull during a suspected incident, a handover dispute, or a forensic
  window when you need the data to stop moving.

Operational consequence the Super Admin must understand before pulling it, and
which the UI states plainly: **automated jobs stop too.** Scheduled invoicing,
delivery processing and anything else touching the locked stream will fail while
the lock is engaged. That is the intent of a lockdown rather than a defect, but
it is not a switch to flip casually.
"""

import logging

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# System parameter that permits a toggle without strong authentication.
# Exists only because WebAuthn does not yet (P2-2). See _confirm_strong_auth.
ALLOW_WEAK_TOGGLE_PARAM = "sec_record_freeze.allow_toggle_without_webauthn"


class StreamLock(models.Model):
    """One lockdown toggle per transaction stream."""

    _name = "sec.stream.lock"
    _description = "Back-end Stream Lock"
    _order = "stream"

    stream = fields.Selection(
        selection=[
            ("sales", "Sales"),
            ("purchase", "Purchase"),
            ("accounting", "Accounting"),
        ],
        string="Transaction Stream",
        required=True,
        help="Sales and Purchase are independent by requirement (US-3.2): "
        "locking one must not affect the other.",
    )
    locked = fields.Boolean(
        string="Locked",
        default=False,
        readonly=True,
        help="When locked, no user except a Super Administrator may create, "
        "modify or delete records in this stream, in any state.",
    )
    locked_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Locked By",
        readonly=True,
        help="Who engaged the current lock.",
    )
    locked_at = fields.Datetime(
        string="Locked At (UTC)",
        readonly=True,
        help="When the current lock was engaged.",
    )
    reason = fields.Text(
        string="Current Reason",
        readonly=True,
        help="Why the stream is locked. Mandatory when engaging a lock.",
    )
    log_ids = fields.One2many(
        comodel_name="sec.stream.lock.log",
        inverse_name="lock_id",
        string="Toggle History",
        help="Every state change, with actor, timestamp and before/after.",
    )

    _sql_constraints = [
        ("stream_uniq", "unique(stream)", "That stream already has a lock record."),
    ]

    # ------------------------------------------------------------------
    # Strong authentication hook
    # ------------------------------------------------------------------
    @api.model
    def _webauthn_available(self):
        """Whether a WebAuthn verification provider is installed.

        P2-2 provides ``sec.webauthn.credential`` and re-implements this as a
        real assertion check. Until then there is nothing to call.
        """
        return "sec.webauthn.credential" in self.env

    @api.model
    def _confirm_strong_auth(self):
        """Require WebAuthn confirmation for a toggle, per US-3.2.

        Returns True when the action was strongly authenticated, False when it
        was permitted without it. Never silently returns True.

        The Phase 1 position: WebAuthn does not exist yet. Rather than fake a
        confirmation or block the control entirely, the toggle proceeds and is
        **recorded as weakly authenticated**, so the audit trail distinguishes
        toggles that were cryptographically confirmed from those that were not.
        A blanket 'True' here would be the worst option: it would put a false
        claim of strong authentication into the evidence record.
        """
        if self._webauthn_available():
            provider = self.env["sec.webauthn.credential"]
            if provider._verification_ready():
                # Verification exists, so a failure means the assertion was bad.
                # Proceeding "weakly" here would silently accept an unverified
                # approval on the strongest control in the system.
                if not provider._verify_pending_assertion():
                    raise UserError(
                        _(
                            "WebAuthn confirmation failed or was not provided. "
                            "This action requires an assertion from an enrolled "
                            "authenticator."
                        )
                    )
                return True
            _logger.warning(
                "WebAuthn module is installed but verification is not yet "
                "implemented (P2-2); falling back to policy for this toggle."
            )
        allow_weak = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(ALLOW_WEAK_TOGGLE_PARAM, "True")
        )
        if allow_weak not in ("True", "true", "1"):
            raise UserError(
                _(
                    "This action requires WebAuthn confirmation, which is not "
                    "yet available on this system, and the policy parameter "
                    "'%(param)s' is set to refuse unconfirmed toggles.",
                    param=ALLOW_WEAK_TOGGLE_PARAM,
                )
            )
        return False

    # ------------------------------------------------------------------
    # Toggling
    # ------------------------------------------------------------------
    def _check_super_admin(self):
        if not self.env.user.has_group(
            "sec_plaza_rbac.group_security_super_admin"
        ):
            raise UserError(
                _(
                    "Only a Security Suite Super Administrator may change a "
                    "back-end stream lock."
                )
            )

    def _record_toggle(self, new_state, reason, strongly_authenticated):
        """Write the tamper-evident history entry for a toggle."""
        self.ensure_one()
        self.env["sec.stream.lock.log"].sudo().create(
            {
                "lock_id": self.id,
                "stream": self.stream,
                "state_before": self.locked,
                "state_after": new_state,
                "actor_id": self.env.user.id,
                "changed_at": fields.Datetime.now(),
                "reason": reason,
                "strongly_authenticated": strongly_authenticated,
                "source_ip": self.env["sec.anomaly.mixin"]._current_source_ip(),
            }
        )
        # US-3.2 says the toggle is written to the Locker. The Locker is P1-7
        # and does not exist yet; this local log is the interim record and P1-7
        # must additionally capture sec.stream.lock writes.
        self.env["sec.anomaly.mixin"]._raise_anomaly(
            alert_type="frozen_record_write_attempt",
            name=_(
                "%(stream)s stream %(action)s",
                stream=dict(self._fields["stream"].selection).get(self.stream),
                action=_("LOCKED") if new_state else _("UNLOCKED"),
            ),
            reason=_(
                "%(user)s set the %(stream)s back-end lock to %(state)s. "
                "Reason given: %(reason)s. Strong authentication: %(auth)s.",
                user=self.env.user.login,
                stream=self.stream,
                state=_("locked") if new_state else _("unlocked"),
                reason=reason,
                auth=_("yes") if strongly_authenticated else _("NO"),
            ),
            severity="critical",
            record=self,
        )
        _logger.critical(
            "Stream lock %s -> %s by %s (strong auth: %s). Reason: %s",
            self.stream,
            new_state,
            self.env.user.login,
            strongly_authenticated,
            reason,
        )

    def action_engage_lock(self, reason=None):
        """Lock the stream. Requires Super Admin, a reason, and confirmation."""
        self.ensure_one()
        self._check_super_admin()
        reason = (reason or self.env.context.get("lock_reason") or "").strip()
        if not reason:
            raise UserError(
                _(
                    "Engaging a stream lock requires a written reason. It will "
                    "appear in the monthly forensic report."
                )
            )
        if self.locked:
            raise UserError(_("That stream is already locked."))
        strong = self._confirm_strong_auth()
        self._record_toggle(True, reason, strong)
        self.sudo().with_context(sec_stream_lock_internal=True).write(
            {
                "locked": True,
                "locked_by_id": self.env.user.id,
                "locked_at": fields.Datetime.now(),
                "reason": reason,
            }
        )
        return True

    def action_release_lock(self, reason=None):
        """Unlock the stream. Same requirements as engaging one."""
        self.ensure_one()
        self._check_super_admin()
        reason = (reason or self.env.context.get("lock_reason") or "").strip()
        if not reason:
            raise UserError(
                _("Releasing a stream lock requires a written reason.")
            )
        if not self.locked:
            raise UserError(_("That stream is not locked."))
        strong = self._confirm_strong_auth()
        self._record_toggle(False, reason, strong)
        self.sudo().with_context(sec_stream_lock_internal=True).write(
            {
                "locked": False,
                "locked_by_id": False,
                "locked_at": False,
                "reason": reason,
            }
        )
        return True

    # ------------------------------------------------------------------
    # Enforcement entry point, called from the freeze mixin
    # ------------------------------------------------------------------
    @api.model
    def check_stream_writable(self, stream, records=None):
        """Raise if ``stream`` is locked and the acting user is not Super Admin."""
        if not stream or stream == "other":
            return True
        if stream not in self._locked_streams():
            return True
        lock = self.sudo().search(
            [("stream", "=", stream), ("locked", "=", True)], limit=1
        )
        if not lock:
            return True
        if self.env.user.has_group("sec_plaza_rbac.group_security_super_admin"):
            return True
        raise UserError(
            _(
                "The %(stream)s back-end is currently locked by a Super "
                "Administrator and cannot be changed.\n\n"
                "Locked at: %(when)s\nReason: %(reason)s\n\n"
                "Contact the Super Administrator if you believe this is in "
                "error. This attempt has been recorded.",
                stream=stream,
                when=lock.locked_at,
                reason=lock.reason or _("(none recorded)"),
            )
        )

    @api.model
    @tools.ormcache()
    def _locked_streams(self):
        """Cached set of currently locked streams.

        A lockdown is rare and permanent-ish while it lasts, so the common case
        is an empty set and a cache hit. The cache is cleared on every toggle,
        so a lock takes effect immediately rather than at the next restart —
        which would be an unacceptable property for this particular control.
        """
        return tuple(
            self.sudo().search([("locked", "=", True)]).mapped("stream")
        )

    def write(self, vals):
        """Force toggling through the action methods.

        Writing ``locked`` directly would skip the reason, the confirmation and
        the history entry — the three things that make the toggle auditable.
        """
        if "locked" in vals and not self.env.context.get("sec_stream_lock_internal"):
            raise UserError(
                _(
                    "Use the Lock and Unlock buttons. Setting this field "
                    "directly would bypass the reason, the confirmation step "
                    "and the toggle history."
                )
            )
        result = super().write(vals)
        # A lock must bite immediately, so the cache is cleared on every write
        # rather than only on the toggle path.
        self.env.registry.clear_cache()
        return result


class StreamLockLog(models.Model):
    """Append-only history of every stream lock toggle."""

    _name = "sec.stream.lock.log"
    _description = "Stream Lock Toggle Log"
    _order = "changed_at desc, id desc"

    lock_id = fields.Many2one(
        comodel_name="sec.stream.lock",
        string="Lock",
        required=True,
        ondelete="restrict",
        index=True,
    )
    stream = fields.Char(string="Stream", required=True, index=True)
    state_before = fields.Boolean(string="Locked Before", required=True)
    state_after = fields.Boolean(string="Locked After", required=True)
    actor_id = fields.Many2one(
        comodel_name="res.users",
        string="Changed By",
        required=True,
        ondelete="restrict",
    )
    changed_at = fields.Datetime(string="Changed At (UTC)", required=True)
    reason = fields.Text(string="Reason", required=True)
    strongly_authenticated = fields.Boolean(
        string="WebAuthn Confirmed",
        required=True,
        help="False means the toggle was made without cryptographic "
        "confirmation, which US-3.2 requires. Recorded honestly rather than "
        "asserted, so the audit trail distinguishes the two.",
    )
    source_ip = fields.Char(string="Source IP")

    def write(self, vals):
        raise UserError(_("Stream lock history entries cannot be modified."))

    def unlink(self):
        raise UserError(_("Stream lock history entries cannot be deleted."))
