# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Controllers serving the blocking declaration page and recording acceptance."""

import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DeclarationGateway(http.Controller):
    @http.route(
        "/declaration/pending",
        type="http",
        auth="user",
        website=False,
        methods=["GET"],
    )
    def declaration_pending(self, **kwargs):
        """Render the blocking declaration page."""
        user = request.env.user
        version = request.env["declaration.version"].sudo().get_current_version()
        if not version or not user.must_accept_declaration:
            return request.redirect("/odoo")
        lang = (user.lang or "en_US").lower()
        body = version.body_html
        if lang.startswith("bn") and version.body_html_bn:
            body = version.body_html_bn
        return request.render(
            "sec_declaration_gateway.declaration_page",
            {
                "user": user,
                "version": version,
                "body": body,
                "error": kwargs.get("error"),
            },
        )

    @http.route(
        "/declaration/accept",
        type="http",
        auth="user",
        website=False,
        methods=["POST"],
        csrf=True,
    )
    def declaration_accept(self, **post):
        """Record an acceptance.

        The version id and hash are taken from the server's current published
        version, never from the submitted form. Trusting a client-supplied hash
        would let a user record acceptance of text they were never shown, which
        would quietly destroy the evidentiary value of the whole mechanism.
        """
        user = request.env.user
        version = request.env["declaration.version"].sudo().get_current_version()
        if not version:
            return request.redirect("/odoo")

        if not post.get("accept"):
            return request.redirect(
                "/declaration/pending?error=%s"
                % _("You must tick the acknowledgement box to continue.")
            )

        existing = (
            request.env["declaration.signoff"]
            .sudo()
            .search(
                [("user_id", "=", user.id), ("version_id", "=", version.id)], limit=1
            )
        )
        if not existing:
            request.env["declaration.signoff"].sudo().create(
                {
                    "user_id": user.id,
                    "version_id": version.id,
                    "declaration_version": version.version,
                    "text_hash": version.text_hash,
                    "source_ip": request.httprequest.remote_addr,
                    "user_agent": request.httprequest.headers.get("User-Agent"),
                }
            )
            _logger.info(
                "Declaration %s accepted by %s from %s",
                version.version,
                user.login,
                request.httprequest.remote_addr,
            )
        return request.redirect("/odoo")
