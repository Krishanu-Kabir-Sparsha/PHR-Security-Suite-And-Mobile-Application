# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The state between "password accepted" and "device confirmed".

Sign-in is two factors and therefore two HTTP calls, and something has to
remember the first one while the second is in flight. That something must not be
an access token: a token is what you get for passing *both* factors, and issuing
one after the password alone would mean a stolen password grants a working
session for as long as it takes nobody to notice.

So this record holds exactly one fact -- "this person proved they know the
password, just now" -- and nothing else. It cannot read anything, cannot call
anything, and expires in minutes.

Hashed like the access tokens, for the same reason: a database dump, a log line
or a backup should not contain anything that can be replayed. See mobile_token.
"""

import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models

from .mobile_token import token_hash

_logger = logging.getLogger(__name__)

# Long enough to unlock a phone, find a fingerprint reader and be interrupted
# once; short enough that a stolen password plus a stolen handset is a race
# rather than an opportunity. WebAuthn challenges expire in five minutes too, so
# a longer window here would only produce a confusing "challenge expired" after
# this record said it was still fine.
PENDING_TTL = timedelta(minutes=5)

# A WebAuthn assertion either verifies or it does not; there is nothing to
# guess. Several failures in a row means something is wrong -- a broken client,
# or somebody trying responses against a password they have -- and the right
# answer is to make them start again from the password.
MAX_ATTEMPTS = 5


class MobilePendingAuth(models.Model):
    _name = "perfecthr.mobile.pending.auth"
    _description = "Perfect HR Mobile Sign-in Awaiting Device Confirmation"
    _order = "create_date desc"

    user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        ondelete="cascade",
        index=True,
        readonly=True,
    )
    token_hash = fields.Char(required=True, index=True, readonly=True)
    expires_at = fields.Datetime(required=True, readonly=True)
    source_ip = fields.Char(readonly=True)
    device_label = fields.Char(readonly=True)
    attempts = fields.Integer(default=0, readonly=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Signing Into",
        ondelete="cascade",
        readonly=True,
        help="The company chosen on the first call, held here until the "
        "device confirms.\n\n"
        "It is carried rather than re-sent with the second call on purpose: a "
        "client that could name the company again at confirmation time could "
        "name a different one, and the check that it was permitted happened "
        "against the first answer.",
    )

    @api.model
    def open_for(self, user, device_label=None, source_ip=None, company=None):
        """Start a sign-in that still needs a device. Returns (record, token).

        Any earlier pending sign-in for the same user is dropped first. Someone
        who retypes their password has abandoned the previous attempt, and
        leaving it alive would keep a second usable handle in play for no
        reason.
        """
        self.sudo().search([("user_id", "=", user.id)]).unlink()

        raw = secrets.token_urlsafe(32)
        record = self.sudo().create(
            {
                "user_id": user.id,
                "token_hash": token_hash(raw),
                "expires_at": fields.Datetime.now() + PENDING_TTL,
                "source_ip": source_ip,
                "device_label": device_label,
                "company_id": company.id if company else False,
            }
        )
        return record, raw

    @api.model
    def resolve(self, raw):
        """The live record for a presented handle, or an empty recordset.

        Deliberately returns empty for expired and unknown alike. Telling a
        caller which of the two it was distinguishes "your password was right
        but you were slow" from "your password was wrong", and only one of those
        is worth an attacker's time.
        """
        if not raw:
            return self.sudo().browse()
        record = self.sudo().search(
            [("token_hash", "=", token_hash(raw))], limit=1
        )
        if not record:
            return self.sudo().browse()
        if record.expires_at <= fields.Datetime.now():
            record.unlink()
            return self.sudo().browse()
        return record

    def register_failure(self):
        """Count a failed confirmation, and drop the record once it is spent."""
        self.ensure_one()
        self.sudo().attempts += 1
        if self.attempts >= MAX_ATTEMPTS:
            _logger.warning(
                "Mobile sign-in for %s abandoned after %s failed device "
                "confirmations",
                self.user_id.login,
                self.attempts,
            )
            self.sudo().unlink()
            return False
        return True

    @api.model
    def purge_expired(self):
        """Housekeeping, from the same cron that purges spent tokens."""
        stale = self.sudo().search(
            [("expires_at", "<=", fields.Datetime.now())]
        )
        count = len(stale)
        stale.unlink()
        if count:
            _logger.info("Purged %s expired pending sign-ins", count)
        return count
