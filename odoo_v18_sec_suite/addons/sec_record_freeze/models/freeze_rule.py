# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Configuration for which records freeze, when, and on which fields.

Implements the configurable half of BRD FR-3.1 and PRD US-3.1.

The critical design decision in this module, and the one most likely to be
questioned: **freezing is field-selective, not total.**

A naive `write()` block on any confirmed Sales Order breaks Odoo outright.
Confirmed orders are written to constantly by the system itself — delivery
status, invoice status, delivered quantities, message threads, activity
scheduling, currency rate recomputation. Blocking all of that does not produce
a secure ERP; it produces an ERP where you cannot deliver goods or raise an
invoice, and the first operational emergency gets the whole module uninstalled.

So each rule names the fields that carry business meaning — amounts, the
counterparty, dates, lines, taxes — and those are the ones that freeze.
Everything else continues to move. This is a faithful reading of the BRD's
actual intent ("confirmed business data cannot be silently altered"), not a
weakening of it, but it *is* a decision the product owner should see and
confirm, because a field left off a protected list is a field somebody can
change on a confirmed record.
"""

import logging

from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Technical fields Odoo writes as a matter of course. Never protected, on any
# model, regardless of rule configuration.
ALWAYS_ALLOWED_FIELDS = {
    "message_ids",
    "message_follower_ids",
    "message_main_attachment_id",
    "message_partner_ids",
    "activity_ids",
    "activity_state",
    "activity_user_id",
    "activity_date_deadline",
    "activity_summary",
    "activity_type_id",
    "activity_exception_decoration",
    "activity_exception_icon",
    "write_date",
    "write_uid",
    "access_token",
    "access_url",
    "access_warning",
}


class FreezeRule(models.Model):
    """One freeze policy for one model."""

    _name = "sec.freeze.rule"
    _description = "Record Freeze Rule"
    _order = "model_name"

    name = fields.Char(
        string="Name",
        required=True,
        help="Human-readable label, e.g. 'Sales Orders'.",
    )
    model_name = fields.Char(
        string="Model",
        required=True,
        index=True,
        help="Technical model this rule governs, e.g. sale.order.",
    )
    state_field_path = fields.Char(
        string="State Field Path",
        required=True,
        default="state",
        help="Dotted path to the field holding the state, relative to the "
        "record. Use a path such as 'order_id.state' for line models, whose "
        "frozen-ness is inherited from their parent document.",
    )
    frozen_states = fields.Char(
        string="Frozen States",
        required=True,
        help="Comma-separated state values that freeze the record, "
        "e.g. sale,done or posted.",
    )
    protected_fields = fields.Text(
        string="Protected Fields",
        required=True,
        help="Comma-separated fields that may NOT be written once the record "
        "is frozen. Anything not listed here remains writable, so that "
        "system-driven workflow updates continue to function.",
    )
    block_unlink = fields.Boolean(
        string="Block Deletion",
        default=True,
        help="Deletion of a frozen record is always a business-material act, "
        "so this defaults on and should stay on.",
    )
    enforcement_active = fields.Boolean(
        string="Enforcement Active",
        default=True,
        tracking=True,
        help="Master switch for this rule. Turning enforcement off is itself a "
        "high-severity audited event, and is the intended operational "
        "safety valve during rollout rather than uninstalling the module.",
    )
    stream = fields.Selection(
        selection=[
            ("sales", "Sales"),
            ("purchase", "Purchase"),
            ("accounting", "Accounting"),
            ("other", "Other"),
        ],
        string="Transaction Stream",
        required=True,
        default="other",
        help="Which back-end lock toggle governs this rule (US-3.2, built in "
        "P1-6). Independent toggles are required for Sales and Purchase.",
    )
    notes = fields.Text(
        string="Notes",
        help="Rationale for the protected field list, reviewed at the monthly audit.",
    )

    _sql_constraints = [
        (
            "model_uniq",
            "unique(model_name)",
            "A freeze rule already exists for that model.",
        ),
    ]

    @api.constrains("protected_fields")
    def _check_protected_fields_not_empty(self):
        for rule in self:
            if not rule.protected_field_set():
                raise ValidationError(
                    _(
                        "Freeze rule '%(name)s' protects no fields, so it would "
                        "enforce nothing. Either list the fields that must not "
                        "change once confirmed, or deactivate the rule.",
                        name=rule.name,
                    )
                )

    @api.constrains("model_name", "state_field_path", "protected_fields")
    def _check_fields_exist(self):
        """Catch typos in field names at configuration time, not at runtime.

        A misspelled field in the protected list silently protects nothing,
        which is the worst possible failure mode for a security control: it
        looks configured and enforces nothing.
        """
        for rule in self:
            model = self.env.get(rule.model_name)
            if model is None:
                # The target module may not be installed; not an error here.
                continue
            unknown = rule.protected_field_set() - set(model._fields)
            if unknown:
                raise ValidationError(
                    _(
                        "Freeze rule '%(name)s' lists fields that do not exist on "
                        "%(model)s: %(unknown)s. A misspelled field protects "
                        "nothing while appearing to be configured.",
                        name=rule.name,
                        model=rule.model_name,
                        unknown=", ".join(sorted(unknown)),
                    )
                )
            root_field = rule.state_field_path.split(".")[0]
            if root_field not in model._fields:
                raise ValidationError(
                    _(
                        "State field path '%(path)s' does not resolve on "
                        "%(model)s.",
                        path=rule.state_field_path,
                        model=rule.model_name,
                    )
                )

    def _csv_set(self, value):
        return {part.strip() for part in (value or "").split(",") if part.strip()}

    def protected_field_set(self):
        self.ensure_one()
        return self._csv_set(self.protected_fields) - ALWAYS_ALLOWED_FIELDS

    def frozen_state_set(self):
        self.ensure_one()
        return self._csv_set(self.frozen_states)

    @api.model
    @tools.ormcache("model_name")
    def _active_rule_id_for(self, model_name):
        """Cached id of the active rule for a model, or False.

        P4-5. Before caching, every write to an in-scope model issued a SELECT
        here, another for the transaction stream and a third for the stream
        lock — three round trips on configuration tables that change perhaps
        once a year, on the hot path of every sales order save.

        Only the id is cached, never a recordset: cached recordsets carry a
        stale environment and are a well-known source of subtle bugs.
        """
        rule = self.sudo().search(
            [("model_name", "=", model_name), ("enforcement_active", "=", True)],
            limit=1,
        )
        return rule.id or False

    @api.model
    @tools.ormcache("model_name")
    def _stream_for(self, model_name):
        """Cached transaction stream for a model, independent of enforcement."""
        rule = self.sudo().search([("model_name", "=", model_name)], limit=1)
        return rule.stream if rule else False

    @api.model
    def rule_for(self, model_name):
        """Return the active enforcement rule for a model, or empty."""
        rule_id = self._active_rule_id_for(model_name)
        if not rule_id:
            return self.browse()
        # exists() guards the window between a cache entry and a deletion.
        return self.browse(rule_id).exists()

    @api.model
    def _clear_rule_caches(self):
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._clear_rule_caches()
        return records

    def unlink(self):
        result = super().unlink()
        self._clear_rule_caches()
        return result

    def write(self, vals):
        """Changing enforcement is itself an audited, high-severity event."""
        if "enforcement_active" in vals:
            for rule in self:
                if rule.enforcement_active and not vals["enforcement_active"]:
                    self.env["sec.anomaly.mixin"]._raise_anomaly(
                        alert_type="frozen_record_write_attempt",
                        name=_("Record freeze enforcement DISABLED for %s", rule.model_name),
                        reason=_(
                            "Freeze enforcement was switched off for %(model)s by "
                            "%(user)s. While off, confirmed records on this model "
                            "can be edited without an override.",
                            model=rule.model_name,
                            user=self.env.user.login,
                        ),
                        severity="critical",
                        record=rule,
                    )
                    _logger.critical(
                        "Freeze enforcement disabled for %s by %s",
                        rule.model_name,
                        self.env.user.login,
                    )
        result = super().write(vals)
        self._clear_rule_caches()
        return result
