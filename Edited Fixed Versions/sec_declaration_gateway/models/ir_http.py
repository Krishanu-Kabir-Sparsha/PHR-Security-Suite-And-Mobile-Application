# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The blocking gate: no backend route is reachable before acceptance.

Implements PRD US-1.1, first acceptance criterion.

Enforced in ``ir.http._dispatch`` rather than by overriding named web
controllers, for two reasons. First, it is route-name independent, so it does
not break when Odoo renames its backend entry point (V18 introduced /odoo
alongside /web). Second, and more importantly, a modal rendered by the web
client can be dismissed from the browser console; a server-side dispatch gate
cannot. The PRD asks for a "full-screen modal" — this is implemented as a
server-rendered blocking page, which satisfies the stated criterion ("no
dashboard route is reachable before acceptance") more strictly than a modal
would.
"""

import logging

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)

# Paths that must stay reachable, or the user cannot log in, load the
# declaration page, or log out again.
GATE_ALLOWLIST_PREFIXES = (
    "/declaration",
    "/web/login",
    "/web/logout",
    "/web/session/logout",
    "/web/session/destroy",
    "/web/static",
    "/web/assets",
    "/web/image",
    "/web/binary",
    "/websocket",
    "/longpolling",
    "/favicon.ico",
    "/web/webclient",
    "/web/health",
)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _is_declaration_gated_path(cls, path):
        """True when this path should be blocked pending acceptance."""
        return not any(path.startswith(prefix) for prefix in GATE_ALLOWLIST_PREFIXES)

    @classmethod
    def _dispatch(cls, endpoint):
        try:
            if request and request.session and request.session.uid:
                path = request.httprequest.path
                if cls._is_declaration_gated_path(path):
                    user = request.env.user
                    if (
                        not user._is_declaration_exempt()
                        and user.must_accept_declaration
                    ):
                        _logger.info(
                            "Declaration gate blocked %s for user %s",
                            path,
                            user.login,
                        )
                        return request.redirect("/declaration/pending")
        except Exception:  # noqa: BLE001 - a fault here must not deny all access
            _logger.exception("Declaration gate check failed; allowing request")
        return super()._dispatch(endpoint)
