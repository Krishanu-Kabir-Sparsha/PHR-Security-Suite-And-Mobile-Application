# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One line of a role's permissions: an area of Perfect HR, and a level.

Everything else on this record is derived. The previous form asked for a module,
a record type, four permission checkboxes, a transaction class and a capability
-- seven decisions, six of which are mechanical consequences of the first, and
all of which could be made to contradict one another. A line could claim it
approved while granting create; it could name a transaction class the record
type had nothing to do with.

Those fields still exist, because the segregation-of-duties scan, the monthly
review and the mobile API all read them. They are simply no longer typed in.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .plaza_role import CAPABILITIES, TRANSACTION_TYPES
from .plaza_areas import (
    ACCESS_LEVELS,
    AREA_SELECTION,
    AREAS_BY_KEY,
    LEVEL_APPROVE,
    LEVEL_CAPABILITY,
    LEVEL_NONE,
    LEVEL_PERMISSIONS,
    LEVEL_SUBMIT,
)

_logger = logging.getLogger(__name__)


class PlazaRoleAccess(models.Model):
    """What a role may do in one area of Perfect HR."""

    _name = "role.plaza_model.access"
    _description = "Role Permission"
    _order = "role_id, area"

    role_id = fields.Many2one(
        comodel_name="role.plaza_model",
        string="Role",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # ------------------------------------------------------------------
    # The two choices anybody makes
    # ------------------------------------------------------------------
    area = fields.Selection(
        selection=AREA_SELECTION,
        string="Area",
        # Deliberately not `required`, which would put NOT NULL on the column.
        # A line the upgrade could not convert would then fail the whole
        # upgrade, and the only remedies would be to delete somebody's reviewed
        # configuration or to guess at it. It is enforced below instead, on
        # create and write, so a blank one survives the upgrade, is obvious on
        # the form, and can be set by hand.
        help="The part of Perfect HR this permission covers.",
    )
    access_level = fields.Selection(
        selection=ACCESS_LEVELS,
        string="Can",
        default="view",
        help="What a holder of this role may do in this area.\n\n"
        "View only — can see it, cannot change it.\n"
        "Submit own — can raise and edit their own.\n"
        "Approve others' — can sign off other people's. A role that could both "
        "raise and approve the same thing would defeat the separation, so these "
        "two are deliberately different levels.",
    )
    notes = fields.Char(
        string="Why",
        help="Rationale for this permission, read during the monthly review.",
    )

    # ------------------------------------------------------------------
    # Derived. Kept because other things read them; never typed in.
    # ------------------------------------------------------------------
    # These are computed AND stored. Stored because the segregation-of-duties
    # scan searches on transaction_type and capability, and a non-stored compute
    # cannot be searched. Computed because the whole point of this rewrite is
    # that they can no longer disagree with the area and level above them.
    record_types = fields.Char(
        string="Record Types",
        compute="_compute_derived",
        store=True,
        help="Technical: the records this area covers. Shown only in "
        "developer mode; the Area is the user-facing name.",
    )
    module_label = fields.Char(
        string="Area Label",
        compute="_compute_derived",
        store=True,
    )
    perm_read = fields.Boolean(compute="_compute_derived", store=True)
    perm_create = fields.Boolean(compute="_compute_derived", store=True)
    perm_write = fields.Boolean(compute="_compute_derived", store=True)
    # Retained so existing rows and the mobile API's divergence report keep a
    # column to read, and permanently False. No role held delete, HR records are
    # evidence for payroll and attendance history -- archived, never removed --
    # and an option nobody needs is an option somebody grants by accident.
    perm_unlink = fields.Boolean(
        string="Delete",
        compute="_compute_derived",
        store=True,
        help="Always false. Records are archived rather than deleted.",
    )
    transaction_type = fields.Selection(
        selection=TRANSACTION_TYPES,
        string="Transaction Class",
        compute="_compute_derived",
        store=True,
        help="Technical: which class of transaction this area belongs to. "
        "Derived from the Area; the segregation-of-duties scan groups by it.",
    )
    capability = fields.Selection(
        selection=CAPABILITIES,
        string="Capability",
        compute="_compute_derived",
        store=True,
        help="Technical: derived from the level. 'Submit own' originates, "
        "'Approve others'' signs off.",
    )

    field_restrictions = fields.Char(
        string="Hidden Fields",
        help="Optional. Comma-separated fields in this area the role may not "
        "see, e.g. a margin figure on an order. Leave empty for none.",
    )

    _sql_constraints = [
        (
            "role_area_uniq",
            "unique(role_id, area)",
            "Each area may appear only once in a role's permissions. "
            "Change the existing line rather than adding a second.",
        ),
    ]

    # ------------------------------------------------------------------
    @api.depends("area", "access_level")
    def _compute_derived(self):
        for line in self:
            definition = AREAS_BY_KEY.get(line.area)
            level = line.access_level or LEVEL_NONE
            permissions = LEVEL_PERMISSIONS[level]

            line.record_types = ",".join(definition.records) if definition else False
            line.module_label = definition.label if definition else False
            line.perm_read = permissions["read"]
            line.perm_create = permissions["create"]
            line.perm_write = permissions["write"]
            line.perm_unlink = False

            # A self-service area raises no duty conflict: segregation of
            # duties governs acting on somebody else's records, not your own.
            # Without this, every member of staff who can request their own
            # leave would be paired against whoever approves leave, and the scan
            # would report a conflict for every line manager in the company --
            # a control that fires on everyone is one nobody reads.
            is_own_work = bool(definition and definition.self_service) and (
                level in (LEVEL_NONE, "view", LEVEL_SUBMIT)
            )
            transaction = definition.transaction if definition else False

            if not transaction or is_own_work:
                line.transaction_type = False
                line.capability = "none"
            else:
                line.transaction_type = transaction
                line.capability = LEVEL_CAPABILITY[level]

    @api.constrains("area", "access_level")
    def _check_approval_is_not_self_service(self):
        """Approving in a self-service area has to mean approving others'.

        Caught here because the level names promise it: "Approve others'" on an
        area where the only records are your own would be a level that does
        nothing, and a permission that silently does nothing is worse than one
        that is refused.
        """
        for line in self:
            definition = AREAS_BY_KEY.get(line.area)
            if not definition or line.access_level != LEVEL_APPROVE:
                continue
            if definition.self_service and not definition.transaction:
                raise ValidationError(
                    _(
                        "%(area)s has no approval step, so \"Approve others'\" "
                        "would grant nothing. Use \"Submit own\" instead.",
                        area=definition.label,
                    )
                )

    @api.constrains("access_level")
    def _check_no_intra_role_sod_breach(self):
        """One role may not both raise and approve the same class of work.

        Unreachable through the form -- the level is a single choice, so a line
        is one or the other -- but still enforced, because a role can also be
        written by import or RPC, and this is the rule the whole catalog rests
        on.
        """
        for line in self:
            if line.capability != "create_approve":
                continue
            raise ValidationError(
                _(
                    "A role may not both submit and approve the same work. "
                    "Split %(area)s across two roles.",
                    area=line.module_label or line.area,
                )
            )

    def name_get(self):
        """"Leave — Approve others'", so a line reads without opening it."""
        levels = dict(ACCESS_LEVELS)
        return [
            (
                line.id,
                "%s — %s"
                % (
                    line.module_label or line.area or "",
                    levels.get(line.access_level, ""),
                ),
            )
            for line in self
        ]

    @api.constrains("area", "access_level")
    def _check_area_and_level_present(self):
        """Enforced here rather than with `required=True` on the fields.

        `required` puts NOT NULL on the column, and a row the upgrade could not
        convert would then fail the whole upgrade — leaving only bad options:
        delete reviewed configuration, or guess at it. A blank line survives,
        shows as blank, and is refused the moment anybody edits it.
        """
        for line in self:
            if not line.area:
                raise ValidationError(
                    _("Choose the area of Perfect HR this permission covers.")
                )
            if not line.access_level:
                raise ValidationError(
                    _("Choose what this role can do in %(area)s.",
                      area=dict(AREA_SELECTION).get(line.area, line.area))
                )
