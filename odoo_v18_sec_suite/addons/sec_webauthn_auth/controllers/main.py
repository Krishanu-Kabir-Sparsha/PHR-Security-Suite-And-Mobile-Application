# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Enrolment and approval-authentication endpoints.

Both ceremonies verify server-side before reporting success. Errors are
returned as a message rather than raised, so the browser can show the user
something actionable; every failure path is also recorded as an anomaly by the
model layer, so a returned error is never a silent one.
"""

import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WebauthnController(http.Controller):
    def _origin(self):
        headers = request.httprequest.headers
        origin = headers.get("Origin")
        if origin:
            return origin
        return request.httprequest.host_url.rstrip("/")

    @http.route("/webauthn/enroll", type="http", auth="user", methods=["GET"])
    def enrolment_page(self, **kwargs):
        """Render the enrolment page, or a clear explanation of what is missing."""
        config = request.env["sec.webauthn.config"]
        error = None
        try:
            config.check_ready(origin=self._origin())
        except Exception as exc:  # noqa: BLE001 - shown to the user verbatim
            error = str(exc)
        credentials = request.env["sec.webauthn.credential"].enrolled_for(
            request.env.user
        )
        status = request.env["sec.webauthn.credential"].check_enrolment_sufficient(
            request.env.user
        )
        return request.render(
            "sec_webauthn_auth.enrolment_page",
            {
                "error": error,
                "rp_id": config.rp_id(),
                "credentials": credentials,
                "status": status,
                "verification_ready": request.env[
                    "sec.webauthn.credential"
                ]._verification_ready(),
            },
        )

    @http.route(
        "/webauthn/register/options",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def registration_options(self, **kwargs):
        """Issue PublicKeyCredentialCreationOptions for this user."""
        env = request.env
        config = env["sec.webauthn.config"]
        config.check_ready(origin=self._origin())
        user = env.user
        challenge = env["sec.webauthn.challenge"].issue(user, "registration")
        existing = env["sec.webauthn.credential"].enrolled_for(user)
        return {
            "challenge": challenge.challenge,
            "rp": {"id": config.rp_id(), "name": config.rp_name()},
            "user": {
                # A stable, non-reassignable handle. The login is not used:
                # logins can be changed and reused, and a reused handle would
                # let a new holder inherit an old credential.
                "id": "odoo-user-%s" % user.id,
                "name": user.login,
                "displayName": user.name,
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": -7},    # ES256
                {"type": "public-key", "alg": -257},  # RS256
            ],
            "timeout": 300000,
            "attestation": "none",
            "authenticatorSelection": {
                "residentKey": "preferred",
                "userVerification": "required",
            },
            "excludeCredentials": [
                {"type": "public-key", "id": c.credential_id} for c in existing
            ],
        }

    @http.route(
        "/webauthn/register/verify",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def registration_verify(self, credential=None, device_label=None, **kwargs):
        """Verify the attestation and store the credential."""
        Credential = request.env["sec.webauthn.credential"]
        if not Credential._verification_ready():
            return {
                "ok": False,
                "error": _(
                    "The py_webauthn library is not installed on this server, "
                    "so your device's response cannot be verified. Enrolment "
                    "is refused rather than storing an unverified credential."
                ),
            }
        try:
            stored = Credential.verify_and_store_registration(
                credential, device_label
            )
        except Exception as exc:  # noqa: BLE001 - message is shown to the user
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "credential_id": stored.id,
                "device_label": stored.device_label}

    @http.route(
        "/webauthn/authenticate/options",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def authentication_options(self, context_ref=None, **kwargs):
        """Issue an assertion challenge bound to one specific action."""
        return request.env[
            "sec.webauthn.credential"
        ].issue_authentication_challenge(context_ref=context_ref)

    @http.route(
        "/webauthn/authenticate/verify",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def authentication_verify(self, credential=None, context_ref=None, **kwargs):
        """Verify an assertion and mark this request as confirmed.

        The marker lives on the request object, not the session: an assertion
        authorises one action in one request, not everything the user does for
        the rest of the day.
        """
        try:
            verified = request.env["sec.webauthn.credential"].verify_authentication(
                credential, context_ref=context_ref
            )
        except Exception as exc:  # noqa: BLE001 - message is shown to the user
            return {"ok": False, "error": str(exc)}
        request.sec_webauthn_verified_for = context_ref or True
        return {"ok": True, "device_label": verified.device_label}
