# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Recognised policy exception categories (US-5.1).

US-5.1's second acceptance criterion: "Request is rejected client-side if it
does not map to a recognized policy exception category."

The point of a bounded list is not bureaucracy. Free-text reasons produce a
register that cannot be analysed: after a year nobody can answer "how many
overrides were price corrections?", which is exactly the question the monthly
forensic report exists to answer. A closed list also makes a novel reason
visible as a novel reason, rather than letting it hide inside a paragraph.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OverrideReasonCategory(models.Model):
    _name = "override.reason.category"
    _description = "Override Reason Category"
    _order = "sequence, name"

    name = fields.Char(string="Category", required=True, translate=True)
    code = fields.Char(string="Code", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(
        string="When to Use This",
        required=True,
        help="Guidance shown to requesters. A category nobody can interpret "
        "consistently produces statistics nobody can trust.",
    )
    requires_attachment = fields.Boolean(
        string="Always Requires Documentation",
        default=True,
        help="Independent of the Written/Oral rule: some categories always "
        "need supporting evidence regardless of how the instruction arrived.",
    )
    high_risk = fields.Boolean(
        string="High Risk",
        default=False,
        help="Flags the resulting override for closer scrutiny in the monthly "
        "report.",
    )

    _sql_constraints = [
        ("code_uniq", "unique(code)", "That category code already exists."),
    ]

    @api.constrains("active")
    def _check_at_least_one_active(self):
        if not self.sudo().search_count([("active", "=", True)]):
            raise ValidationError(
                _(
                    "At least one override reason category must stay active, "
                    "or no override could ever be requested and the only route "
                    "to correcting a frozen record would be closed."
                )
            )
