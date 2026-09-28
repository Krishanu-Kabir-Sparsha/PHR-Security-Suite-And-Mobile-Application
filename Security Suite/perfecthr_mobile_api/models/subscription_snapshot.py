# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The workspace's own subscription, read from inside the tenant.

WHERE THIS COMES FROM
---------------------
A subscription record lives on the master database (perfecthr.net), not in the
tenant, so a tenant cannot read ``saas.subscription`` -- the model is not in its
registry. What it *does* have is a snapshot: provisioning writes the
master-owned facts into the tenant's own ``ir.config_parameter`` under
``saas.subscription_info``, and refreshes it whenever the plan changes. See
``saas_subscription/models/tenant_provisioner.py::_store_subscription_snapshot``.

This reads that snapshot. It makes no call back to the master, which is the
point of the snapshot existing: a billing server that is slow, unreachable or
mid-deploy must not be able to slow down or break a phone opening its Settings
screen.

The consequence to be honest about is staleness. The snapshot carries the time
it was written, and that time is reported, so a plan changed five minutes ago
on the portal may still read as the old one here. Saying when a figure was last
confirmed is the difference between a stale number and a wrong one.

STORAGE AND USER COUNTS ARE LIVE
--------------------------------
Those are facts about this database, so they are measured here and now rather
than taken from the snapshot -- which would be a figure from provisioning day
and never true again. Only the plan's *limits* come from the snapshot.

