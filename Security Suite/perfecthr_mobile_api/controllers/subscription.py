# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""GET /api/mobile/v1/me/subscription -- the workspace's own plan and usage.

WHAT THIS IS FOR
----------------
Perfect HR is sold as a subscription, and the person who administers a tenant
has, until now, had to open the web portal on a desktop to answer "what plan
are we on, when does it renew, and how close are we to our limits?". That is a
question people ask on a phone, usually because a renewal notice arrived on
one.

WHO MAY ASK IT
--------------
Administrators and HR managers only -- see ``res.users._may_view_subscription``.
Plan, price and renewal date are facts about the employer's commercial
relationship with its vendor. An ordinary employee opening Settings should be
looking at their own job, not their company's invoice, and a phone is read over
shoulders far more often than a desktop is.

This is a real authorisation boundary, unlike ``/me/capabilities`` which only
drives menus. The check is made here and the payload is never built for anyone
who fails it, so a client that fabricates the capability still gets a 403 and
no data.

WHY IT CANNOT REACH THE MASTER
------------------------------
The facts are read from a snapshot in this tenant's own configuration, written
by provisioning. A billing server that is slow or unreachable must not be able
to make a phone's Settings screen hang -- and the staleness that buys is
reported, as ``synced_at``, rather than hidden.
"""

import logging

from odoo import http
from odoo.http import request

from .common import authenticated, fail, ok

_logger = logging.getLogger(__name__)


class MobileSubscription(http.Controller):
    @http.route(
        "/api/mobile/v1/me/subscription",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def subscription(self, **kwargs):
        user = request.env.user

        if not user._may_view_subscription():
            # Logged, because someone reaching this without the capability is
            # either a stale app build or somebody probing, and the two are
            # worth being able to tell apart afterwards.
            return fail(
                403,
                "Your plan details are available to workspace administrators.",
                code="subscription_forbidden",
                log="subscription refused for %s" % user.login,
            )

        overview = request.env["perfecthr.mobile.subscription"].overview()

        if overview is None:
            # No snapshot: an on-premise install, or a database provisioned
            # outside the SaaS pipeline. A normal state of the world, answered
            # as such -- the app hides the section rather than showing an
            # empty plan, which would read as a fault.
            return ok({"available": False, "subscription": None})

        return ok({"available": True, "subscription": overview})
