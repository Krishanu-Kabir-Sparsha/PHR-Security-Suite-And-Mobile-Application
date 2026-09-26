# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Install or refresh the database-level freeze triggers on upgrade.

The triggers themselves are generated rather than written as static SQL,
because the columns to guard are derived from the rule configuration and from
what actually exists in the schema (one2many "fields" are not columns, and a
protected field on an uninstalled model must be skipped). A static .sql file
would drift from the configuration the moment anyone edited a rule, which for
a security control is worse than no file at all.

This is a documented departure from the master build prompt's instruction that
PostgreSQL work live in versioned migration scripts: the *invocation* is
versioned here, the generation logic lives in models/freeze_sql.py where it can
be tested. Recorded in PROGRESS.md under Known Deviations.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    results = env["sec.freeze.rule"].sync_all_triggers()
    for model_name, status in sorted(results.items()):
        _logger.info("Freeze trigger sync: %s -> %s", model_name, status)
