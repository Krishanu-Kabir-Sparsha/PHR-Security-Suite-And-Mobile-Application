# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Written/Oral instruction classification and its documentation requirement.

Implements BRD FR-1.2 / FR-1.3 / FR-1.4 and PRD US-1.2 / US-1.3.

The mixin exists so that Phase 2's ``override.request`` (P2-5) inherits exactly
this logic instead of reimplementing it. If the two ever diverge, one of the two
paths into a frozen record will accept undocumented oral instructions, which is
the specific failure the BRD was written to prevent.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

INSTRUCTION_TYPES = [
    ("written", "Written Instruction"),
    ("oral", "Oral Instruction"),
]


class InstructionMixin(models.AbstractModel):
    """Adds a mandatory Written/Oral classification and its evidence rules."""

    _name = "sec.instruction.mixin"
    _description = "Written/Oral Instruction Mixin"
    _inherit = ["sec.anomaly.mixin"]

    instruction_type = fields.Selection(
        selection=INSTRUCTION_TYPES,
        string="Instruction Source",
        required=True,
        help="Whether the instruction behind this request arrived in writing "
        "or verbally. Mandatory: a request cannot be submitted without it "
        "(BRD FR-1.2).",
    )
    instructing_person_id = fields.Many2one(
        comodel_name="res.users",
        string="Instructing Supervisor",
        help="Who gave the instruction. Required for oral instructions, so "
        "that an undocumented phone call has a named originator.",
    )
    attachment_ids = fields.Many2many(
        comodel_name="ir.attachment",
        string="Supporting Documentation",
        help="Voice note, memo, email or scanned document evidencing the "
        "instruction. Mandatory when the instruction was oral (BRD FR-1.3).",
    )
    documentation_complete = fields.Boolean(
        string="Documentation Complete",
        compute="_compute_documentation_complete",
        store=True,
        help="Whether this request currently satisfies its documentation "
        "requirement. Drives the submit button and the server-side check.",
    )

    @api.depends("instruction_type", "attachment_ids", "instructing_person_id")
    def _compute_documentation_complete(self):
        for record in self:
            if record.instruction_type == "oral":
                record.documentation_complete = bool(
                    record.attachment_ids and record.instructing_person_id
                )
            elif record.instruction_type == "written":
                record.documentation_complete = bool(record.attachment_ids)
            else:
                record.documentation_complete = False

    def _check_documentation_or_flag(self):
        """Server-side gate. Raises, and raises an anomaly alert, if incomplete.

        Called on submission. The client-side check in the view is a
        convenience; this is the check that counts, because a client-side
        block is trivially bypassed by anyone using the JSON-RPC API directly
        — which is precisely the population the BRD is concerned about
        (PRD US-1.2: "blocked client-side and re-validated server-side").
        """
        for record in self:
            if record.documentation_complete:
                continue
            missing = []
            if not record.instruction_type:
                missing.append(_("instruction source (Written or Oral)"))
            if not record.attachment_ids:
                missing.append(_("supporting documentation"))
            if record.instruction_type == "oral" and not record.instructing_person_id:
                missing.append(_("the name of the instructing supervisor"))
            reason = _(
                "Submission blocked. Missing: %(missing)s.",
                missing=", ".join(missing),
            )
            # FR-1.4 / US-1.3: raise the alert BEFORE raising the error, so the
            # rollback of the failed write does not take the alert with it.
            # _raise_anomaly writes with sudo() in a way the caller cannot undo
            # from the UI, but a failed transaction would still roll it back —
            # hence the explicit new cursor below.
            record._raise_anomaly_out_of_band(reason=reason)
            raise ValidationError(
                _(
                    "%(reason)s\n\nThis blocked attempt has been recorded and "
                    "the System Monitor has been alerted.",
                    reason=reason,
                )
            )
        return True

    def _raise_anomaly_out_of_band(self, reason):
        """Write the alert on a separate cursor so a rollback cannot erase it.

        This is the whole point of FR-1.4: the record of a *blocked* attempt
        must survive the rollback of the transaction that was blocked. Writing
        it on the request's own cursor would mean every blocked attempt
        silently disappeared.
        """
        self.ensure_one()
        try:
            with self.pool.cursor() as new_cr:
                env = self.env(cr=new_cr)
                env["sec.anomaly.mixin"]._raise_anomaly(
                    alert_type="missing_documentation",
                    name=_("Edit request submitted without required documentation"),
                    reason=reason,
                    severity="high",
                    user=self.env.user,
                    source_ref="%s,%s" % (self._name, self.id),
                )
        except Exception:  # noqa: BLE001 - alerting must never mask the block
            _logger.exception(
                "Failed to raise out-of-band missing-documentation anomaly for %s,%s",
                self._name,
                self.id,
            )


class EditRequest(models.Model):
    """A request to make a manual edit, carrying its instruction provenance.

    In Phase 1 this stands alone, because there is nothing to unlock yet. From
    P2-5, ``override.request`` inherits ``sec.instruction.mixin`` and carries
    the same rules into the Nuclear Key workflow.
    """

    _name = "sec.edit.request"
    _description = "Manual Edit Request"
    _inherit = ["sec.instruction.mixin", "mail.thread"]
    _order = "create_date desc"

    name = fields.Char(
        string="Reference",
        required=True,
        default=lambda self: _("New Edit Request"),
        help="Short label for the request.",
    )
    requester_id = fields.Many2one(
        comodel_name="res.users",
        string="Requester",
        required=True,
        default=lambda self: self.env.user,
        help="Who is asking for the edit.",
    )
    target_model = fields.Char(
        string="Target Model",
        help="Technical model of the record to be edited. Free text in Phase 1; "
        "replaced by a real reference once the freeze engine lands in P1-4.",
    )
    target_record_id = fields.Integer(
        string="Target Record ID",
        help="Database ID of the record to be edited.",
    )
    justification = fields.Text(
        string="Justification",
        required=True,
        tracking=True,
        help="Why the edit is needed, in the requester's own words.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("rejected", "Rejected"),
            ("completed", "Completed"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        help="Draft requests are not yet subject to the documentation gate; "
        "submission is what triggers it.",
    )
    submitted_at = fields.Datetime(
        string="Submitted At",
        readonly=True,
        help="When the request passed the documentation gate.",
    )

    def action_submit(self):
        """Submit the request, enforcing the documentation requirement."""
        for request_record in self:
            if request_record.state != "draft":
                raise ValidationError(
                    _("Only a draft request can be submitted.")
                )
            request_record._check_documentation_or_flag()
            request_record.write(
                {"state": "submitted", "submitted_at": fields.Datetime.now()}
            )
        return True

    def action_reject(self):
        self.write({"state": "rejected"})
        return True
