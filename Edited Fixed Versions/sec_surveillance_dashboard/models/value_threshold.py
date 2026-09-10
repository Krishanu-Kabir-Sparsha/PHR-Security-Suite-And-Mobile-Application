# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Configurable high-value field thresholds (P3-2, US-7.1 third bullet).

PRD Section 12, open question 2 asks: "Which specific high-value field
thresholds should trigger anomaly alerts, and who owns tuning them
post-launch?" That question is still unanswered, so this module ships the
mechanism and **no default thresholds at all**.

Inventing a figure would be worse than shipping none. A threshold that is too
low buries the dashboard; one that is too high is a control that exists on paper
and fires never. Either way the number would carry the appearance of a
considered business decision that nobody actually made. Instead, the
configuration checker reports plainly when nothing is configured, so the gap is
visible rather than mistaken for coverage.

Three comparison modes, because "high value" means different things:

- **absolute** — the new value itself is large. Catches a big order.
- **delta** — the value moved a lot in either direction. Catches a large
  correction to an existing figure, which is often the more interesting event:
  changing an invoice from 1,000,000 to 1,001,000 is a small delta on a large
  number, while 1,000 to 100,000 is a small number that grew alarmingly.
- **increase** — the value moved up by a lot. For cases where reductions are
  routine and only growth is worth a look.
