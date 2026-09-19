# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Login, refresh and logout for the mobile app.

These replace the Keycloak OIDC flow the client was originally designed around.
Nothing in the client's networking layer has to change for that: its
`AuthInterceptor` wants a bearer token and a refresh endpoint and does not care
who issues them, so Odoo issuing its own tokens removes an entire component from
the stack rather than adding one.

The role and permission set returned here are what the app uses to choose a
navigation profile. They are advisory for the UI only -- every actual read and
write is still authorised server-side against the user's real Odoo groups, so a
tampered client can change what its own menus look like and nothing else.
"""

import logging

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .common import authenticated, bearer_token, current_ip, fail, ok, _payload

_logger = logging.getLogger(__name__)

# Odoo group -> mobile UserRole wire value, most privileged first. The client's
# UserRole enum is the contract; see lib/core/session/user_role.dart.
ROLE_MAP = [
    ("sec_plaza_rbac.group_security_super_admin", "super_admin"),
    ("sec_plaza_rbac.group_plaza_admin", "hr"),
    ("sec_plaza_rbac.group_plaza_compliance", "hr"),
    ("hr.group_hr_manager", "hr"),
    ("hr.group_hr_user", "hr"),
    ("hr_attendance.group_hr_attendance_manager", "manager"),
]


class MobileAuth(http.Controller):
    def _resolve_role(self, user):
        """Best available mobile role for this user, defaulting to employee."""
        for xmlid, wire in ROLE_MAP:
            if user.has_group(xmlid):
                return wire
        return "employee"

    def _session_user(self, user):
        """The SessionUser payload the client expects on sign-in."""
        employee = (
            request.env["hr.employee"]
            .sudo()
            .search([("user_id", "=", user.id)], limit=1)
        )
        company = user.company_id
        return {
            # employee_id is the app's stable handle for "me". Falling back to
            # the user id keeps a user without an hr.employee record usable
            # rather than crashing the home screen on a null.
            "employee_id": str(employee.id or user.id),
            "display_name": user.name or user.login,
            "role": self._resolve_role(user),
            # Single-tenant today. Sent because the client models it, and
            # because inventing it later would be a breaking change.
            "tenant_id": str(company.id),
            "tenant_name": company.name,
            "job_title": employee.job_title or (employee.job_id.name or None),
            "avatar_url": "/web/image/hr.employee/%s/avatar_128" % employee.id
            if employee
            else None,
            # Advisory, for menu construction only. See the module docstring.
            "permissions": sorted(
                {
                    "attendance.self",
                    "leave.self",
                    *(
                        ["team.read"]
                        if self._resolve_role(user) in ("manager", "hr", "super_admin")
                        else []
                    ),
                }
            ),
        }

    def _token_response(self, record, access, refresh, user):
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            # Seconds, as OAuth-style clients expect.
            "expires_in": int(
                (record.access_expires_at - record.create_date).total_seconds()
            ),
            "user": self._session_user(user),
        }

    @http.route(
        "/api/mobile/v1/auth/login",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def login(self, **kwargs):
        """Exchange a login and password for a token pair.

        ``save_session=False`` matters: without it Odoo would set a session
        cookie for every API call, and a mobile client that then happened to
        hold a cookie would be authenticated two different ways at once.
        """
        data = _payload() or kwargs
        login = (data.get("login") or "").strip()
        password = data.get("password") or ""
        device_label = data.get("device_label")

        if not login or not password:
            return fail(
                422,
                "Enter your username and password.",
                code="missing_credentials",
                errors={
                    **({} if login else {"login": "Required."}),
                    **({} if password else {"password": "Required."}),
                },
            )

        try:
            # interactive=False: this is not a browser sign-in, and the
            # interactive path expects a session and a request context it does
            # not have here.
            auth_info = request.env["res.users"].authenticate(
                request.db,
                {"type": "password", "login": login, "password": password},
                {"interactive": False},
            )
        except AccessDenied:
            # Deliberately identical for unknown user and wrong password, and
            # deliberately says nothing about which. The real reason goes to
            # the server log only.
            return fail(
                401,
                "Those sign-in details were not recognised.",
                code="invalid_credentials",
                log="failed login for %r from %s" % (login, current_ip()),
            )

        uid = auth_info["uid"] if isinstance(auth_info, dict) else auth_info
        user = request.env["res.users"].sudo().browse(uid).exists()
        if not user or not user.active:
            return fail(
                401,
                "Those sign-in details were not recognised.",
                code="invalid_credentials",
                log="authenticate returned an unusable uid %r" % (uid,),
            )

        record, access, refresh = (
            request.env["perfecthr.mobile.token"]
            .sudo()
            .issue(user, device_label=device_label, source_ip=current_ip())
        )
        _logger.info("Mobile sign-in: %s from %s", user.login, current_ip())
        return ok(self._token_response(record, access, refresh, user))

    @http.route(
        "/api/mobile/v1/auth/refresh",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def refresh(self, **kwargs):
        """Exchange a refresh token for a new pair. The old pair is revoked."""
        data = _payload() or kwargs
        raw = data.get("refresh_token")
        try:
            record, access, refresh = (
                request.env["perfecthr.mobile.token"].sudo().rotate(raw)
            )
        except AccessDenied:
            return fail(
                401,
                "Please sign in again.",
                code="invalid_refresh_token",
                log="refresh rejected from %s" % current_ip(),
            )
        return ok(
            self._token_response(record, access, refresh, record.user_id)
        )

    @http.route(
        "/api/mobile/v1/auth/logout",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def logout(self, **kwargs):
        """Revoke the presented token.

        Only the token that was presented, not every session for the user: a
        phone signing out should not sign out the tablet.
        """
        token = (
            request.env["perfecthr.mobile.token"]
            .sudo()
            .resolve_access(bearer_token())
        )
        if token:
            token.revoke()
        return ok({"ok": True})
