# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Segregation-of-duties analysis across Plaza Model role assignments.

Implements BRD FR-2.4 and PRD US-2.2.

The intra-role case (one role granting both create and approve) is blocked at
authoring time in ``plaza_role.py``. This module handles the case that cannot
be blocked at authoring time: a *combination* of individually-valid roles held
by one user that together permit both creating and approving the same class of
transaction.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .plaza_role import TRANSACTION_TYPES


class SodConflict(models.Model):
    """A detected create+approve conflict for one user on one transaction class.

    Persisted rather than transient so that the monthly forensic report
    (PRD US-8.1) can cite a stable record, and so that an accepted risk can be
    marked as such with a justification instead of reappearing every run.
    """

    _name = "plaza.sod.conflict"
    _description = "Segregation of Duties Conflict"
    _order = "detected_on desc, user_id"

    scan_id = fields.Many2one(
        comodel_name="plaza.sod.scan",
        string="Scan",
        required=True,
        ondelete="cascade",
        index=True,
        help="The scan run that produced this finding.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        ondelete="cascade",
        index=True,
        help="The user whose combined roles produce the conflict.",
    )
    transaction_type = fields.Selection(
        selection=TRANSACTION_TYPES,
        string="Transaction Class",
        required=True,
        help="The class of transaction the user can both create and approve.",
    )
    create_role_ids = fields.Many2many(
        comodel_name="role.plaza_model",
        relation="plaza_sod_conflict_create_role_rel",
        column1="conflict_id",
        column2="role_id",
        string="Roles Granting Create",
        help="Which of the user's roles supply the creation capability.",
    )
    approve_role_ids = fields.Many2many(
        comodel_name="role.plaza_model",
        relation="plaza_sod_conflict_approve_role_rel",
        column1="conflict_id",
        column2="role_id",
        string="Roles Granting Approve",
        help="Which of the user's roles supply the approval capability.",
    )
    detected_on = fields.Datetime(
        string="Detected On",
        required=True,
        default=fields.Datetime.now,
        help="UTC timestamp at which the conflict was detected.",
    )
    state = fields.Selection(
        selection=[
            ("open", "Open"),
            ("accepted", "Accepted Risk"),
            ("remediated", "Remediated"),
        ],
        string="Status",
        default="open",
        required=True,
        help="Open conflicts are reported to the CEO/Owner each month until "
        "they are remediated or formally accepted.",
    )
    acceptance_note = fields.Text(
        string="Acceptance / Remediation Note",
        help="Mandatory justification when a conflict is accepted as residual "
        "risk rather than remediated.",
    )
    accepted_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Accepted By",
        readonly=True,
        help="Who signed off on accepting this conflict as residual risk.",
    )

    def action_accept_risk(self):
        """Mark conflicts as accepted residual risk; a note is mandatory."""
        for conflict in self:
            if not (conflict.acceptance_note or "").strip():
                raise UserError(
                    _(
                        "Accepting a segregation-of-duties conflict requires a "
                        "written justification in the acceptance note."
                    )
                )
            conflict.write(
                {"state": "accepted", "accepted_by_id": self.env.user.id}
            )
        return True


class SodScan(models.Model):
    """One execution of the segregation-of-duties analysis."""

    _name = "plaza.sod.scan"
    _description = "Segregation of Duties Scan"
    _order = "run_on desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default=lambda self: _("SoD Scan"),
        help="Label for this scan run.",
    )
    run_on = fields.Datetime(
        string="Run On",
        required=True,
        default=fields.Datetime.now,
        help="UTC timestamp of the scan.",
    )
    run_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Run By",
        default=lambda self: self.env.user,
        help="Who initiated the scan.",
    )
    conflict_ids = fields.One2many(
        comodel_name="plaza.sod.conflict",
        inverse_name="scan_id",
        string="Conflicts",
        help="Findings produced by this scan.",
    )
    conflict_count = fields.Integer(
        string="Conflict Count",
        compute="_compute_conflict_count",
        store=True,
        help="Number of findings, used as the headline figure in the monthly report.",
    )
    users_scanned = fields.Integer(
        string="Users Scanned",
        readonly=True,
        help="How many active users were evaluated.",
    )
    clean = fields.Boolean(
        string="Clean",
        compute="_compute_conflict_count",
        store=True,
        help="True when the scan found no open conflicts.",
    )

    @api.depends("conflict_ids")
    def _compute_conflict_count(self):
        for scan in self:
            scan.conflict_count = len(scan.conflict_ids)
            scan.clean = not scan.conflict_ids

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    @api.model
    def _capability_map_for_user(self, user):
        """Return {transaction_type: {"create": roles, "approve": roles}}.

        A user's capabilities are the union of the access-matrix lines of every
        Plaza role whose backing group the user holds.
        """
        Role = self.env["role.plaza_model"].sudo()
        roles = Role.search(
            [("active", "=", True), ("group_id", "in", user.groups_id.ids)]
        )
        capabilities = {}
        for role in roles:
            for line in role.access_line_ids:
                if not line.transaction_type or line.capability == "none":
                    continue
                bucket = capabilities.setdefault(
                    line.transaction_type, {"create": Role, "approve": Role}
                )
                if line.capability in ("create", "create_approve"):
                    bucket["create"] |= role
                if line.capability in ("approve", "create_approve"):
                    bucket["approve"] |= role
        return capabilities

    @api.model
    def run_scan(self, name=None):
        """Execute a full SoD scan and return the resulting scan record."""
        Users = self.env["res.users"].sudo()
        users = Users.search([("active", "=", True), ("share", "=", False)])
        scan = self.create(
            {
                "name": name or _("SoD Scan %s", fields.Datetime.now()),
                "users_scanned": len(users),
            }
        )
        conflict_vals = []
        for user in users:
            for txn_type, caps in self._capability_map_for_user(user).items():
                if caps["create"] and caps["approve"]:
                    conflict_vals.append(
                        {
                            "scan_id": scan.id,
                            "user_id": user.id,
                            "transaction_type": txn_type,
                            "create_role_ids": [(6, 0, caps["create"].ids)],
                            "approve_role_ids": [(6, 0, caps["approve"].ids)],
                        }
                    )
        if conflict_vals:
            self.env["plaza.sod.conflict"].create(conflict_vals)
        return scan

    def action_run_scan(self):
        """Button target: run a scan and open its conflicts."""
        scan = self.run_scan()
        return {
            "type": "ir.actions.act_window",
            "name": _("Segregation of Duties Conflicts"),
            "res_model": "plaza.sod.conflict",
            "view_mode": "list,form",
            "domain": [("scan_id", "=", scan.id)],
            "context": {"search_default_group_by_transaction": 1},
        }

    @api.model
    def latest_scan_summary(self):
        """Summary consumed by the monthly forensic report (PRD US-8.1)."""
        scan = self.search([], order="run_on desc", limit=1)
        if not scan:
            return {
                "has_scan": False,
                "message": _("No segregation-of-duties scan has ever been run."),
            }
        open_conflicts = scan.conflict_ids.filtered(lambda c: c.state == "open")
        return {
            "has_scan": True,
            "scan_id": scan.id,
            "run_on": scan.run_on,
            "users_scanned": scan.users_scanned,
            "total_conflicts": len(scan.conflict_ids),
            "open_conflicts": len(open_conflicts),
            "clean": not open_conflicts,
        }
