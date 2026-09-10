# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""P2-2 is live: stop permitting unconfirmed stream lock toggles.

P1-6 shipped with `sec_record_freeze.allow_toggle_without_webauthn` set True,
because requiring a WebAuthn confirmation that did not exist would have made the
back-end lock toggles unusable. Verification now exists, so the exemption is
withdrawn automatically rather than left to somebody remembering.

Deliberately does NOT touch the parameter if an administrator has already set it
to False: this migration removes an exemption, it never grants one.
"""

import logging

_logger = logging.getLogger(__name__)

PARAM = "sec_record_freeze.allow_toggle_without_webauthn"


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    if "sec.freeze.rule" not in env:
        return
    config = env["ir.config_parameter"].sudo()
    current = config.get_param(PARAM, "True")
    if current in ("True", "true", "1"):
        config.set_param(PARAM, "False")
        _logger.warning(
            "WebAuthn verification is available; %s set to False. Back-end "
            "stream lock toggles now require a verified assertion.",
            PARAM,
        )
