# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Bearer tokens for the mobile app.

Opaque random tokens in a table, deliberately not JWTs. A JWT's advantage is
stateless verification across many services, and there is one service here.
What we actually need is the opposite property: a token in a table can be
**revoked**. When somebody loses a phone, that row is deactivated and the device
is out. Revoking a JWT means maintaining a blocklist, which is the statelessness
given back with extra moving parts. This also mirrors Odoo's own
res.users.apikeys, so it is a pattern a future maintainer will recognise.

Only a SHA-256 hash of each token is stored. The plaintext is returned once, at
issue, and never again, so a read of this table yields nothing usable. That
matters because the Audit Locker's own threat model (BRD 8.2) already assumes a
DBA can read any table. Plain SHA-256 is the right primitive rather than a slow
KDF: these are 256 bits of `secrets` entropy, so there is no low-entropy secret
to grind, and a per-request KDF would only add latency to every call.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied

_logger = logging.getLogger(__name__)

# Short access token, long refresh. The access token travels on every request,
# so its exposure window should be small; the refresh token is sent only to
# /auth/refresh.
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)


def token_hash(raw):
    """SHA-256 of a token, hex encoded. See the module docstring."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MobileToken(models.Model):
    _name = "perfecthr.mobile.token"
    _description = "Perfect HR Mobile Access Token"
    _order = "create_date desc"
    _rec_name = "device_label"

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        ondelete="cascade",
        index=True,
    )
    access_hash = fields.Char(
        string="Access Token Hash", required=True, index=True, readonly=True
    )
    refresh_hash = fields.Char(
        string="Refresh Token Hash", required=True, index=True, readonly=True
    )
    access_expires_at = fields.Datetime(required=True, readonly=True)
    refresh_expires_at = fields.Datetime(required=True, readonly=True)
    device_label = fields.Char(
        string="Device",
        help="Free text supplied by the app, so a person can recognise which "
        "handset a session belongs to when revoking it.",
    )
    source_ip = fields.Char(string="Issued From IP", readonly=True)
    last_used_at = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True)
    enrolment_required = fields.Boolean(
        default=False,
        readonly=True,
        help="This token was issued on a password alone, because the user has "
        "no device enrolled yet. It is restricted to enrolling one: see the "
        "gate in controllers/common.authenticated. Without that restriction the "
        "requirement would be cosmetic, since anyone could simply not enrol.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Signed Into",
        ondelete="cascade",
        readonly=True,
        help="The company this session operates in, chosen at sign-in and "
        "fixed for the life of the token. Pinned rather than read from the "
        "user's default on each request, because a phone left signed in "
        "overnight must not silently change company when an administrator "
        "edits the account.",
    )
    auth_mode = fields.Selection(
        selection=[
            ("basic", "Basic - password only"),
            ("advance", "Advanced - password and paired device"),
        ],
        string="Proof Given",
        default="advance",
        readonly=True,
        help="Which proof produced this session. Recorded because a basic "
        "session is materially weaker than an advanced one, and anything "
        "deciding what it may do -- or auditing what it did -- has to be able "
        "to tell them apart after the fact.",
    )

    _sql_constraints = [
        ("access_hash_uniq", "unique(access_hash)", "Token collision."),
        ("refresh_hash_uniq", "unique(refresh_hash)", "Token collision."),
    ]

    # ------------------------------------------------------------------
    # Issuing
    # ------------------------------------------------------------------
    @api.model
    def issue(
        self,
        user,
        device_label=None,
        source_ip=None,
        enrolment_required=False,
        company=None,
        auth_mode="advance",
    ):
        """Mint a token pair for ``user``. Returns (record, access, refresh).

        The plaintext values are handed back to the caller and never stored, so
        this is the only moment they exist anywhere but the client.

        ``company`` is validated by the caller, not here: this method mints
        tokens and does not decide who may have one. It falls back to the
        user's own default so that a caller which does not care about companies
        still produces a session pinned to something definite.
        """
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = fields.Datetime.now()
        record = self.sudo().create(
            {
                "user_id": user.id,
                "access_hash": token_hash(access),
                "refresh_hash": token_hash(refresh),
                "access_expires_at": now + ACCESS_TTL,
                "refresh_expires_at": now + REFRESH_TTL,
                "device_label": device_label or _("Mobile device"),
                "source_ip": source_ip,
                "enrolment_required": enrolment_required,
                "company_id": (company or user.company_id).id,
                "auth_mode": auth_mode or "advance",
            }
        )
        _logger.info(
            "Mobile token issued for %s (device=%s, ip=%s, company=%s, auth=%s)",
            user.login,
            device_label,
            source_ip,
            record.company_id.name,
            record.auth_mode,
        )
        return record, access, refresh

    # ------------------------------------------------------------------
    # Resolving
    # ------------------------------------------------------------------
    @api.model
    def resolve_access(self, raw):
        """Return the live token record for a presented access token, or empty.

        Looked up by hash, so a wrong token is simply not found.
        """
        if not raw:
            return self.browse()
        token = self.sudo().search(
            [
                ("access_hash", "=", token_hash(raw)),
                ("active", "=", True),
                ("access_expires_at", ">", fields.Datetime.now()),
            ],
            limit=1,
        )
        if token:
            # Direct SQL on purpose. This runs on every authenticated request,
            # and going through the ORM would fire tracking, recomputes and the
            # security suite's own write guards for a timestamp nobody audits.
            self.env.cr.execute(
                "UPDATE perfecthr_mobile_token SET last_used_at = "
                "(now() AT TIME ZONE 'UTC') WHERE id = %s",
                (token.id,),
            )
        return token

    @api.model
    def rotate(self, raw_refresh):
        """Exchange a refresh token for a new pair, revoking the old one.

        Rotation is not optional. A refresh token that stays valid after use can
        be replayed by whoever captured it, and the legitimate client would
        never notice, because its own token keeps working too.
        """
        if not raw_refresh:
            raise AccessDenied()
        token = self.sudo().search(
            [
                ("refresh_hash", "=", token_hash(raw_refresh)),
                ("active", "=", True),
                ("refresh_expires_at", ">", fields.Datetime.now()),
            ],
            limit=1,
        )
        if not token:
            raise AccessDenied()
        user = token.user_id
        if not user.active:
            # Archiving a user has to end their sessions. Without this a
            # departed employee's phone keeps working until the token expires.
            token.sudo().write({"active": False})
            raise AccessDenied()
        replacement, access, refresh = self.issue(
            user,
            device_label=token.device_label,
            source_ip=token.source_ip,
            # Carried forward, never re-derived. Both would otherwise fall back
            # to their defaults on the first refresh: the company would revert
            # to the user's default -- moving a session to a company it was
            # never granted -- and auth_mode would read 'advance' for a session
            # that only ever proved a password. The second is the dangerous
            # one, because anything that trusts an advanced session would begin
            # trusting this one an hour after it was issued.
            company=token.company_id,
            auth_mode=token.auth_mode,
            # A refresh cannot lift the enrolment restriction either. Enrolling
            # is what lifts it, and that path issues a fresh token.
            enrolment_required=token.enrolment_required,
        )
        token.sudo().write({"active": False})
        return replacement, access, refresh

    def revoke(self):
        """Deactivate rather than delete, so the session stays auditable."""
        return self.sudo().write({"active": False})

    @api.model
    def cron_purge_expired(self):
        """Delete rows whose refresh window has closed.

        Once the refresh token is dead the row can authorise nothing, so it is
        landfill rather than evidence. Rows still inside their window are left
        alone even when inactive, so a revocation stays visible for its life.
        """
        dead = self.sudo().search(
            [("refresh_expires_at", "<", fields.Datetime.now())]
        )
        count = len(dead)
        dead.unlink()
        if count:
            _logger.info("Purged %s expired mobile token(s)", count)
        return count
