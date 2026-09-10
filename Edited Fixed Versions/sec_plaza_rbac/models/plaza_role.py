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
        return roles

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
    # ------------------------------------------------------------------
    # Module / model selection
    # ------------------------------------------------------------------
    # module_id and model_id are the fields people actually use; module_label
    # and model_name below remain the stored truth. Keeping both is deliberate:
    # the unique SQL constraint, _order, the seeded catalog in
    # data/plaza_role_data.xml and the SoD error messages all read model_name,
    # and a role catalog that could only ever name installed models would lose
    # the ability to describe a role before its module is deployed.
    module_id = fields.Many2one(
        comodel_name="ir.module.module",
        string="Module",
        # Deliberately NOT restrict. Uninstalling a module deletes its ir.model
        # rows, and a restrict here would make the RBAC catalog able to veto an
        # uninstall -- a surprising failure a long way from its cause. On
        # set null the picker empties and module_label / model_name survive,
        # which is the graceful degradation the original text fields were
        # chosen for in the first place.
        ondelete="set null",
        domain=[("state", "=", "installed")],
        help="Installed module this access line belongs to. Choosing one "
        "narrows the Model list to that module's models.",
    )
    model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Model",
        ondelete="set null",  # see the note on module_id above
        compute="_compute_model_id",
        store=True,
        readonly=False,
        help="Model the access applies to, limited to the chosen module.",
    )
    allowed_model_ids = fields.Many2many(
        comodel_name="ir.model",
        string="Selectable Models",
        compute="_compute_allowed_model_ids",
        help="Technical helper: the models the chosen module defines or "
        "extends. Drives the domain on Model; not shown to users.",
    )
    # These two stay plain stored columns, NOT computed from the pickers.
    # model_id already declares @api.depends("model_name"); making model_name
    # compute from model_id in turn would be a declared dependency cycle, which
    # Odoo rejects when it builds the registry. They are kept in step through
    # onchange (for the UI) and create/write (for imports and RPC) instead --
    # a runtime relationship, which the dependency graph never sees.
    model_name = fields.Char(
        string="Technical Model",
        required=True,
        help="Technical model name the access applies to, e.g. sale.order. "
        "Stored as text so the matrix can be authored before the target "
        "module is installed.",
    )
    module_label = fields.Char(
        string="Module Label",
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

    # ------------------------------------------------------------------
    # Resolving a module to its models
    # ------------------------------------------------------------------
    @api.model
    def _models_for_modules(self, module_names):
        """Map each module name to the ir.model records it may offer.

        Odoo records the link as external IDs: every module that defines *or
        extends* a model gets an ``ir.model.data`` row pointing at it. That is
        exactly what ``ir.model.modules`` displays as "In Apps", and it is the
        behaviour we want here -- ``sale`` should be able to grant access to
        ``res.partner``, which it extends rather than defines. The seeded
        catalog already assumes this (its Sales roles cover res.partner).

        ``ir.model.modules`` itself is computed and not stored, so it cannot be
        used in a domain; this reads the same source directly.

        Excluded, per the agreed scope:

        * transient models -- wizards are a UI mechanism, not a thing a role
          holds standing rights over;
        * abstract models -- mixins have no table, so an ACL on one is
          meaningless and Odoo would refuse it anyway.
        """
        if not module_names:
            return {}
        data = (
            self.env["ir.model.data"]
            .sudo()
            .search(
                [
                    ("model", "=", "ir.model"),
                    ("module", "in", list(module_names)),
                ]
            )
        )
        by_module = {name: [] for name in module_names}
        for row in data:
            by_module.setdefault(row.module, []).append(row.res_id)

        IrModel = self.env["ir.model"].sudo()
        result = {}
        for name, res_ids in by_module.items():
            records = IrModel.browse(res_ids).exists()
            keep = IrModel.browse()
            for record in records:
                target = self.env.get(record.model)
                # Absent from the registry: the xmlid outlived the model.
                if target is None or target._abstract or target._transient:
                    continue
                keep |= record
            result[name] = keep
        return result

    @api.depends("module_id")
    def _compute_allowed_model_ids(self):
        names = {line.module_id.name for line in self if line.module_id}
        by_module = self._models_for_modules(names)
        empty = self.env["ir.model"]
        for line in self:
            line.allowed_model_ids = by_module.get(line.module_id.name, empty)

    @api.depends("model_name")
    def _compute_model_id(self):
        """Backfill the picker from the stored technical name.

        Runs for rows authored before this field existed -- the seeded catalog
        and anything created from XML data, which set model_name directly. It
        is store=True + readonly=False, so a value chosen by hand is kept; only
        a change to model_name re-derives it.
        """
        for line in self:
            if not line.model_name:
                line.model_id = False
                continue
            if line.model_id and line.model_id.model == line.model_name:
                continue
            line.model_id = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", line.model_name)], limit=1)
            )

    # ------------------------------------------------------------------
    # Keeping the pickers and the stored text in step
    # ------------------------------------------------------------------
    # Deliberately NOT a backfill for module_id. Matching the seeded labels
    # against installed modules is unreliable and, worse, confidently wrong:
    # on this database "Sales" resolves to sale_management rather than sale,
    # while "Accounting", "Inventory" and "Settings" match nothing at all.
    # Guessing would either stamp the wrong module on a role or trip
    # _check_model_belongs_to_module during the upgrade and abort it. Existing
    # rows therefore keep an empty picker and their module_label text; someone
    # sets the module the next time they edit the line, which is a visible
    # to-do rather than a silent wrong answer.
    @staticmethod
    def _sync_from_pickers(vals, env):
        """Fill module_label / model_name from the pickers in ``vals``.

        Applied on create and write so that a line written over RPC or by an
        import behaves like one edited in the form, rather than failing the
        required-field check on columns the caller never heard of.
        """
        if vals.get("model_id") and not vals.get("model_name"):
            model = env["ir.model"].sudo().browse(vals["model_id"]).exists()
            if model:
                vals["model_name"] = model.model
        if vals.get("module_id") and not vals.get("module_label"):
            module = env["ir.module.module"].sudo().browse(vals["module_id"]).exists()
            if module:
                vals["module_label"] = module.shortdesc or module.name
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(
            [self._sync_from_pickers(dict(vals), self.env) for vals in vals_list]
        )

    def write(self, vals):
        return super().write(self._sync_from_pickers(dict(vals), self.env))

    @api.onchange("model_id")
    def _onchange_model_id(self):
        """Mirror the chosen model into the stored technical name."""
        if self.model_id:
            self.model_name = self.model_id.model

    @api.onchange("module_id")
    def _onchange_module_id(self):
        """Mirror the label, and drop a model outside the new module."""
        if self.module_id:
            self.module_label = self.module_id.shortdesc or self.module_id.name
        if self.model_id and self.model_id not in self.allowed_model_ids:
            self.model_id = False
            self.model_name = False

    @api.constrains("module_id", "model_id")
    def _check_model_belongs_to_module(self):
        """The pair must be coherent however it was written.

        The view domain covers the UI; this covers imports, XML data and
        anything written over RPC, where a mismatched pair would otherwise be
        accepted and then read as authoritative during the monthly review.
        """
        for line in self:
            if not line.module_id or not line.model_id:
                continue
            allowed = line._models_for_modules({line.module_id.name}).get(
                line.module_id.name
            )
            if allowed is not None and line.model_id not in allowed:
                raise ValidationError(
                    _(
                        "Model '%(model)s' is not part of module '%(module)s'. "
                        "Pick a model the module defines or extends, or change "
                        "the module.",
                        model=line.model_id.model,
                        module=line.module_id.shortdesc or line.module_id.name,
                    )
                )

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
