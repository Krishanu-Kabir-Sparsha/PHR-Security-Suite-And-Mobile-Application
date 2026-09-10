# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Unified Declaration / NDA+ versions and user sign-offs.

Implements BRD FR-1 and PRD US-1.1.

Scope boundary, stated explicitly because it matters legally: this module
captures *acceptance*. It does not contain, and must never contain,
declaration wording drafted by anyone other than qualified counsel. The
``body_html`` field is a configuration point that Legal fills in. BRD Section
11 and PRD Section 5.2 both place the drafting outside engineering scope,
and BRD Section 9 risk 4 flags the family-liability clause as likely
unenforceable and not to be deployed as drafted.
"""

import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class DeclarationVersion(models.Model):
    """One published version of the declaration text."""

    _name = "declaration.version"
    _description = "Unified Declaration Version"
    _order = "effective_date desc, id desc"

    name = fields.Char(
        string="Title",
        required=True,
        help="Human-readable title, e.g. 'Unified Declaration & NDA+ v1.0'.",
    )
    version = fields.Char(
        string="Version",
        required=True,
        help="Version label. Changing the published text requires a NEW "
        "version record, never an edit of an existing one, so that a "
        "sign-off can always be tied to the exact wording shown.",
    )
    body_html = fields.Html(
        string="Declaration Text",
        required=True,
        sanitize=False,
        help="The legally-approved declaration text, supplied by Legal Counsel. "
        "Engineering does not author this content.",
    )
    body_html_bn = fields.Html(
        string="Declaration Text (Bengali)",
        sanitize=False,
        help="Bengali rendering of the same declaration, per the bilingual "
        "requirement in PRD Section 9. Falls back to the English text when "
        "empty.",
    )
    text_hash = fields.Char(
        string="Text Hash (SHA-256)",
        compute="_compute_text_hash",
        store=True,
        readonly=True,
        help="Hash of the exact text. Stored on every sign-off so that a "
        "later dispute about what a user actually agreed to can be settled "
        "by comparison rather than by assertion.",
    )
    effective_date = fields.Date(
        string="Effective From",
        required=True,
        default=fields.Date.context_today,
        help="Date from which this version is the one users must accept.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("published", "Published"),
            ("superseded", "Superseded"),
        ],
        string="Status",
        default="draft",
        required=True,
        help="Exactly one version may be published at a time. Publishing a new "
        "version supersedes the previous one and forces every user to "
        "re-accept (PRD US-1.1, third criterion).",
    )
    is_material_update = fields.Boolean(
        string="Material Update",
        default=True,
        help="Material updates force re-acceptance by all users. Clear this "
        "only for corrections with no change of meaning, and expect to "
        "justify that judgement at audit.",
    )
    approved_by_legal = fields.Boolean(
        string="Approved by Legal Counsel",
        default=False,
        help="Must be set before publication. Engineering cannot self-certify "
        "the wording (BRD Section 11).",
    )
    legal_reviewer = fields.Char(
        string="Legal Reviewer",
        help="Name of the counsel who approved this wording, recorded for audit.",
    )
    signoff_ids = fields.One2many(
        comodel_name="declaration.signoff",
        inverse_name="version_id",
        string="Sign-offs",
        help="Acceptances recorded against this version.",
    )
    signoff_count = fields.Integer(
        string="Sign-offs",
        compute="_compute_signoff_count",
        help="How many users have accepted this version.",
    )

    _sql_constraints = [
        ("version_uniq", "unique(version)", "That declaration version already exists."),
    ]

    @api.depends("body_html", "body_html_bn", "version")
    def _compute_text_hash(self):
        for record in self:
            payload = "%s|%s|%s" % (
                record.version or "",
                record.body_html or "",
                record.body_html_bn or "",
            )
            record.text_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @api.depends("signoff_ids")
    def _compute_signoff_count(self):
        for record in self:
            record.signoff_count = len(record.signoff_ids)

    @api.constrains("state")
    def _check_single_published_version(self):
        published = self.sudo().search_count([("state", "=", "published")])
        if published > 1:
            raise ValidationError(
                _(
                    "Only one declaration version may be published at a time; "
                    "%(count)s were found. Supersede the current version first.",
                    count=published,
                )
            )

    def action_publish(self):
        """Publish this version and supersede any currently published one."""
        self.ensure_one()
        if not self.approved_by_legal:
            raise UserError(
                _(
                    "This declaration cannot be published until Legal Counsel has "
                    "approved the wording. Engineering does not self-certify "
                    "declaration text."
                )
            )
        if not (self.body_html or "").strip():
            raise UserError(_("The declaration text is empty."))
        current = self.sudo().search([("state", "=", "published")])
        current.write({"state": "superseded"})
        self.write({"state": "published"})
        _logger.warning(
            "Declaration version %s published by %s; %d user(s) must re-accept.",
            self.version,
            self.env.user.login,
            self.env["res.users"].sudo().search_count(
                [("active", "=", True), ("share", "=", False)]
            ),
        )
        return True

    @api.model
    def get_current_version(self):
        """Return the currently published version, or an empty recordset."""
        return self.sudo().search([("state", "=", "published")], limit=1)

    def write(self, vals):
        """Prevent silent edits to text that users have already accepted."""
        locked_fields = {"body_html", "body_html_bn", "version"}
        if locked_fields & set(vals):
            for record in self:
                if record.signoff_ids:
                    raise UserError(
                        _(
                            "Declaration version '%(version)s' has already been "
                            "accepted by %(count)s user(s) and its text can no "
                            "longer be changed. Create a new version instead — "
                            "otherwise a recorded sign-off would no longer match "
                            "what the user was shown.",
                            version=record.version,
                            count=len(record.signoff_ids),
                        )
                    )
        return super().write(vals)


class DeclarationSignoff(models.Model):
    """A single user's acceptance of a specific declaration version."""

    _name = "declaration.signoff"
    _description = "Declaration Sign-off"
    _order = "accepted_at desc"

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        ondelete="restrict",
        index=True,
        help="Who accepted. Restrict on delete: removing a user must not "
        "silently destroy evidence of their acknowledgment.",
    )
    version_id = fields.Many2one(
        comodel_name="declaration.version",
        string="Declaration Version",
        required=True,
        ondelete="restrict",
        index=True,
        help="Which version was accepted.",
    )
    declaration_version = fields.Char(
        string="Version Label",
        required=True,
        help="Denormalised version label, retained independently of the "
        "version record.",
    )
    text_hash = fields.Char(
        string="Accepted Text Hash",
        required=True,
        help="Hash of the exact text shown at the moment of acceptance.",
    )
    accepted_at = fields.Datetime(
        string="Accepted At (UTC)",
        required=True,
        default=fields.Datetime.now,
        help="Timestamp of acceptance.",
    )
    source_ip = fields.Char(
        string="Source IP",
        help="Client IP at acceptance.",
    )
    user_agent = fields.Char(
        string="User Agent",
        help="Browser user-agent string at acceptance.",
    )
    hash_matches_version = fields.Boolean(
        string="Hash Still Matches",
        compute="_compute_hash_matches",
        help="False would mean the version text changed after this acceptance, "
        "which the write guard is designed to make impossible. A False here "
        "is a serious finding, not a display issue.",
    )

    _sql_constraints = [
        (
            "user_version_uniq",
            "unique(user_id, version_id)",
            "This user has already signed off on this declaration version.",
        ),
    ]

    @api.depends("text_hash", "version_id.text_hash")
    def _compute_hash_matches(self):
        for record in self:
            record.hash_matches_version = (
                record.text_hash == record.version_id.text_hash
            )

    def write(self, vals):
        """Sign-offs are evidence: append-only."""
        raise UserError(
            _(
                "Declaration sign-off records cannot be modified. They are "
                "evidence of what a user accepted and when."
            )
        )

    def unlink(self):
        """Sign-offs are evidence: never deleted."""
        raise UserError(
            _("Declaration sign-off records cannot be deleted.")
        )
