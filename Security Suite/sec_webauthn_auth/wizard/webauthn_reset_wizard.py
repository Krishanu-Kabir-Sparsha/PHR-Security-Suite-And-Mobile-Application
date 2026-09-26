# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Clear a user's enrolment history so they can register a device again.

Revoking a credential archives it rather than deleting it, and that is right: a
revocation is evidence of what somebody once held. But ``_check_enrolment_
permitted`` reads *history*, not active credentials, so once every device on an
account has been revoked the holder lands on Route 3 -- break-glass recovery,
two other approvers -- instead of a fresh first enrolment.

That is exactly right for a key lost in the field. It is wrong for a replaced
handset, a test account, or a device retired on purpose, and without a way out
the only remedy is to convene two approvers for an event nobody considers an
incident.

A wizard rather than a bare button, for two reasons:

* **The reason is mandatory.** This deletes credentials, and the audit entry is
  worth nothing if it only says that it happened. Making the field required is
  the difference between a log somebody can act on and one they cannot.
* **The consequence is shown before it is chosen.** The form names how many
  credentials will go and what they were called, because "reset" reads like
  clearing a form until you find out it was not.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WebauthnResetWizard(models.TransientModel):
    _name = "sec.webauthn.reset.wizard"
    _description = "Reset Security Device Enrolment"

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        help="Whose enrolment history to clear. They will be able to register "
        "a first device again without break-glass recovery.",
    )
    reason = fields.Text(
        string="Reason",
        required=True,
        help="Why this enrolment is being cleared. Written to the audit record "
        "before anything is deleted, and read during the monthly review.",
    )
    credential_count = fields.Integer(
        string="Credentials To Remove",
        compute="_compute_preview",
        help="Includes revoked ones. Those are the reason the user is stuck: "
        "the enrolment gate reads history, not active devices.",
    )
    credential_summary = fields.Char(
        string="Devices",
        compute="_compute_preview",
    )

    @api.depends("user_id")
    def _compute_preview(self):
        Credential = self.env["sec.webauthn.credential"].sudo()
        for wizard in self:
            if not wizard.user_id:
                wizard.credential_count = 0
                wizard.credential_summary = False
                continue
            # active_test=False on purpose: the archived ones are precisely
            # what keeps the user on the break-glass route, so a preview that
            # hid them would understate what this does and why it is needed.
            history = Credential.with_context(active_test=False).search(
                [("user_id", "=", wizard.user_id.id)]
            )
            wizard.credential_count = len(history)
            wizard.credential_summary = (
                ", ".join(
                    "%s%s"
                    % (c.device_label or _("(unnamed)"),
                       "" if c.active else _(" [revoked]"))
                    for c in history
                )
                or False
            )

    def action_reset(self):
        """Delete the history, after the audit record is written."""
        self.ensure_one()
        if not self.credential_count:
            raise UserError(
                _(
                    "%(user)s has no enrolment history, so there is nothing to "
                    "clear. They can already enrol a first device.",
                    user=self.user_id.display_name,
                )
            )

        removed = self.env["sec.webauthn.credential"].reset_enrolment_for(
            self.user_id, reason=self.reason
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "warning",
                "title": _("Enrolment cleared"),
                "message": _(
                    "%(count)s credential(s) removed for %(user)s. They can now "
                    "register a first device again.",
                    count=removed,
                    user=self.user_id.display_name,
                ),
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
