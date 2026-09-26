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

# Context reference for "prove you still hold a device before adding another".
# Must match the value _check_enrolment_permitted gates Route 2 on; a mismatch
# would silently fail closed and look exactly like a broken authenticator.
ADD_CREDENTIAL_CONTEXT = "sec.webauthn.credential,add"


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
    def registration_verify(
        self, credential=None, device_label=None, assertion=None, **kwargs
    ):
        """Verify the attestation and store the credential.

        ``assertion`` carries a ceremony performed on an authenticator the user
        already holds, and it has to be verified *here* rather than by a prior
        call to /webauthn/authenticate/verify.

        Adding a device while one still works is Route 2 of
        _check_enrolment_permitted, which gates on
        _verify_pending_assertion("sec.webauthn.credential,add"). That reads a
        marker on the *request object*, deliberately: an assertion authorises
        one action in one request, not everything the user does for the rest of
        the day. So a marker set by a separate HTTP call is already gone by the
        time this one arrives, and Route 2 could never be satisfied from the
        browser -- adding a second device was impossible, which matters most for
        the final-approval role, where two are required.

        Same shape as the override engine's approval endpoint: verify, mark, act,
        clear in a finally.
        """
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
        marked = False
        try:
            if assertion:
                Credential.verify_authentication(
                    assertion, context_ref=ADD_CREDENTIAL_CONTEXT
                )
                request.sec_webauthn_verified_for = ADD_CREDENTIAL_CONTEXT
                marked = True
            stored = Credential.verify_and_store_registration(
                credential, device_label
            )
        except Exception as exc:  # noqa: BLE001 - message is shown to the user
            return {"ok": False, "error": str(exc)}
        finally:
            # Never leave the marker behind: anything later in this request must
            # not inherit a confirmation it did not ask for.
            if marked:
                request.sec_webauthn_verified_for = None
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