"""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

COMPARISON_MODES = [
    ("absolute", "New value exceeds the threshold"),
    ("delta", "Value changed by more than the threshold, in either direction"),
    ("increase", "Value increased by more than the threshold"),
]


class ValueThreshold(models.Model):
    """One high-value rule for one field on one model."""

    _name = "sec.value.threshold"
    _description = "High-Value Field Threshold"
    _order = "model_name, field_name"

    name = fields.Char(
        string="Name",
        compute="_compute_name",
        store=True,
        help="Derived label, so the list reads without opening each record.",
    )
    model_name = fields.Char(
        string="Model",
        required=True,
        index=True,
        help="Technical model, e.g. account.move.",
    )
    field_name = fields.Char(
        string="Field",
        required=True,
        help="Numeric field to watch, e.g. amount_total.",
    )
    threshold_amount = fields.Float(
        string="Threshold",
        required=True,
        help="The figure at or above which an edit is flagged. Expressed in "
        "whatever currency the field is stored in — see the note on "
        "multi-currency in the module README.",
    )
    comparison_mode = fields.Selection(
        selection=COMPARISON_MODES,
        string="Compare",
        default="delta",
        required=True,
        help="Delta is usually the right default: it catches a large "
        "correction to an existing figure, which is more often the "
        "interesting event than a large figure in itself.",
    )
    severity = fields.Selection(
        selection=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("critical", "Critical"),
        ],
        string="Alert Severity",
        default="high",
        required=True,
    )
    active = fields.Boolean(default=True)
    owner_id = fields.Many2one(
        comodel_name="res.users",
        string="Tuning Owner",
        help="Who owns this figure. PRD Section 12 asks who tunes thresholds "
        "post-launch; recording it per threshold answers that concretely "
        "rather than in a policy document nobody reads.",
    )
    notes = fields.Text(
        string="Rationale",
        help="Why this figure. Reviewed at the monthly audit; a threshold "
        "nobody can justify is a threshold nobody will defend when it fires.",
    )

    _sql_constraints = [
        (
            "model_field_uniq",
            "unique(model_name, field_name)",
            "A threshold already exists for that field.",
        ),
    ]

    @api.depends("model_name", "field_name", "threshold_amount")
    def _compute_name(self):
        for threshold in self:
            threshold.name = "%s.%s ≥ %s" % (
                threshold.model_name or "?",
                threshold.field_name or "?",
                threshold.threshold_amount or 0,
            )

    @api.constrains("model_name", "field_name")
    def _check_field_is_numeric(self):
        """A threshold on a non-numeric field would never fire.

        Caught at configuration time, because the failure mode otherwise is a
        rule that looks configured and silently does nothing — the worst shape
        for a control.
        """
        for threshold in self:
            model = self.env.get(threshold.model_name)
            if model is None:
                # Target module may not be installed; not an error here.
                continue
            field = model._fields.get(threshold.field_name)
            if field is None:
                raise ValidationError(
                    _(
                        "%(field)s is not a field on %(model)s.",
                        field=threshold.field_name,
                        model=threshold.model_name,
                    )
                )
            if field.type not in ("float", "monetary", "integer"):
                raise ValidationError(
                    _(
                        "%(field)s is a %(type)s field. A value threshold on it "
                        "would never fire.",
                        field=threshold.field_name,
                        type=field.type,
                    )
                )

    @api.constrains("threshold_amount")
    def _check_threshold_positive(self):
        for threshold in self:
            if threshold.threshold_amount <= 0:
                raise ValidationError(
                    _(
                        "A threshold of %s would fire on every edit.",
                        threshold.threshold_amount,
                    )
                )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    @staticmethod
    def _to_number(raw):
        """Best-effort numeric conversion of a stored diff value."""
        if raw in (None, "", False, "False", "None"):
            return None
        try:
            return float(str(raw).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    def _breach(self, old_value, new_value):
        """Whether this threshold is breached, and by what amount."""
        self.ensure_one()
        old_number = self._to_number(old_value) or 0.0
        new_number = self._to_number(new_value)
        if new_number is None:
            return None
        if self.comparison_mode == "absolute":
            measured = abs(new_number)
        elif self.comparison_mode == "increase":
            measured = new_number - old_number
        else:
            measured = abs(new_number - old_number)
        if measured >= self.threshold_amount:
            return measured
        return None

    @api.model
    def evaluate_entry(self, entry):
        """Check one Locker entry against every active threshold.

        Returns the list of alerts raised, which is normally empty.
        """
        if not entry.field_changes:
            return []
        thresholds = self.sudo().search(
            [("active", "=", True), ("model_name", "=", entry.model_name)]
        )
        if not thresholds:
            return []
        try:
            changes = json.loads(entry.field_changes)
        except (TypeError, ValueError):
            return []
        if not isinstance(changes, dict):
            return []

        raised = []
        for threshold in thresholds:
            change = changes.get(threshold.field_name)
            if not isinstance(change, dict):
                continue
            measured = threshold._breach(change.get("old"), change.get("new"))
            if measured is None:
                continue
            raised.append(threshold._raise_breach(entry, change, measured))
        return raised

    def _raise_breach(self, entry, change, measured):
        self.ensure_one()
        return self.env["sec.anomaly.mixin"]._raise_anomaly(
            alert_type="high_value_edit",
            name=_(
                "High-value change to %(model)s.%(field)s",
                model=self.model_name,
                field=self.field_name,
            ),
            reason=_(
                "%(user)s changed %(field)s on %(label)s from %(old)s to "
                "%(new)s. Measured %(mode)s of %(measured)s meets the "
                "configured threshold of %(threshold)s.",
                user=entry.user_login,
                field=self.field_name,
                label=entry.record_label
                or "%s,%s" % (entry.model_name, entry.res_id),
                old=change.get("old"),
                new=change.get("new"),
                mode=dict(COMPARISON_MODES).get(self.comparison_mode, ""),
                measured=measured,
                threshold=self.threshold_amount,
            ),
            severity=self.severity,
            user=entry.user_id,
            source_ref="audit.locker.entry,%s" % entry.id,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    @api.model
    def coverage_report(self):
        """State plainly whether any threshold is configured at all.

        Consumed by the configuration checker and the monthly forensic report.
        An empty dashboard section can mean "nothing exceeded a threshold" or
        "no threshold exists"; those are very different, and the report says
        which.
        """
        thresholds = self.sudo().search([("active", "=", True)])
        unowned = thresholds.filtered(lambda t: not t.owner_id)
        return {
            "configured": len(thresholds),
            "any_configured": bool(thresholds),
            "without_owner": [t.name for t in unowned],
            "message": _(
                "No high-value thresholds are configured, so no edit will ever "
                "be flagged on value. PRD Section 12 leaves the figures to the "
                "business; until they are set, this control is inactive."
            )
            if not thresholds
            else _("%s threshold(s) active.", len(thresholds)),
        }


class LockerEntryValueSurveillance(models.Model):
    _inherit = "audit.locker.entry"

    def _evaluate_out_of_hours(self):
        """Extend the surveillance hook to also evaluate value thresholds.

        Chained onto the existing hook rather than added as a second override of
        ``append``, so there is one place where per-entry surveillance runs and
        one place where its failures are contained.
        """
        result = super()._evaluate_out_of_hours()
        try:
            self.env["sec.value.threshold"].evaluate_entry(self)
        except Exception:  # noqa: BLE001 - surveillance must not break auditing
            _logger.exception(
                "High-value evaluation failed for Locker entry %s", self.id
            )
        return result