WHO MAY SEE IT
--------------
Enforced by the controller, not here. Plan, price and renewal date are
commercial facts about the employer, not about the employee, and an ordinary
member of staff has no business reading what their company pays. The gate is
``_may_view_subscription`` on ``res.users``.
"""

import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_GB = 1024.0 ** 3

PARAM_KEY = "saas.subscription_info"

# Subscription states, in the words a customer would use.
#
# The raw values are the master's vocabulary; these are what the person paying
# the invoice calls the same thing.
STATE_LABELS = {
    "draft": "Not started",
    "pending": "Being set up",
    "provisioning": "Being set up",
    "active": "Active",
    "suspended": "Suspended",
    "expired": "Expired",
    "canceled": "Cancelled",
    "cancelled": "Cancelled",
}

# How close to a limit counts as worth mentioning. Below this the figure is
# still shown -- it is simply not flagged, because a progress bar that is amber
# from the first day is one nobody looks at.
QUOTA_WARN_RATIO = 0.8

# How near a renewal starts being called out.
RENEWAL_WARN_DAYS = 14


class MobileSubscriptionSnapshot(models.AbstractModel):
    """Reads the tenant's subscription snapshot and measures live usage."""

    _name = "perfecthr.mobile.subscription"
    _description = "Mobile Subscription Snapshot"

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------
    @api.model
    def _snapshot(self):
        """The master-written facts, or ``{}`` when there are none.

        An empty result is a normal outcome, not a fault: an on-premise
        install or a database that was never provisioned through the SaaS
        pipeline simply has no subscription, and the app is told so plainly.
        """
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_KEY)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            # Corrupt rather than absent. Logged, because this should never
            # happen and somebody needs to know it did -- but still answered as
            # "no subscription", since a broken Settings screen helps nobody.
            _logger.warning("Could not parse %s; treating as absent", PARAM_KEY)
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @api.model
    def _storage_used_gb(self):
        """Database size plus attachments, in GB.

        Both halves are attempted independently so that a permissions problem
        on one does not discard the other. A failure contributes zero and is
        logged; the alternative -- refusing to report storage at all -- tells
        the reader less.
        """
        used = 0
        try:
            self.env.cr.execute("SELECT pg_database_size(current_database())")
            used += self.env.cr.fetchone()[0] or 0
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Could not measure database size: %s", exc)
        try:
            self.env.cr.execute(
                "SELECT COALESCE(SUM(file_size), 0) FROM ir_attachment"
            )
            used += self.env.cr.fetchone()[0] or 0
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Could not measure attachment size: %s", exc)
        return round(used / _GB, 2)

    @api.model
    def _user_count(self):
        """Internal users who count against the plan.

        Portal and public users are excluded (``share = True``) because they do
        not consume a seat, and archived users are excluded because a company
        that offboards ten people should see their seat count fall.
        """
        return (
            self.env["res.users"]
            .sudo()
            .search_count([("share", "=", False), ("active", "=", True)])
        )

    @api.model
    def _apps(self):
        """Installed applications, by their display names.

        ``shortdesc`` rather than ``name``: "Attendances", not
        ``hr_attendance``. The app shows this to a person deciding whether
        their plan covers what they need, and a technical module name answers a
        different question than the one they asked.
        """
        modules = (
            self.env["ir.module.module"]
            .sudo()
            .search([("state", "=", "installed"), ("application", "=", True)])
        )
        return sorted({module.shortdesc or module.name for module in modules})

    # ------------------------------------------------------------------
    # Derived reporting
    # ------------------------------------------------------------------
    @api.model
    def _quota(self, used, limit, unit):
        """One usage line: used, limit, how close, and whether to say so.

        A limit of zero means unlimited on this plan, which is reported as
        such rather than as a division by zero or a full bar.
        """
        limit = limit or 0
        unlimited = limit <= 0
        ratio = None if unlimited else min(used / float(limit), 1.0)
        return {
            "used": used,
            "limit": None if unlimited else limit,
            "unit": unit,
            "unlimited": unlimited,
            "ratio": round(ratio, 4) if ratio is not None else None,
            # Advisory only. Nothing in Perfect HR blocks work on a quota --
            # a company that cannot record attendance because it is near a
            # storage limit has been failed by its software, not its plan.
            "near_limit": bool(ratio is not None and ratio >= QUOTA_WARN_RATIO),
        }

    @api.model
    def _parse_date(self, value):
        if not value:
            return None
        try:
            return fields.Date.to_date(value)
        except (ValueError, TypeError):
            return None

    @api.model
    def _days_until(self, value):
        date = self._parse_date(value)
        if not date:
            return None
        return (date - fields.Date.context_today(self.env.user)).days

    @api.model
    def _health(self, info, days_left):
        """One word for the state of the service, and a sentence about it.

        Ordered by severity so that a suspended trial reads as suspended: the
        worst true thing is the one worth leading with.
        """
        state = (info.get("state") or "").lower()
        is_trial = bool(info.get("is_trial"))

        if state in ("suspended",):
            return (
                "suspended",
                "Your workspace is suspended. Renew from the customer portal "
                "to restore full access.",
            )
        if state in ("expired", "canceled", "cancelled"):
            return (
                "ended",
                "This subscription has ended. Contact Perfect HR to start it "
                "again.",
            )
        if state in ("draft", "pending", "provisioning"):
            return ("setup", "Your workspace is still being set up.")
        if is_trial:
            if days_left is not None and days_left <= 0:
                return ("ended", "Your free trial has finished.")
            if days_left is not None:
                return (
                    "trial",
                    "Free trial — %s day%s left."
                    % (days_left, "" if days_left == 1 else "s"),
                )
            return ("trial", "You are on a free trial.")
        if days_left is not None and 0 <= days_left <= RENEWAL_WARN_DAYS:
            return (
                "renewing",
                "Renews in %s day%s." % (days_left, "" if days_left == 1 else "s"),
            )
        return ("active", "Your subscription is active.")

    # ------------------------------------------------------------------
    # The payload
    # ------------------------------------------------------------------
    @api.model
    def overview(self):
        """Everything the app's Subscription screen shows, or ``None``.

        ``None`` means this database has no subscription snapshot -- an
        on-premise install, or one provisioned outside the SaaS pipeline. The
        app hides the whole section in that case, which is correct: there is
        no plan to talk about, and an empty "Subscription" screen would read
        as a fault.
        """
        info = self._snapshot()
        if not info:
            return None

        is_trial = bool(info.get("is_trial"))
        # A trial counts down to its own end date; a paid plan counts down to
        # the next invoice. Reading the wrong one would tell a trial customer
        # they have months left.
        renewal_key = "trial_end_date" if is_trial else "date_next_invoice"
        days_left = self._days_until(info.get(renewal_key))
        health, headline = self._health(info, days_left)

        currency = info.get("currency") or ""
        monthly = info.get("monthly_price") or 0.0

        return {
            "plan_name": info.get("package_name") or None,
            "plan_label": info.get("billing_plan_label") or None,
            "reference": info.get("subscription_ref") or None,
            "is_trial": is_trial,
            # A single word the app styles on, plus the sentence it prints.
            # Sent together so the phone never has to infer severity from
            # English, and never has to compose the sentence itself.
            "health": health,
            "headline": headline,
            "status_label": STATE_LABELS.get(
                (info.get("state") or "").lower(),
                (info.get("state") or "").replace("_", " ").title() or None,
            ),
            "price": (
                {
                    "amount": monthly,
                    "currency": currency,
                    # Pre-formatted, because the currency here is a symbol
                    # rather than a code and the phone has no locale rules for
                    # it. One formatting decision, made once, on the server.
                    "display": "%s%s / month"
                    % (currency, "{:,.2f}".format(monthly)),
                }
                if monthly
                else None
            ),
            "started_on": info.get("date_start") or None,
            "renews_on": info.get(renewal_key) or None,
            "days_left": days_left,
            "usage": {
                "users": self._quota(
                    self._user_count(), info.get("user_limit") or 0, "users"
                ),
                "storage": self._quota(
                    self._storage_used_gb(),
                    info.get("storage_limit_gb") or 0,
                    "GB",
                ),
            },
            "apps": self._apps(),
            # Deep links back to the customer portal on the master. Sent rather
            # than built in the app, because only the master knows its own
            # public URL -- and a link the app composed would break the first
            # time the portal moved.
            "manage_url": info.get("manage_url") or None,
            "upgrade_url": info.get("upgrade_url") or None,
            # When these master-owned facts were last written. Reported so a
            # figure that is behind the portal can be recognised as behind
            # rather than wrong.
            "synced_at": info.get("synced_at") or None,
        }
