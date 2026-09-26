# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Confirmation wizard for a stream lock toggle.

Exists so the mandatory reason is captured in the same interaction as the
decision, rather than being typed into a field somebody can leave blank. When
P2-2 lands, this wizard is where the WebAuthn ceremony is presented.
"""

from odoo import fields, models


class StreamLockWizard(models.TransientModel):
    _name = "sec.stream.lock.wizard"
    _description = "Stream Lock Toggle Confirmation"

    lock_id = fields.Many2one(
        comodel_name="sec.stream.lock",
        string="Stream",
        required=True,
        readonly=True,
    )
    target_state = fields.Selection(
        selection=[("lock", "Lock"), ("unlock", "Release")],
        string="Action",
        required=True,
        readonly=True,
    )
    reason = fields.Text(string="Reason", required=True)

    def action_apply(self):
        self.ensure_one()
        if self.target_state == "lock":
            self.lock_id.action_engage_lock(reason=self.reason)
        else:
            self.lock_id.action_release_lock(reason=self.reason)
        return {"type": "ir.actions.act_window_close"}
