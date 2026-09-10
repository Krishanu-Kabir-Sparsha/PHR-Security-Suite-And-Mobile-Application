# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Subscribe the Locker's auditlog rules on upgrade.

``post_init_hook`` subscribes them, but Odoo runs that on install only. Any
database that gained the OCA ``auditlog`` dependency *after* this module was
first installed therefore ends up with the ten rules present and sitting in
``draft`` -- which captures nothing at all, while every screen still looks
healthy and ``verify_chain()`` reports an intact chain of zero entries.

This runs at upgrade so the fix lands immediately rather than waiting for the
next nightly ``cron_verify_locker_chain``, which now performs the same check.

alert=False deliberately: rules dormant at upgrade time mean setup was never
completed, which is a gap to close rather than an incident to report. The cron
passes alert=True, so a rule that goes dormant *after* this point -- the case
where somebody switched capture off -- does raise a critical anomaly.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    fixed = env["audit.locker.entry"].ensure_rules_subscribed(alert=False)
    if fixed is None:
        _logger.warning(
            "OCA auditlog is not installed; the Audit Locker will capture "
            "nothing until it is."
        )
    elif fixed:
        _logger.warning(
            "Audit Locker capture activated for %s previously dormant rule(s): %s",
            len(fixed),
            ", ".join(fixed.mapped("name")),
        )
    else:
        _logger.info("Audit Locker capture already active for all shipped rules.")
