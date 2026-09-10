# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Executing an approved override (P2-8).

Closes the loop described in PRD Section 8.1: the system unlocks the specific
record for a single, logged edit, and the record re-freezes immediately.

Three things are worth understanding about how this is done.

**The approved change is structured, not prose.** ``proposed_changes`` is the
human explanation approvers read. ``change_ids`` is the machine-readable list of
field/value pairs that execution actually applies. Approving free text and then
letting the requester type whatever they liked into the record would mean the
three signatures attest to something nobody checked. The unlock ticket is scoped
to exactly the fields named in ``change_ids``, so an approval obtained for a
price correction cannot be spent changing the counterparty.

**Re-freezing is not a state change.** The record never leaves its frozen state;
what exists briefly is a single-use ticket scoped to one record and one field
set. Spending it is what re-freezes. There is no window during which the record
is "unlocked" in any general sense, and nothing to forget to switch back.

**Both enforcement layers have to be told, separately.** The ORM check consults
the ticket. The PL/pgSQL trigger from P1-5 knows nothing about tickets, so the
transaction also sets ``sec.freeze_unlock`` with ``SET LOCAL`` — scoped to this
transaction and reset immediately afterwards. Missing either one produces a
puzzling half-failure, which is exactly the kind of thing that gets "fixed" by
disabling a control.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

UNLOCK_GUC = "sec.freeze_unlock"

# Field types execution can set from a text value. Anything else must be
# handled by a human, because guessing at the conversion is how a "correction"
# quietly becomes a different correction.
CONVERTIBLE_TYPES = {
    "char", "text", "html", "integer", "float", "monetary",
    "boolean", "date", "datetime", "selection", "many2one",
}


class OverrideChange(models.Model):
    """One field to be changed on the target record."""

    _name = "override.change"
    _description = "Override Proposed Field Change"
    _order = "field_name"

    request_id = fields.Many2one(
        comodel_name="override.request",
        string="Override Request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    field_name = fields.Char(
        string="Field",
        required=True,
        help="Technical field name on the target model.",
    )
    field_label = fields.Char(string="Field Label", readonly=True)
    old_value = fields.Char(
        string="Current Value",
        readonly=True,
        help="Captured when the request is submitted, so approvers see what is "
        "being changed from, and so a later divergence is detectable.",
    )
    new_value = fields.Char(
        string="New Value",
        required=True,
        help="Value to set. For a many2one, give the database id.",
    )

    _sql_constraints = [
        (
            "field_uniq",
            "unique(request_id, field_name)",
            "That field is already listed on this request.",
        ),
    ]

    @api.constrains("field_name")
    def _check_field_is_valid_and_protected(self):
        for change in self:
            request_record = change.request_id
            model = self.env.get(request_record.res_model)
            if model is None:
                raise ValidationError(
                    _("Model %s is not installed.", request_record.res_model)
                )
            field = model._fields.get(change.field_name)
            if field is None:
                raise ValidationError(
                    _(
                        "%(field)s is not a field on %(model)s.",
                        field=change.field_name,
                        model=request_record.res_model,
                    )
                )
            if field.type not in CONVERTIBLE_TYPES:
                raise ValidationError(
                    _(
                        "Changes to %(type)s fields cannot be applied "
                        "automatically. %(field)s must be corrected another "
                        "way; guessing at the conversion risks applying a "
                        "different change from the one approved.",
                        type=field.type,
                        field=change.field_name,
                    )
                )
            if not field.store:
                raise ValidationError(
                    _("%s is not stored and cannot be written.", change.field_name)
                )

    def _check_parent_is_draft(self, action):
        """P4-4 finding: these values were editable after approval.

        ``override.change`` carried full create/write/unlink rights for every
        user and no guard of its own. The parent request locks its justification
        once under review, but the *actual field values the approvals authorise*
        sat in a child model that anyone could rewrite between the CEO/Owner's
        signature and execution. Three cryptographic approvals would then have
        attested to numbers nobody approved.
        """
        for change in self:
            state = change.request_id.state
            if state != "draft":
                change.request_id._raise_anomaly(
                    alert_type="incomplete_override",
                    name=_("Attempt to alter an approved override's changes"),
                    reason=_(
                        "%(user)s attempted to %(action)s field change "
                        "'%(field)s' on override %(ref)s, which is in state "
                        "'%(state)s'. The approvals attest to the values as "
                        "submitted; altering them afterwards would make those "
                        "signatures meaningless.",
                        user=self.env.user.login,
                        action=action,
                        field=change.field_name,
                        ref=change.request_id.name,
                        state=state,
                    ),
                    severity="critical",
                    record=change.request_id,
                )
                raise UserError(
                    _(
                        "This override has already been submitted, so the "
                        "changes it applies can no longer be altered. Cancel it "
                        "and raise a new request."
                    )
                )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_parent_is_draft(_("add"))
        return records

    def write(self, vals):
        if not self.env.context.get("override_capture_values"):
            self._check_parent_is_draft(_("modify"))
        return super().write(vals)

    def unlink(self):
        self._check_parent_is_draft(_("remove"))
        return super().unlink()

    def _typed_value(self):
        """Convert the stored text into the field's python value."""
        self.ensure_one()
        model = self.env[self.request_id.res_model]
        field = model._fields[self.field_name]
        raw = self.new_value
        try:
            if field.type in ("char", "text", "html", "selection"):
                return raw
            if field.type == "integer":
                return int(raw)
            if field.type in ("float", "monetary"):
                return float(raw)
            if field.type == "boolean":
                return str(raw).strip().lower() in ("1", "true", "yes")
            if field.type == "many2one":
                return int(raw)
            if field.type in ("date", "datetime"):
                return raw
        except (TypeError, ValueError) as exc:
            raise UserError(
                _(
                    "'%(value)s' is not a valid %(type)s for %(field)s.",
                    value=raw,
                    type=field.type,
                    field=self.field_name,
                )
            ) from exc
        raise UserError(
            _("Cannot convert a value for field type %s.", field.type)
        )


