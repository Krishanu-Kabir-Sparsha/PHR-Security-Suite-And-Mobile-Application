# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Turn on Odoo's automatic check-out for companies using mobile attendance.

WHY THIS IS A MIGRATION AND NOT A DEFAULT
-----------------------------------------
``res.company.auto_check_out`` ships with Odoo 18, along with the cron that
acts on it, and is **off** out of the box. That default is fine for a
deployment where people punch at a terminal by the door and notice the screen
on the way out. It is wrong for one where they punch on a phone, because the
phone goes in a pocket and the check-out is remembered or it is not.

The cost of leaving it off is not tidiness. An unclosed row makes
``hr.attendance``'s own overlap constraint refuse **every** later check-in for
that employee, so one forgotten Friday blocks Monday, Tuesday and Wednesday
until somebody with backend access notices. That is exactly what happened on
this deployment: a row opened on 24 September was still open on the 26th and
every check-in in between was refused.

Applied once, on upgrade to 18.0.1.14.0, rather than as a column default:
a default would only touch companies created afterwards, and the companies
that need it already exist.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not touch a company that has already turned the setting on or off by
hand -- only ones still sitting on the shipped default -- and it only touches
companies that actually use mobile attendance. An administrator who decided
against automatic check-out does not get overruled by an upgrade.
"""

import logging

_logger = logging.getLogger(__name__)

# Hours past the end of the scheduled working day before the cron closes an
# open session. Odoo's own default, restated here because the migration sets
# it explicitly rather than relying on a field default that may have been
# changed.
TOLERANCE_HOURS = 2.0


def migrate(cr, version):
    if not version:
        return

    # Companies that record attendance from the app and have never expressed a
    # preference about automatic check-out. `auto_check_out IS NOT TRUE` covers
    # both false and null, the latter appearing on rows created before the
    # column existed.
    cr.execute(
        """
        SELECT id, name FROM res_company
         WHERE mobile_auto_checkin IS TRUE
           AND auto_check_out IS NOT TRUE
        """
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info(
            "Automatic check-out: nothing to change; no company is using "
            "mobile attendance with it still off."
        )
        return

    cr.execute(
        """
        UPDATE res_company
           SET auto_check_out = TRUE,
               auto_check_out_tolerance = %s
         WHERE id IN %s
        """,
        (TOLERANCE_HOURS, tuple(company_id for company_id, _name in rows)),
    )
    _logger.warning(
        "Automatic check-out enabled for %d company/companies (%s) with a "
        "%.1f hour tolerance. A session left open past the end of the "
        "scheduled working day plus that tolerance is now closed by Odoo's "
        "own cron, stamped out_mode='auto_check_out' so it is visibly not a "
        "real punch. Turn it off per company under Mobile Sign-in if this is "
        "not wanted.",
        len(rows),
        ", ".join(name for _id, name in rows),
        TOLERANCE_HOURS,
    )
