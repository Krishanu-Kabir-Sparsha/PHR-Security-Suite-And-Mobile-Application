# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Detect module installation / upgrade, so security guards can stand down.

Both the Plaza RBAC grant guard and the Record Freeze mixin must refuse
operations performed by a human, and must *not* refuse operations performed by
Odoo itself while it installs or upgrades a module. Loading
``purchase/security/purchase_security.xml`` grants a purchase group to a stock
user; installing ``account`` replays demo invoices through the ORM. Neither has
an acting human to justify anything, and refusing them aborts the install with
a ParseError rather than protecting anything.

Both modules already documented this bypass -- ``plaza_bypass_grant_check`` and
``sec_freeze_install_mode`` -- but nothing in Odoo has ever set those keys, so
in practice the bypass never fired. This module supplies the real signals.

Why this is not simply ``not env.registry.ready``
-------------------------------------------------
``registry.ready`` is False for the whole registry build, and Odoo runs module
tests inside that same build (``odoo/tests/common.py`` explicitly works around
it). Keying the bypass on ``ready`` alone would therefore switch both guards off
during the suite's own tests, and every "the freeze blocks this" assertion would
pass without exercising a single check. A security test that cannot fail is
worse than no test. Hence the ``current_test`` term: while a test runs we are
emphatically *not* in unattended install mode, whatever the registry says.
"""

from odoo.modules import module as odoo_module

# Context keys Odoo sets while loading module data. ``install_mode`` is set by
# ``models._load_records`` (every XML ``<record>``); ``install_module`` by
# ``tools/convert.py`` (XML records and CSV ``load()``).
_LOADING_CONTEXT_KEYS = ("install_mode", "install_module")


def in_module_loading(env):
    """Return True when Odoo, not a user, is driving the current write.

    :param env: an ``odoo.api.Environment``.
    :rtype: bool
    """
    context = env.context
    if any(context.get(key) for key in _LOADING_CONTEXT_KEYS):
        return True
    # Covers what the context keys miss: ``<function>`` calls in data files,
    # ``post_init_hook``s, and demo records driven through business methods.
    # ``current_test`` is truthy for the whole of a module's test run.
    return not env.registry.ready and not odoo_module.current_test
