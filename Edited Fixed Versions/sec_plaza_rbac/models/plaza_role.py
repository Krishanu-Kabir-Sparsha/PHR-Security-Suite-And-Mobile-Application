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
from odoo.exceptions import AccessError, UserError, ValidationError

from .plaza_areas import ACCESS_LEVELS, AREAS_BY_KEY

_logger = logging.getLogger(__name__)


class _NoArea:
    """Stand-in for a permission line whose area is not set.

    Only reachable on a line the upgrade could not convert, which is kept
    deliberately rather than deleted. Treated as not self-service so such a
    role is reported as granting nothing, which is true and is what should
    draw somebody's attention to it.
    """

    self_service = False


_NO_AREA = _NoArea()

MIN_ACTIVE_ROLES = 10
# Raised from 20 to 25 when the catalog was extended to cover human resources.
#
# PRD US-2.1 specified 20, and that figure was chosen while the catalog governed
# one domain: sales, purchasing and finance. Adding HR brought a second domain
# and six more roles, taking the shipped catalog to 21 -- so the ceiling was
# rejecting a legitimate expansion of scope rather than the role proliferation
# it exists to prevent.
#
# The bound is kept, and kept tight, because the failure it guards against is
# real: a catalog that grows a role per person stops being a control and becomes
# an inventory. 25 accommodates finance plus HR with four slots of headroom,
# which still forces a deliberate decision -- and an archive -- rather than
# unbounded growth.
#
# **This supersedes the figure in PRD US-2.1 and needs product sign-off.** If it
# is rejected, the alternative is to archive an unused finance role rather than
# to trim the HR set, which is sized by the duty separations it has to express.
MAX_ACTIVE_ROLES = 25

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
    # --- Human resources -------------------------------------------------
    # Added so HR is governed by the same catalog, the same segregation-of-
    # duties checker and the same monthly review as finance. Without these the
    # HR roles could carry no capability at all, because
    # `_check_capability_has_transaction_type` requires a transaction class on
    # any line that creates or approves -- so HR would have been present in the
    # catalog but invisible to every control built on top of it.
    #
    # The split matters for the same reason it does in finance: the person who
    # requests leave must not be the person who approves it, and the person who
    # prepares payroll must not be the person who posts it.
    ("leave_request", "Leave Request"),
    ("attendance_record", "Attendance Record"),
    ("payroll_run", "Payroll Run"),
    ("employee_master", "Employee Master Data"),
    ("recruitment", "Recruitment Decision"),
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
        inverse="_inverse_user_ids",
        readonly=False,
        help="Users currently holding this role. Editable here, but the "
        "backing security group remains the single source of truth: adding "
        "or removing someone writes their group membership, it does not "
        "record anything separately on the role.",
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

    granted_summary = fields.Char(
        string="Gives Access To",
        compute="_compute_granted_access",
        help="What a holder of this role can actually reach in Perfect HR. "
        "Derived from the Permissions tab; there is nothing to configure here. "
        "Shown so that what a role confers is visible without having to read "
        "it out of the permission lines one by one.",
    )
    grants_nothing = fields.Boolean(
        string="Declares Access It Does Not Grant",
        compute="_compute_grants_nothing",
        help="True when the role has permissions set but none of them confer "
        "any access. Surfaced on the form because a role that looks "
        "configured and grants nothing is the hardest kind of mistake to "
        "notice from the outside.",
    )

    _sql_constraints = [
        (
            "code_uniq",
            "unique(code)",
            "A Plaza role with this code already exists. Role codes must be unique.",
        ),
    ]

    def _apply_permission_grants(self):
        """Give the backing group exactly the access the permission lines imply.

        This is what makes the Permissions tab real. Each line names an area and
        a level; the area knows what access each level confers; this writes the
        union of that onto the role's backing group, which is what Perfect HR
        consults when it decides whether an operation is allowed.

        Called on create and on every save, so there is no separate step to
        forget. Before this existed the two had to be configured independently,
        and a role could describe access nobody actually had.

        **Only ever adds.** Access set deliberately outside the catalog --
        during an incident, or for something the areas do not model yet --
        survives. Quietly revoking access because a permission line was removed
        would break somebody mid-task with no trace of why; removals are made on
        purpose, by a person, in Settings.
        """
        for role in self:
            wanted_names = []
            for line in role.access_line_ids:
                definition = AREAS_BY_KEY.get(line.area)
                if not definition or not line.access_level:
                    continue
                wanted_names.extend(definition.access_for(line.access_level))

            wanted = self.env["res.groups"]
            for name in dict.fromkeys(wanted_names):
                found = self.env.ref(name, raise_if_not_found=False)
                if found:
                    wanted |= found
                else:
                    # Routine: this module governs finance, procurement and HR,
                    # and a deployment need not run all three.
                    _logger.debug("Access %s not present; skipped", name)

            group = role.group_id or role._ensure_backing_group()
            missing = wanted - group.sudo().implied_ids
            if not missing:
                continue

            group.sudo().write(
                {"implied_ids": [fields.Command.link(gid) for gid in missing.ids]}
            )
            role.message_post(
                body=_(
                    "Permissions applied. This role now also gives: %(names)s",
                    names=", ".join(missing.mapped("name")),
                )
            )
            _logger.info(
                "Role %s now grants %s", role.code, ", ".join(missing.mapped("name"))
            )

    @api.model
    def _apply_all_permission_grants(self):
        """Re-apply every role's grants. Called from the data file on upgrade."""
        self.search([]).sudo()._apply_permission_grants()

    @api.depends("access_line_ids.area", "access_line_ids.access_level")
    def _compute_granted_access(self):
        levels = dict(ACCESS_LEVELS)
        for role in self:
            parts = []
            for line in role.access_line_ids:
                definition = AREAS_BY_KEY.get(line.area)
                if not definition or line.access_level in (None, False, "none"):
                    continue
                parts.append(
                    "%s (%s)" % (definition.label, levels.get(line.access_level, ""))
                )
            role.granted_summary = ", ".join(parts)

    @api.depends("access_line_ids.area", "access_line_ids.access_level", "group_id")
    def _compute_grants_nothing(self):
        for role in self:
            has_lines = any(
                line.access_level not in (None, False, "none")
                for line in role.access_line_ids
            )
            confers = bool(role.group_id and role.group_id.sudo().implied_ids)
            # Self-service areas legitimately confer nothing extra: Perfect HR's
            # baseline access already covers acting on your own records. A role
            # made only of those is complete, not broken.
            only_self_service = all(
                (AREAS_BY_KEY.get(line.area) or _NO_AREA).self_service
                for line in role.access_line_ids
                if line.access_level not in (None, False, "none")
            )
            role.grants_nothing = bool(
                has_lines and not confers and not only_self_service
            )

    @api.depends("access_line_ids")
    def _compute_access_line_count(self):
        for role in self:
            role.access_line_count = len(role.access_line_ids)

    @api.depends("is_approval_tier")
    def _compute_requires_webauthn(self):
        for role in self:
            role.requires_webauthn = role.is_approval_tier != "none"

    def _inverse_user_ids(self):
        """Apply membership changes by writing res.users, never res.groups.

        This is the whole reason the field has an inverse rather than being
        left to Odoo's default behaviour. The non-standard-grant guard that is
        the point of this module lives in ``ResUsers.write()`` and only fires
        when ``groups_id`` appears in the values. Writing the same relation
        from the group side -- ``group.users`` -- updates the identical table
        without ever calling it, so a role page that assigned users that way
        would quietly become the one route into a security group that skips
        the check, the audit stamp and the chatter entry.

        So: compute the delta, then write it through the users.
        """
        for role in self:
            # Capture the requested membership BEFORE anything else touches the
            # record. user_ids is computed from group_id, so creating a group
            # below marks it for recomputation and would throw away the very
            # assignment being made -- the list would silently save empty.
            target = role.user_ids

            # A role created before this behaviour existed, or one whose group
            # was deleted, has nowhere to put members. Make one rather than
            # refusing: the group is what "assigning a user" means here, so
            # demanding it up front would be asking the author to satisfy a
            # technical precondition they did not create.
            group = role.group_id or role._ensure_backing_group()

            # Read the membership as sudo (a catalog administrator need not be
            # able to read res.groups.users), then re-browse in the caller's
            # environment. Recordset arithmetic keeps the environment of its
            # left operand, so leaving `current` in sudo would have handed
            # `to_remove` a superuser recordset and removals would have written
            # as root -- skipping exactly the access checks that additions get.
            current = self.env["res.users"].browse(group.sudo().users.ids)
            to_add = target - current
            to_remove = current - target
            if not to_add and not to_remove:
                continue

            # Changing someone's groups is user administration. Deliberately
            # NOT sudo'd: if the catalog administrator may not administer
            # users, they may not grant this role either. Checked up front so
            # the refusal explains itself instead of surfacing as a bare
            # AccessError from somewhere inside the write.
            try:
                (to_add | to_remove).check_access("write")
            except AccessError as exc:
                raise UserError(
                    _(
                        "Assigning users to a role changes their security "
                        "groups, which requires permission to administer "
                        "users. Ask an administrator to make the change, or "
                        "add the members from Settings."
                    )
                ) from exc

            if to_add:
                to_add.write({"groups_id": [(4, group.id)]})
            if to_remove:
                to_remove.write({"groups_id": [(3, group.id)]})

    def _ensure_backing_group(self):
        """Give the role a security group if it has none, and return it.

        Called automatically -- when a role is created, and again if someone
        assigns a user to a role that still has no group. There is no button:
        the group is an implementation detail of "a role someone can hold", and
        making the author click something to create it only moved a technical
        requirement into the workflow.

        The group is created empty. It grants nothing until access rights are
        attached to it, so this is not a privilege escalation, and it is sudo'd
        so a catalog administrator can finish their own work without rights
        over res.groups. Putting *users* into it is a different matter and is
        deliberately not sudo'd -- see _inverse_user_ids.
        """
        self.ensure_one()
        if self.group_id:
            return self.group_id
        category = self.env.ref(
            "sec_plaza_rbac.module_category_security_suite", raise_if_not_found=False
        )
        group = (
            self.env["res.groups"]
            .sudo()
            .create(
                {
                    "name": "Plaza / %s" % (self.name or self.code),
                    "category_id": category.id if category else False,
                    "comment": _(
                        "Backing group for Plaza Model role %s. Created from "
                        "the role catalog; membership of this group is what "
                        "confers the role.",
                        self.code or self.name,
                    ),
                }
            )
        )
        self.group_id = group.id
        _logger.info(
            "Backing group %s created for Plaza role %s by %s",
            group.name,
            self.code or self.name,
            self.env.user.login,
        )
        return group

    @api.model_create_multi
    def create(self, vals_list):
        """Every new role gets a backing group, so the field is never empty.

        Done after super() rather than by injecting into vals, because the
        group's name comes from the role's own name and code.
        """
        roles = super().create(vals_list)
        for role in roles:
            role._ensure_backing_group()
        # Apply immediately, so a role created with permissions already on it
        # confers them without a second save. There is no separate "apply" step
        # anywhere, by design: the gap between describing a role and granting it
        # is exactly where the catalog used to drift from the system.
        roles._apply_permission_grants()
        return roles

    def write(self, vals):
        result = super().write(vals)
        # Only when the permissions actually changed. Renaming a role or editing
        # its description should not touch anybody's access, and re-applying on
        # every save would put a chatter entry on the role each time.
        if "access_line_ids" in vals:
            self._apply_permission_grants()
        return result

    # Depends on the group's membership, not just on which group is linked.
    # With only "group_id" here, adding or removing a user from the backing
    # group left user_count stale until something else invalidated the cache --
    # a role page quietly showing the wrong number of holders.
    @api.depends("group_id", "group_id.users")
    def _compute_user_ids(self):
        for role in self:
            # res.groups exposes its members as "users" in Odoo 18. The name
            # "user_ids" belongs to Odoo 19's res.groups refactor; on 18 it is
            # only on change.password.wizard, so this raised AttributeError as
            # soon as anyone opened the Plaza Roles list.
            users = role.group_id.sudo().users if role.group_id else self.env["res.users"]
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
