# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Plaza Model role catalog.

Implements BRD FR-2.1 / FR-2.3 and PRD US-2.1.

The catalog is deliberately *bounded*: at most ``MAX_ACTIVE_ROLES`` roles may be
active at once, and go-live readiness requires at least ``MIN_ACTIVE_ROLES``.
See ``docs/DESIGN_NOTES_plaza_rbac.md`` for why the lower bound is a readiness
gate rather than a write-time constraint.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MIN_ACTIVE_ROLES = 10
MAX_ACTIVE_ROLES = 20

# Transaction classes used by the segregation-of-duties analysis (US-2.2).
# Kept as a module-level constant so the SoD checker and the access matrix
# cannot drift apart.
TRANSACTION_TYPES = [
    ("sale_order", "Sales Order"),
    ("purchase_order", "Purchase Order"),
    ("customer_invoice", "Customer Invoice"),
    ("vendor_bill", "Vendor Bill"),
    ("vendor_payment", "Vendor Payment"),
    ("journal_entry", "Journal Entry"),
    ("stock_move", "Stock Movement"),
    ("master_data", "Master Data (partners, products, pricing)"),
]

CAPABILITIES = [
    ("none", "No Capability"),
    ("create", "Create / Submit"),
    ("approve", "Approve / Confirm"),
    ("create_approve", "Create and Approve"),
]


