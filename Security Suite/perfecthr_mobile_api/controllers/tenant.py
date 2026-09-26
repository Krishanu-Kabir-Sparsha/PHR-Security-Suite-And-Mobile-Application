# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The two questions the app asks before anyone types a password.

    GET /api/mobile/v1/tenant/resolve     is this a Perfect HR workspace?
    GET /api/mobile/v1/tenant/companies   which companies may I pick from?

WHY THE TENANT IS A URL
-----------------------
Perfect HR provisions each customer as its own PostgreSQL database behind its
own hostname, and the server is configured ``dbfilter = ^%h$`` -- the database
name is *exactly* the hostname (see ``saas_subscription/models/
tenant_provisioner.py``). So the tenant identifier and the address the app
talks to are the same string, and asking the user for a tenant URL is asking
them for the tenant ID. Nothing has to look one up from the other, and there is
no central registry to query, be unavailable, or leak the customer list.

This is why the app cannot ship with a compiled-in host. It has to be pointed
at a workspace at runtime, and this endpoint is how it confirms it arrived
somewhere real before showing a password field. A person who mistypes their
company's address should be told "that is not a Perfect HR workspace" here,
not have their password posted to whatever did answer.

WHY THESE ARE PUBLIC, AND WHAT THAT COSTS
-----------------------------------------
They are read before authentication, by necessity: the company picker is drawn
above the password field. So everything either returns is readable by anyone
who can reach the host, and both are written on that assumption.

``resolve`` returns only what is already visible to anyone who loads the login
page in a browser -- the workspace name and its logo -- plus the sign-in policy,
which is not a secret and which the app needs in order to draw the right
screen.

``companies`` returns **nothing at all** until an administrator ticks a box per
company. A tenant's list of subsidiaries is an org chart, and publishing one to
anybody who guesses a subdomain is not a trade worth making for the convenience
of a dropdown. An unconfigured tenant returns an empty list, the app skips the
step, and every user lands in their own default company -- which is the correct
behaviour for the single-company tenants that are most of them.

Both are rate limited per IP. The limit is not about load; it is about making
these useless for sweeping a subdomain range to find which workspaces exist.
"""

import logging
import time
from collections import defaultdict

from odoo import http
from odoo.http import request

from .common import current_ip, fail, ok

_logger = logging.getLogger(__name__)

# Enough for a person fumbling a URL on a phone keyboard; far too few to
# enumerate anything. Per worker process, which is the honest description: Odoo
# runs several and this dict is not shared between them, so the real ceiling is
# this multiplied by the worker count. That is fine for what it defends
# against, and a shared counter would mean a Redis dependency this module does
# not otherwise need.
DISCOVERY_MAX_CALLS = 30
DISCOVERY_WINDOW_SECONDS = 300

_discovery_hits = defaultdict(list)


def _rate_limited(bucket):
    """True when this IP has spent its allowance on ``bucket``.

    Trims as it goes, so the dict cannot grow without bound while the worker
    lives. Keyed on IP and bucket together so exhausting one endpoint does not
    close the other.
    """
    now = time.monotonic()
    key = (bucket, current_ip() or "-")
    recent = [t for t in _discovery_hits[key] if now - t < DISCOVERY_WINDOW_SECONDS]
    if len(recent) >= DISCOVERY_MAX_CALLS:
        _discovery_hits[key] = recent
        return True
    recent.append(now)
    _discovery_hits[key] = recent
    return False


class MobileTenant(http.Controller):
    def _too_many(self):
        return fail(
            429,
            "Too many attempts from this network. Please wait a few minutes "
            "and try again.",
            code="rate_limited",
            log="tenant discovery rate limit hit from %s" % current_ip(),
        )

    @http.route(
        "/api/mobile/v1/tenant/resolve",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def resolve(self, **kwargs):
        """Confirm this host is a Perfect HR workspace, and describe it.

        Answering at all is the signal: a host that is not a Perfect HR
        workspace has no such route and returns Odoo's own 404, which the app
        reads as "that address is not a workspace".
        """
        if _rate_limited("resolve"):
            return self._too_many()

        params = request.env["ir.config_parameter"].sudo()
        company = request.env["res.company"].sudo().browse(1).exists()
        host = request.httprequest.host.split(":")[0].lower()

        # Companies an anonymous caller may be shown. Computed here as well as
        # in /companies so the app can decide in one round trip whether the
        # company step is needed at all.
        listable = (
            request.env["res.company"]
            .sudo()
            .search([("mobile_login_enabled", "=", True), ("active", "=", True)])
        )

        return ok(
            {
                # The database name, which under dbfilter = ^%h$ is the host.
                # Returned explicitly rather than left for the app to infer,
                # because a deployment that is NOT using host-based dbfilter
                # would otherwise have no way to say so.
                "tenant_id": request.db or host,
                "host": host,
                # The workspace's own name, so the app can show "Signing in to
                # Daffodil Group" rather than echoing a URL back at somebody.
                "tenant_name": company.name if company else host,
                "logo_url": "/web/image/res.company/%s/logo/256x256" % company.id
                if company and company.logo
                else None,
                # Drawn behind the sign-in form when set, so a tenant can brand
                # its own login screen without an app release.
                "brand_color": params.get_param("perfecthr.mobile_brand_color")
                or None,
                # True when the app must ask which company. False means either
                # nothing is published or there is only one to pick, and either
                # way the step is skipped and the server uses the user's own
                # default.
                "company_step_required": len(listable) > 1,
                "company_count": len(listable),
                # Lets the app say "please update" rather than failing oddly
                # against a server whose contract has moved on. Unset means no
                # minimum, which is the state on every deployment today.
                "minimum_app_version": params.get_param(
                    "perfecthr.mobile_minimum_version"
                )
                or None,
                # Whether this server can verify a paired device at all. A
                # deployment with a broken cryptography install would otherwise
                # offer an advanced sign-in that can never complete.
                "advance_available": self._advance_available(),
                "api_version": "1.12.0",
            }
        )

    def _advance_available(self):
        """Whether the strong path can actually complete on this server."""
        try:
            Credential = request.env["sec.webauthn.credential"].sudo()
            return bool(
                Credential._device_binding_ready() or Credential._verification_ready()
            )
        except Exception:  # noqa: BLE001 - an absent module is a plain "no"
            _logger.warning(
                "Could not determine whether advanced sign-in is available; "
                "reporting it as unavailable."
            )
            return False

    @http.route(
        "/api/mobile/v1/tenant/companies",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def companies(self, **kwargs):
        """The companies published for the sign-in picker. Often empty.

        Empty is not an error and the app must not treat it as one -- see the
        module docstring. It means "do not ask", and the sign-in endpoint will
        place the user in their own default company.
        """
        if _rate_limited("companies"):
            return self._too_many()

        published = (
            request.env["res.company"]
            .sudo()
            .search(
                [("mobile_login_enabled", "=", True), ("active", "=", True)],
                order="name",
            )
        )
        return ok(
            {
                "companies": [c._mobile_public_payload() for c in published],
                # Restated here so a client that skipped /resolve still knows.
                "company_step_required": len(published) > 1,
            }
        )
