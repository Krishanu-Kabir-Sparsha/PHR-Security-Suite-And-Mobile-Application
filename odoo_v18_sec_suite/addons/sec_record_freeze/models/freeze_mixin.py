# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""ORM-layer enforcement of the record freeze.

Implements BRD FR-3.1 / FR-3.2 (application half) and PRD US-3.1.

Honest statement of what this layer does and does not achieve, so nobody
oversells it to the CEO/Owner:

- It blocks edits through the web client, the JSON-RPC API, and any Python that
  goes through the ORM. That covers essentially all normal and most abnormal
  use, including an administrator using the Odoo shell.
- `sudo()` does **not** bypass it. The check is on the operation, not the
  permission level, which is the whole point: BRD FR-3.1 says immutability
  applies "including for administrators and developers".
- It does **not** survive raw SQL. Someone with a psql prompt writes straight
  to the table and this code never runs. That is what P1-5's database-level
  constraints partially address, and what BRD Section 9 risk 1 (removing direct
  production DB access) actually addresses. Until that is done, this is a
  strong control against people using Odoo, not against people with the
  database.
"""

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Context key set by the override engine (P2-8) once three tier approvals have
# been validated. Honoured only when a valid unlock ticket backs it — see
# _freeze_unlock_authorised. Setting the key by hand achieves nothing.
UNLOCK_CONTEXT_KEY = "sec_freeze_unlock_ticket"


class RecordFreezeMixin(models.AbstractModel):
    """Inherit on any model that must freeze once confirmed."""

    _name = "sec.record.freeze.mixin"
    _description = "Record Freeze Mixin"
    _inherit = ["sec.anomaly.mixin"]

    # ------------------------------------------------------------------
    # Frozen-state resolution
    # ------------------------------------------------------------------
    def _freeze_rule(self):
        """The active freeze rule for this model, or an empty recordset."""
        return self.env["sec.freeze.rule"].rule_for(self._name)

    def _freeze_stream(self):
        """This model's transaction stream, independent of freeze enforcement.

        Looked up without the enforcement_active filter on purpose: the stream
        lock (US-3.2) is a separate control from the confirm-state freeze, and
        switching the freeze off must not also switch off the lockdown.
        """
        return self.env["sec.freeze.rule"]._stream_for(self._name)

    def _resolve_state_value(self, rule):
        """Read the state through the rule's dotted path.

        Line models inherit frozen-ness from their parent document, which is
        why this walks a path rather than reading a field. Without it, someone
        blocked from editing a confirmed order's total simply edits the order
        line instead and the total recomputes.
        """
        self.ensure_one()
        value = self
        for part in rule.state_field_path.split("."):
            if not value:
                return None
            value = value[part] if part in value._fields else None
            if value is None:
                return None
            if not hasattr(value, "_fields"):
                return value
        return value

    def _filter_frozen(self, rule):
        """Return the subset of self currently in a frozen state."""
        frozen_states = rule.frozen_state_set()
        frozen = self.browse()
        for record in self:
            try:
                if record._resolve_state_value(rule) in frozen_states:
                    frozen |= record
            except Exception:  # noqa: BLE001 - a resolution fault must fail closed
                _logger.exception(
                    "Freeze state resolution failed for %s,%s; treating as frozen",
                    record._name,
                    record.id,
                )
                frozen |= record
        return frozen

    # ------------------------------------------------------------------
    # Authorisation
    # ------------------------------------------------------------------
    def _freeze_unlock_authorised(self, vals=None):
        """Whether a validated single-use unlock covers this exact write.

        Implemented in P2-8. Until then this returned False unconditionally,
        which was correct: there was no override engine, so there was no
        legitimate way to edit a frozen record.

        A ticket id in the context is necessary but nowhere near sufficient.
        The ticket must exist, be unspent, be unexpired, name *this* record,
        and cover *every* protected field being written. A context key any
        caller can set is not an authorisation mechanism, so the key only
        selects which ticket to check.
        """
        ticket_id = self.env.context.get(UNLOCK_CONTEXT_KEY)
        if not ticket_id:
            return False
        ticket = self.env["sec.freeze.unlock.ticket"].sudo().browse(
            int(ticket_id)
        ).exists()
        if not ticket:
            return False
        for record in self:
            if not ticket.is_valid_for(record, vals or {}):
                _logger.warning(
                    "Unlock ticket %s does not authorise write of %s to %s,%s",
                    ticket.id,
                    sorted(vals or {}),
                    record._name,
                    record.id,
                )
                return False
        return True

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------
    def _freeze_blocked_fields(self, vals, rule):
        """Which of the written fields are protected on a frozen record."""
        return sorted(set(vals) & rule.protected_field_set())

    def _freeze_raise(self, frozen, blocked_fields, operation):
        """Flag the attempt, then refuse it."""
        record = frozen[0]
        field_list = ", ".join(blocked_fields) if blocked_fields else _("(deletion)")
        reason = _(
            "%(user)s attempted to %(operation)s %(model)s record(s) %(ids)s "
            "while frozen. Blocked fields: %(fields)s.",
            user=self.env.user.login,
            operation=operation,
            model=self._name,
            ids=", ".join(str(r.id) for r in frozen[:20]),
            fields=field_list,
        )
        self._raise_anomaly_out_of_band(
            alert_type="frozen_record_write_attempt",
            name=_("Write attempt on frozen %s", self._name),
            reason=reason,
            record=record,
        )
        raise UserError(
            _(
                "This record is confirmed and can no longer be changed directly.\n\n"
                "Fields you tried to change: %(fields)s\n\n"
                "If a correction is genuinely needed, raise an override request. "
                "It requires approval from your department head, Compliance, and "
                "the CEO/Owner before the record can be unlocked for a single, "
                "logged edit.\n\n"
                "This attempt has been recorded.",
                fields=field_list,
            )
        )

    def _raise_anomaly_out_of_band(self, alert_type, name, reason, record=None):
        """Write the alert on a separate cursor so the refusal cannot erase it.

        A blocked write raises, which rolls the transaction back. An alert
        written on the same cursor would roll back too, and every blocked
        attempt would silently disappear — the exact opposite of what the
        surveillance requirement asks for.
        """
        try:
            with self.pool.cursor() as new_cr:
                env = self.env(cr=new_cr)
                env["sec.anomaly.mixin"]._raise_anomaly(
                    alert_type=alert_type,
                    name=name,
                    reason=reason,
                    severity="critical",
                    user=self.env.user,
                    source_ref="%s,%s" % (self._name, record.id if record else 0),
                )
        except Exception:  # noqa: BLE001 - alerting must never mask the refusal
            _logger.exception("Failed to raise out-of-band freeze anomaly")

    @api.model_create_multi
    def create(self, vals_list):
        """A locked stream refuses new records, and so does a frozen parent.

        P4-4 finding. Until the adversarial review this method checked only the
        stream lock, which left an open door: blocking edits to a confirmed
        order's total while permitting ``sale.order.line.create()`` against that
        same order means the total can still be changed — just from the other
        side. The one2many path was covered (``order_line`` is a protected field
        on the parent); creating the child directly was not.
        """
        if not self.env.context.get("sec_freeze_install_mode"):
            self.env["sec.stream.lock"].check_stream_writable(self._freeze_stream())
            self._freeze_check_create(vals_list)
        return super().create(vals_list)

    @api.model
    def _freeze_check_create(self, vals_list):
        """Refuse creation of a child row under an already-frozen parent."""
        rule = self._freeze_rule()
        if not rule:
            return True
        path = (rule.state_field_path or "state").split(".")
        if len(path) == 1:
            # Not a child model. A record created directly in a frozen state is
            # left alone deliberately: Odoo creates documents in draft and then
            # confirms them, and blocking here would break normal creation and
            # data import for no security gain.
            return True
        parent_field, remainder = path[0], path[1:]
        frozen_states = rule.frozen_state_set()
        field = self._fields.get(parent_field)
        if field is None or field.type != "many2one":
            return True
        parent_model = self.env.get(field.comodel_name)
        if parent_model is None:
            return True

        for vals in vals_list:
            parent_id = vals.get(parent_field)
            if not parent_id:
                continue
            parent = parent_model.browse(int(parent_id)).exists()
            if not parent:
                continue
            value = parent
            for part in remainder:
                value = value[part] if part in value._fields else None
                if value is None:
                    break
            if value in frozen_states:
                if self._freeze_unlock_authorised(dict(vals)):
                    continue
                self._raise_anomaly_out_of_band(
                    alert_type="frozen_record_write_attempt",
                    name=_("Attempt to add a row to a frozen %s", parent._name),
                    reason=_(
                        "%(user)s attempted to create a %(model)s under "
                        "%(parent)s, which is frozen. Adding a line to a "
                        "confirmed document changes it as surely as editing "
                        "one.",
                        user=self.env.user.login,
                        model=self._name,
                        parent=parent.display_name,
                    ),
                    record=parent,
                )
                raise UserError(
                    _(
                        "This document is confirmed, so lines cannot be added "
                        "to it.\n\nIf a correction is genuinely needed, raise "
                        "an override request.\n\nThis attempt has been "
                        "recorded."
                    )
                )
        return True

    def write(self, vals):
        if not self.env.context.get("sec_freeze_install_mode"):
            self.env["sec.stream.lock"].check_stream_writable(
                self._freeze_stream(), self
            )
        rule = self._freeze_rule()
        if rule and not self.env.context.get("sec_freeze_install_mode"):
            frozen = self._filter_frozen(rule)
            if frozen:
                blocked = frozen._freeze_blocked_fields(vals, rule)
                if blocked and not frozen._freeze_unlock_authorised(
                    {f: vals[f] for f in blocked}
                ):
                    frozen._freeze_raise(frozen, blocked, _("modify"))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("sec_freeze_install_mode"):
            self.env["sec.stream.lock"].check_stream_writable(
                self._freeze_stream(), self
            )
        rule = self._freeze_rule()
        if rule and rule.block_unlink and not self.env.context.get(
            "sec_freeze_install_mode"
        ):
            frozen = self._filter_frozen(rule)
            # A ticket authorises a correction, never a deletion. Deleting a
            # confirmed document is not a correction; it is the removal of the
            # thing being corrected.
            if frozen:
                frozen._freeze_raise(frozen, [], _("delete"))
        return super().unlink()