class PlazaRole(models.Model):
    """A single standardised organisational role in the Plaza Model catalog."""

    _name = "role.plaza_model"
    _description = "Plaza Model Role"
    _inherit = ["mail.thread"]
    _order = "sequence, code"

    name = fields.Char(
        string="Role Name",
        required=True,
        tracking=True,
        help="Human-readable role title as used in the RACI register.",
    )
    code = fields.Char(
        string="Role Code",
        required=True,
        tracking=True,
        help="Short stable identifier for the role, e.g. ACC_LEAD. "
        "Referenced by reports and by the SoD checker.",
    )
    description = fields.Text(
        string="Description",
        required=True,
        tracking=True,
        help="Mandatory per PRD US-2.1: what this role is for and what it may do. "
        "A role without a description cannot be saved.",
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
        help="Display order in the catalog screen.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        tracking=True,
        help="Only active roles count towards the bounded catalog size "
        "(min %s / max %s)." % (MIN_ACTIVE_ROLES, MAX_ACTIVE_ROLES),
    )
    group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Backing Security Group",
        ondelete="restrict",
        tracking=True,
        help="The Odoo security group this role materialises as. Group "
        "assignments to a user that do not trace back to a Plaza role are "
        "treated as non-standard grants (PRD US-2.1, third criterion).",
    )
    access_line_ids = fields.One2many(
        comodel_name="role.plaza_model.access",
        inverse_name="role_id",
        string="Access Matrix",
        help="Module- and field-level access granted by this role. "
        "One line per Odoo model in scope for the role.",
    )
    access_line_count = fields.Integer(
        string="Matrix Lines",
        compute="_compute_access_line_count",
        store=True,
        help="Number of models covered by this role's access matrix.",
    )
    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Assigned Users",
        compute="_compute_user_ids",
        help="Users currently holding this role, derived from the backing group.",
    )
    user_count = fields.Integer(
        string="Assigned User Count",
        compute="_compute_user_ids",
        help="How many users currently hold this role.",
    )
    is_approval_tier = fields.Selection(
        selection=[
            ("none", "Not an Approval Tier"),
            ("tier_1", "Tier 1 - Department Head"),
            ("tier_2", "Tier 2 - Compliance / Legal Lead"),
            ("tier_3", "Tier 3 - CEO / Owner (Nuclear Key)"),
        ],
        string="Override Approval Tier",
        default="none",
        required=True,
        tracking=True,
        help="Whether holders of this role act as an approver in the "
        "multi-party override workflow (BRD FR-5). Consumed by "
        "sec_override_engine in Phase 2 and by the WebAuthn enrolment "
        "prompt in sec_webauthn_auth.",
    )
    requires_webauthn = fields.Boolean(
        string="Requires WebAuthn Enrolment",
        compute="_compute_requires_webauthn",
        store=True,
        help="True for any role that participates in an approval tier; such "
        "users must enrol an authenticator (BRD FR-6.1).",
    )
    catalog_version = fields.Char(
        string="Catalog Version",
        default="1.0",
        tracking=True,
        help="Version stamp for the access matrix, reviewed at each monthly "
        "forensic audit (BRD FR-2.3).",
    )

    _sql_constraints = [
        (
            "code_uniq",
            "unique(code)",
            "A Plaza role with this code already exists. Role codes must be unique.",
        ),
    ]

    @api.depends("access_line_ids")
    def _compute_access_line_count(self):
        for role in self:
            role.access_line_count = len(role.access_line_ids)

    @api.depends("is_approval_tier")
    def _compute_requires_webauthn(self):
        for role in self:
            role.requires_webauthn = role.is_approval_tier != "none"

    @api.depends("group_id")
    def _compute_user_ids(self):
        for role in self:
            users = role.group_id.sudo().user_ids if role.group_id else self.env["res.users"]
            role.user_ids = users
            role.user_count = len(users)

    # ------------------------------------------------------------------
    # Constraints - bounded catalog (PRD US-2.1, first acceptance criterion)
    # ------------------------------------------------------------------
    @api.constrains("active")
    def _check_catalog_upper_bound(self):
        """Reject any change that pushes the active catalog above the ceiling.

        The upper bound is enforced at write time because exceeding it is
        always a policy breach. The lower bound cannot be enforced the same way
        (the first role created would always violate it), so it is surfaced by
        ``check_catalog_readiness`` instead and blocks go-live rather than
        blocking a save.
        """
        active_count = self.sudo().search_count([("active", "=", True)])
        if active_count > MAX_ACTIVE_ROLES:
            raise ValidationError(
                _(
                    "The Plaza Model catalog is limited to %(maximum)s active roles "
                    "and this change would produce %(count)s. Archive an existing "
                    "role before adding another.",
                    maximum=MAX_ACTIVE_ROLES,
                    count=active_count,
                )
            )

    @api.constrains("description")
    def _check_description_present(self):
        for role in self:
            if not (role.description or "").strip():
                raise ValidationError(
                    _(
                        "Role '%(name)s' must have a description. Every Plaza role "
                        "carries a mandatory description (PRD US-2.1).",
                        name=role.name or role.code or "",
                    )
                )

    @api.constrains("is_approval_tier", "active")
    def _check_single_nuclear_key_tier(self):
        """Tier 3 is the CEO/Owner 'Nuclear Key' and must not be diluted."""
        tier_3 = self.sudo().search_count(
            [("is_approval_tier", "=", "tier_3"), ("active", "=", True)]
        )
        if tier_3 > 1:
            raise ValidationError(
                _(
                    "Only one active role may hold the Tier 3 (Nuclear Key) "
                    "approval authority; %(count)s were found.",
                    count=tier_3,
                )
            )

    # ------------------------------------------------------------------
    # Readiness / reporting helpers
    # ------------------------------------------------------------------
    @api.model
    def check_catalog_readiness(self):
        """Return a structured readiness verdict for the role catalog.

        Called by the go-live checklist and by the monthly forensic report
        (PRD US-8.1). Returns a dict rather than raising, so the caller decides
        whether a finding is fatal.
        """
        active = self.sudo().search([("active", "=", True)])
        findings = []
        if len(active) < MIN_ACTIVE_ROLES:
            findings.append(
                _(
                    "Catalog has %(count)s active roles; the Plaza Model requires "
                    "at least %(minimum)s before go-live.",
                    count=len(active),
                    minimum=MIN_ACTIVE_ROLES,
                )
            )
        if len(active) > MAX_ACTIVE_ROLES:
            findings.append(
                _(
                    "Catalog has %(count)s active roles; the ceiling is %(maximum)s.",
                    count=len(active),
                    maximum=MAX_ACTIVE_ROLES,
                )
            )
        without_group = active.filtered(lambda r: not r.group_id)
        if without_group:
            findings.append(
                _(
                    "These roles have no backing security group and therefore "
                    "enforce nothing: %(codes)s",
                    codes=", ".join(without_group.mapped("code")),
                )
            )
        without_matrix = active.filtered(lambda r: not r.access_line_ids)
        if without_matrix:
            findings.append(
                _(
                    "These roles have an empty access matrix: %(codes)s",
                    codes=", ".join(without_matrix.mapped("code")),
                )
            )
        for tier, label in (
            ("tier_1", "Tier 1 (Department Head)"),
            ("tier_2", "Tier 2 (Compliance / Legal Lead)"),
            ("tier_3", "Tier 3 (CEO / Owner)"),
        ):
            if not active.filtered(lambda r, t=tier: r.is_approval_tier == t):
                findings.append(
                    _(
                        "No active role is designated as %(label)s; the three-tier "
                        "override workflow cannot complete.",
                        label=label,
                    )
                )
        return {
            "active_role_count": len(active),
            "ready": not findings,
            "findings": findings,
        }

    def action_view_users(self):
        """Open the users currently holding this role."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Users holding %s", self.name),
            "res_model": "res.users",
            "view_mode": "list,form",
            "domain": [("id", "in", self.user_ids.ids)],
        }


class PlazaRoleAccess(models.Model):
    """One row of a role's module/field-level access matrix."""

    _name = "role.plaza_model.access"
    _description = "Plaza Model Role Access Matrix Line"
    _order = "role_id, model_name"

    role_id = fields.Many2one(
        comodel_name="role.plaza_model",
        string="Role",
        required=True,
        ondelete="cascade",
        index=True,
        help="The Plaza role this access line belongs to.",
    )
    model_name = fields.Char(
        string="Model",
        required=True,
        help="Technical model name the access applies to, e.g. sale.order. "
        "Stored as text so the matrix can be authored before the target "
        "module is installed.",
    )
    module_label = fields.Char(
        string="Module",
        required=True,
        help="Business-facing module label, e.g. Sales, Purchase, Accounting.",
    )
    perm_read = fields.Boolean(string="Read", default=True)
    perm_create = fields.Boolean(string="Create", default=False)
    perm_write = fields.Boolean(string="Write", default=False)
    perm_unlink = fields.Boolean(string="Delete", default=False)
    field_restrictions = fields.Char(
        string="Restricted Fields",
        help="Comma-separated list of fields on this model that the role may "
        "NOT read or write, enforced via groups= on the field definition. "
        "Leave empty for no field-level restriction.",
    )
    transaction_type = fields.Selection(
        selection=TRANSACTION_TYPES,
        string="Transaction Class",
        help="Which class of business transaction this line governs. Required "
        "for any line that carries a create or approve capability, because "
        "the segregation-of-duties checker groups by this value.",
    )
    capability = fields.Selection(
        selection=CAPABILITIES,
        string="Capability",
        default="none",
        required=True,
        help="Whether the role can originate the transaction, approve it, or "
        "both. 'Create and Approve' on a single role is a segregation-of-"
        "duties violation by definition and is rejected on save.",
    )
    notes = fields.Char(
        string="Notes",
        help="Rationale for this access line, shown during the monthly review.",
    )

    _sql_constraints = [
        (
            "role_model_uniq",
            "unique(role_id, model_name)",
            "Each model may appear only once in a role's access matrix.",
        ),
    ]

    @api.constrains("capability", "transaction_type")
    def _check_capability_has_transaction_type(self):
        for line in self:
            if line.capability != "none" and not line.transaction_type:
                raise ValidationError(
                    _(
                        "Access line '%(model)s' on role '%(role)s' declares a "
                        "capability but no transaction class. The segregation-of-"
                        "duties checker cannot evaluate it without one.",
                        model=line.model_name,
                        role=line.role_id.code,
                    )
                )

    @api.constrains("capability")
    def _check_no_intra_role_sod_breach(self):
        """A single role may never grant both create and approve.

        This is the strongest form of BRD FR-2.4: it makes the violation
        impossible to author in the first place, rather than only detectable
        afterwards by the cross-role SoD report.
        """
        for line in self:
            if line.capability == "create_approve":
                raise ValidationError(
                    _(
                        "Role '%(role)s' would grant both creation and approval "
                        "rights over %(txn)s in a single role. Split these into "
                        "two roles (BRD FR-2.4).",
                        role=line.role_id.code,
                        txn=dict(TRANSACTION_TYPES).get(line.transaction_type, ""),
                    )
                )