class OverrideRequestExecution(models.Model):
    _inherit = "override.request"

    change_ids = fields.One2many(
        comodel_name="override.change",
        inverse_name="request_id",
        string="Field Changes",
        help="The exact changes the approvals authorise. Execution applies "
        "these and nothing else.",
    )
    unlock_ticket_id = fields.Many2one(
        comodel_name="sec.freeze.unlock.ticket",
        string="Unlock Ticket",
        readonly=True,
        help="The single-use ticket spent to apply the change.",
    )
    executed_by_id = fields.Many2one(
        comodel_name="res.users", string="Executed By", readonly=True
    )

    def _capture_current_values(self):
        """Record what each field says now, so approvers see the delta."""
        self.ensure_one()
        record = self._target_record()
        if not record:
            return
        for change in self.change_ids:
            value = record[change.field_name]
            if hasattr(value, "id"):
                value = value.id
            change.sudo().with_context(override_capture_values=True).write({
                "old_value": str(value) if value is not None else "",
                "field_label": self.env[self.res_model]._fields[
                    change.field_name
                ].string,
            })

    def action_submit(self):
        """Extend P2-5 submission with the structured-change requirement."""
        for request_record in self:
            if not request_record.change_ids:
                raise UserError(
                    _(
                        "List the exact field changes being requested. "
                        "Approvers cannot meaningfully sign for a description "
                        "alone, and execution applies only what is listed here."
                    )
                )
            request_record._capture_current_values()
        return super().action_submit()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def action_execute(self):
        """Apply the approved change under a single-use unlock, then re-freeze."""
        self.ensure_one()
        if self.state == "executed":
            raise UserError(_("This override has already been executed."))

        # Re-derives three distinct WebAuthn-confirmed approvals from stored
        # evidence. Raises and alerts if anything is short.
        self._assert_executable()

        record = self._target_record()
        if not record:
            raise UserError(_("The target record no longer exists."))

        values = {c.field_name: c._typed_value() for c in self.change_ids}
        if not values:
            raise UserError(_("There is nothing to apply."))

        ticket = self.env["sec.freeze.unlock.ticket"].issue(
            record,
            list(values),
            "override.request,%s" % self.id,
        )

        try:
            # Layer 2: the P1-5 database trigger knows nothing about tickets.
            # SET LOCAL scopes this to the current transaction only.
            self.env.cr.execute("SET LOCAL %s = 'granted'" % UNLOCK_GUC)
            # Layer 1: the ORM check consults the ticket.
            record.with_context(
                **{"sec_freeze_unlock_ticket": ticket.id}
            ).write(values)
            self.env.flush_all()
        finally:
            # Reset inside the same transaction, so nothing later in it can
            # write to a frozen record on the back of this unlock.
            self.env.cr.execute("SET LOCAL %s = ''" % UNLOCK_GUC)

        ticket.consume()
        self.sudo().write(
            {
                "state": "executed",
                "executed_at": fields.Datetime.now(),
                "executed_by_id": self.env.user.id,
                "unlock_ticket_id": ticket.id,
            }
        )
        self._write_locker_chain_entry(values)
        self._raise_anomaly(
            alert_type="incomplete_override",
            name=_("Frozen record changed under approved override"),
            reason=_(
                "%(target)s was changed under override %(ref)s, authorised by "
                "%(approvers)s. Fields changed: %(fields)s. The record is "
                "frozen again; the unlock ticket is spent.",
                target=self.target_display,
                ref=self.name,
                approvers=", ".join(
                    self.approval_ids.filtered(lambda a: a.decision == "approve")
                    .mapped("approver_id.login")
                ),
                fields=", ".join(sorted(values)),
            ),
            severity="critical",
            record=self,
        )
        _logger.critical(
            "Override %s executed on %s,%s fields=%s by %s",
            self.name,
            self.res_model,
            self.res_id,
            sorted(values),
            self.env.user.login,
        )
        return True

    def _write_locker_chain_entry(self, values):
        """Write one Locker entry covering the whole chain.

        The field-level edit is already captured by the auditlog rules from
        P1-7. This adds the thing those cannot express: that this particular
        edit was authorised by these three named people under this request. An
        auditor reading the Locker should not have to join four tables to
        establish that.

        Guarded by a membership test rather than a module dependency, so the
        override engine still installs without the Locker.
        """
        self.ensure_one()
        if "audit.locker.entry" not in self.env:
            return
        approvals = self.approval_ids.filtered(lambda a: a.decision == "approve")
        import json

        payload = {
            "override_reference": self.name,
            "requester": self.requester_id.login,
            "reason_category": self.reason_category_id.name,
            "instruction_type": self.instruction_type,
            "justification": self.justification,
            "approvals": [
                {
                    "tier": a.tier_name,
                    "approver": a.approver_id.login,
                    "at": str(a.decided_at),
                    "webauthn_confirmed": a.strongly_authenticated,
                }
                for a in approvals
            ],
            "fields_changed": {k: str(v) for k, v in values.items()},
        }
        try:
            self.env["audit.locker.entry"].append(
                {
                    "user_id": self.env.user.id,
                    "user_login": self.env.user.login,
                    "source_ip": self.env["sec.anomaly.mixin"]._current_source_ip(),
                    "model_name": self.res_model,
                    "res_id": self.res_id,
                    "record_label": self.target_display,
                    "action_type": "write",
                    "field_changes": json.dumps(
                        payload, sort_keys=True, separators=(",", ":")
                    ),
                }
            )
        except Exception:  # noqa: BLE001 - the edit already happened
            _logger.exception(
                "Override %s executed but its Locker chain entry failed to "
                "write. The edit itself is still captured by auditlog.",
                self.name,
            )
