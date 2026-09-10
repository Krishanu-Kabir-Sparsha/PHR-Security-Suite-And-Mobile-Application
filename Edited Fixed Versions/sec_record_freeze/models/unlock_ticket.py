# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Single-use unlock tickets (P2-8 support).

Lives in ``sec_record_freeze`` rather than in the override engine so that the
dependency runs the right way: the freeze mixin must be able to consult a
ticket without the freeze module depending on the override module.

A ticket is deliberately narrow. It names one record, one set of fields, one
issuer, and a short validity, and it can be spent once. The alternative —
"this user may edit frozen records for the next hour" — is a standing key, and
a standing key is what the whole suite exists to eliminate.
"""

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_TTL_MINUTES = 10


class FreezeUnlockTicket(models.Model):
    _name = "sec.freeze.unlock.ticket"
    _description = "Single-Use Frozen Record Unlock Ticket"
    _order = "issued_at desc"

    res_model = fields.Char(string="Model", required=True, index=True, readonly=True)
    res_id = fields.Integer(string="Record ID", required=True, index=True, readonly=True)
    allowed_fields = fields.Char(
        string="Permitted Fields",
        required=True,
        readonly=True,
        help="Comma-separated. The unlock authorises exactly these fields on "
        "exactly this record. Anything else is still refused, so an approval "
        "for a price correction cannot be spent changing the counterparty.",
    )
    source_ref = fields.Char(
        string="Authorising Record",
        required=True,
        readonly=True,
        help="model,id of the override request whose approvals authorised this.",
    )
    issued_by_id = fields.Many2one(
        comodel_name="res.users", string="Issued By", required=True, readonly=True
    )
    issued_at = fields.Datetime(
        string="Issued At (UTC)", required=True, default=fields.Datetime.now,
        readonly=True,
    )
    expires_at = fields.Datetime(string="Expires At (UTC)", required=True, readonly=True)
    consumed = fields.Boolean(string="Spent", default=False, readonly=True)
    consumed_at = fields.Datetime(string="Spent At", readonly=True)

    @api.model
    def issue(self, record, field_names, source_ref, ttl_minutes=DEFAULT_TTL_MINUTES):
        """Mint a ticket for one record and one field set."""
        if not field_names:
            raise UserError(
                _("An unlock ticket must name the fields it authorises.")
            )
        now = fields.Datetime.now()
        ticket = self.sudo().create(
            {
                "res_model": record._name,
                "res_id": record.id,
                "allowed_fields": ",".join(sorted(field_names)),
                "source_ref": source_ref,
                "issued_by_id": self.env.user.id,
                "issued_at": now,
                "expires_at": now + timedelta(minutes=ttl_minutes),
            }
        )
        _logger.warning(
            "Unlock ticket %s issued for %s,%s fields=%s by %s (authorised by %s)",
            ticket.id,
            record._name,
            record.id,
            ticket.allowed_fields,
            self.env.user.login,
            source_ref,
        )
        return ticket

    def field_set(self):
        self.ensure_one()
        return {f.strip() for f in (self.allowed_fields or "").split(",") if f.strip()}

    def is_valid_for(self, record, vals):
        """Whether this ticket authorises writing ``vals`` to ``record``."""
        self.ensure_one()
        if self.consumed:
            return False
        if fields.Datetime.now() > self.expires_at:
            return False
        if self.res_model != record._name or self.res_id != record.id:
            return False
        written = set(vals or {})
        # Odoo writes technical fields alongside; only the protected ones
        # needed authorising, and the caller passes those.
        return written.issubset(self.field_set())

    def consume(self):
        """Spend the ticket. A ticket authorises exactly one write."""
        self.ensure_one()
        if self.consumed:
            return False
        self.sudo().write(
            {"consumed": True, "consumed_at": fields.Datetime.now()}
        )
        return True

    def write(self, vals):
        allowed = {"consumed", "consumed_at"}
        if not set(vals).issubset(allowed):
            raise UserError(
                _(
                    "An unlock ticket cannot be edited after issue. Its whole "
                    "value is that its scope was fixed by the approvals."
                )
            )
        return super().write(vals)

    def unlink(self):
        raise UserError(
            _("Unlock tickets are retained as evidence of what was authorised.")
        )

    @api.model
    def cron_expire(self):
        """Nothing to delete; expiry is by timestamp. Reports stale grants."""
        now = fields.Datetime.now()
        stale = self.sudo().search(
            [("consumed", "=", False), ("expires_at", "<", now)]
        )
        if stale:
            _logger.info("%s unlock ticket(s) expired unused", len(stale))
        return len(stale)
