# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Business-hours definition for out-of-hours detection (US-7.1).

Out-of-hours editing is the one anomaly class in US-7.1 that nothing in the
suite raised before this module: the freeze engine, the declaration gateway and
the override engine all flag things that are wrong in themselves, whereas
editing at 02:00 is only *interesting*.

Two things this gets right that a naive implementation would not:

**Timezone.** Locker timestamps are UTC, correctly. Comparing a UTC hour against
"09:00 to 18:00" would flag an entire Bangladeshi workday as out-of-hours and
the dashboard would be abandoned in a week. The comparison converts to a
configured local timezone first.

**A signal, not a violation.** Working late is normal in most organisations. An
out-of-hours alert is raised at low severity and exists to be read alongside
other signals — an out-of-hours edit to a high-value field by someone who also
skipped documentation is a story; any one of those alone usually is not.
"""

import logging

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

PARAM_START = "sec_surveillance.business_start_hour"
PARAM_END = "sec_surveillance.business_end_hour"
PARAM_DAYS = "sec_surveillance.working_days"
PARAM_TZ = "sec_surveillance.timezone"
PARAM_ENABLED = "sec_surveillance.out_of_hours_enabled"

# Models whose edits are worth judging against business hours. Deliberately
# limited to the in-scope business documents: flagging out-of-hours writes to
# every technical model would bury the dashboard in noise on day one.
WATCHED_MODELS = (
    "sale.order",
    "sale.order.line",
    "purchase.order",
    "purchase.order.line",
    "account.move",
    "account.move.line",
)


class BusinessHours(models.AbstractModel):
    _name = "sec.business.hours"
    _description = "Business Hours Configuration"

    @api.model
    def _param(self, key, default):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    @api.model
    def enabled(self):
        return self._param(PARAM_ENABLED, "True") in ("True", "true", "1")

    @api.model
    def timezone(self):
        """Configured timezone, falling back to the company's, then UTC."""
        configured = (self._param(PARAM_TZ, "") or "").strip()
        if configured:
            return configured
        company_tz = self.env.company.partner_id.tz
        return company_tz or "UTC"

    @api.model
    def window(self):
        try:
            start = int(self._param(PARAM_START, "9"))
            end = int(self._param(PARAM_END, "18"))
        except ValueError:
            _logger.warning("Malformed business hours configuration; using 9-18")
            start, end = 9, 18
        return start, end

    @api.model
    def working_days(self):
        """ISO weekdays, Monday = 1. Default Sunday-Thursday is not assumed."""
        raw = self._param(PARAM_DAYS, "1,2,3,4,5")
        try:
            return {int(d.strip()) for d in raw.split(",") if d.strip()}
        except ValueError:
            _logger.warning("Malformed working days configuration; using Mon-Fri")
            return {1, 2, 3, 4, 5}

    @api.model
    def is_out_of_hours(self, timestamp_utc):
        """Whether a UTC timestamp falls outside configured local hours."""
        if not timestamp_utc:
            return False
        try:
            local_zone = pytz.timezone(self.timezone())
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "Unknown timezone %s configured; out-of-hours detection "
                "disabled rather than guessed",
                self.timezone(),
            )
            return False
        local = pytz.utc.localize(timestamp_utc).astimezone(local_zone)
        start, end = self.window()
        if local.isoweekday() not in self.working_days():
            return True
        return not (start <= local.hour < end)

    @api.model
    def describe(self, timestamp_utc):
        """Human-readable local time, for the alert text."""
        try:
            local_zone = pytz.timezone(self.timezone())
            local = pytz.utc.localize(timestamp_utc).astimezone(local_zone)
            return local.strftime("%A %d %B %Y at %H:%M (%Z)")
        except Exception:  # noqa: BLE001 - description must never break alerting
            return str(timestamp_utc) + " UTC"

    @api.model
    def validate_configuration(self):
        """Surface a misconfiguration rather than silently mis-flagging."""
        problems = []
        start, end = self.window()
        if not 0 <= start < 24 or not 0 < end <= 24:
            problems.append(_("Business hours must be within 0-24."))
        if start >= end:
            problems.append(
                _(
                    "Business hours start (%(start)s) is not before end "
                    "(%(end)s). Overnight shifts are not supported; if you run "
                    "them, disable out-of-hours detection rather than leaving "
                    "it flagging every normal edit.",
                    start=start,
                    end=end,
                )
            )
        if not self.working_days():
            problems.append(_("No working days configured."))
        try:
            pytz.timezone(self.timezone())
        except pytz.UnknownTimeZoneError:
            problems.append(
                _("'%s' is not a recognised timezone.", self.timezone())
            )
        if problems:
            raise ValidationError("\n".join(problems))
        return True
