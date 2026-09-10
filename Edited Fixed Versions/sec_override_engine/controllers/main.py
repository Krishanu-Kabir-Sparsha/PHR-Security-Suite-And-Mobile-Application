# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Mobile-friendly approval screen and its single-round-trip endpoint.

Two reasons this is a standalone page rather than a button on the backend form.

**Mobile.** PRD Section 9 requires approval screens usable on a mobile browser
without installing anything, and the CEO/Owner persona in Section 4 wants
"fast, low-friction WebAuthn approval from mobile". A dedicated page is a link
in a notification email that works on a phone.

**One round trip.** The assertion marker set by
``/webauthn/authenticate/verify`` lives on the HTTP request object. Verifying in
one call and approving in another would lose it, and the tempting fix — moving
the marker to the session — is exactly wrong: one confirmation would then
authorise every later approval in the same browser session. So ``/override/
approve/submit`` verifies the assertion and records the tier in the same call.
"""

import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OverrideApprovalController(http.Controller):
    def _get_request(self, request_id):
        record = request.env["override.request"].browse(int(request_id)).exists()
        if not record:
            return None
        record.check_access("read")
        return record

    @http.route(
        "/override/approve/<int:request_id>",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def approval_page(self, request_id, **kwargs):
        """Render the approval screen for one request."""
        override = self._get_request(request_id)
        if not override:
            return request.redirect("/odoo")
        pending = override._pending_tier_for(request.env.user)
        return request.render(
            "sec_override_engine.approval_page",
            {
                "override": override,
                "is_my_turn": bool(pending),
                "tier_name": pending[0].name if pending else "",
                "verification_ready": request.env[
                    "sec.webauthn.credential"
                ]._verification_ready(),
            },
        )

    @http.route(
        "/override/approve/options",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def approval_options(self, request_id=None, **kwargs):
        """Issue an assertion challenge bound to this override."""
        override = self._get_request(request_id)
        if not override:
            return {"error": _("Request not found.")}
        return request.env["sec.webauthn.credential"].issue_authentication_challenge(
            context_ref=override._webauthn_context_ref()
        )

    @http.route(
        "/override/approve/submit",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def approval_submit(self, request_id=None, credential=None, **kwargs):
        """Verify the assertion and record the tier, in one round trip."""
        override = self._get_request(request_id)
        if not override:
            return {"ok": False, "error": _("Request not found.")}
        context_ref = override._webauthn_context_ref()
        try:
            request.env["sec.webauthn.credential"].verify_authentication(
                credential, context_ref=context_ref
            )
        except Exception as exc:  # noqa: BLE001 - shown to the approver
            return {"ok": False, "error": str(exc)}

        # Marker for this request only; consumed by _assert_webauthn_confirmed.
        request.sec_webauthn_verified_for = context_ref
        try:
            override.validate_tier()
        except Exception as exc:  # noqa: BLE001 - shown to the approver
            return {"ok": False, "error": str(exc)}
        finally:
            # Clear it explicitly so nothing later in this request can reuse
            # the confirmation for a different action.
            request.sec_webauthn_verified_for = None
        override.invalidate_recordset()
        return {
            "ok": True,
            "state": override.state,
            "fully_approved": override.state == "approved",
        }

    @http.route(
        "/override/reject/submit",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def rejection_submit(self, request_id=None, comment=None, **kwargs):
        """Record a rejection. Not WebAuthn-gated; see reject_tier for why."""
        override = self._get_request(request_id)
        if not override:
            return {"ok": False, "error": _("Request not found.")}
        try:
            override.with_context(default_comment=comment).reject_tier()
        except Exception as exc:  # noqa: BLE001 - shown to the approver
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "state": override.state}
