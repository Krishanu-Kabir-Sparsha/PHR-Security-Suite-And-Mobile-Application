# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""WebAuthn enrolment for the mobile app: status, and the ceremony itself.

The app used to hand enrolment to an external browser. That was the right call
while it lasted -- Android's WebView has no FIDO2 support at all, so an embedded
page renders its button and never raises a prompt, and the browser route needed
no signing fingerprint and no assetlinks file.

It is no longer the right call. Approvals belong on the phone, and a workflow
that bounces to Chrome for every signature is one nobody will use. The app now
runs the ceremony natively through Android's Credential Manager, which needs two
things that now exist: a release signing key, and /.well-known/assetlinks.json
naming its fingerprint.

**The app is still not the authenticator.** The credential is created and held
by the phone's credential store, in secure hardware. These endpoints build the
WebAuthn request and verify the response exactly as the browser endpoints do --
by calling the same model methods -- so there is one implementation of the
ceremony rather than two that can disagree.

The browser route is deliberately kept. It is how somebody enrols a laptop, a
security key or a second phone, and it is the fallback wherever the native path
is unavailable: an older Android, a device with no screen lock, iOS. That is why
``enrol_url`` is still returned.

Adding a **second** device needs proof of the first in the same request -- Route
2 of ``_check_enrolment_permitted``. Hence ``step_up``: the app runs an assertion
with the existing device, then a creation with the new one, and posts both
together. A marker set by a separate call would already be gone by the time the
second arrived, which is the bug that made second devices impossible for months.
"""

import logging

from odoo import http
from odoo.http import request

from .common import authenticated, fail, ok, _payload

# Must match the context Route 2 of _check_enrolment_permitted gates on. A
# mismatch here makes adding a second device impossible in a way that reads
# to the user as a verification failure rather than a configuration one.
ADD_CREDENTIAL_CONTEXT = "sec.webauthn.credential,add"

_logger = logging.getLogger(__name__)


class MobileAuthenticators(http.Controller):
    @http.route(
        "/api/mobile/v1/me/authenticators",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def authenticators(self, **kwargs):
        """Enrolment status plus the URL the app should open in a browser."""
        user = request.env.user
        Credential = request.env["sec.webauthn.credential"]
        status = Credential.sudo().check_enrolment_sufficient(user)
        credentials = Credential.sudo().enrolled_for(user)

        config = request.env["sec.webauthn.config"].sudo()
        rp_id = config.rp_id()
        # base_url rather than a constructed host: it is what the administrator
        # actually configured, and it already carries the scheme.
        base = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url", "")
            .rstrip("/")
        )

        return ok(
            {
                "enrolled": status.get("enrolled", 0),
                "required": status.get("required", 0),
                "sufficient": status.get("sufficient", False),
                # Empty rp_id means enrolment is not configured on the server
                # yet. Reported so the app can say so instead of opening a page
                # that only shows a red error block.
                "configured": bool(rp_id),
                "relying_party": rp_id or None,
                "enrol_url": "%s/webauthn/enroll" % base if base else None,
                # Tells the app to expect a browser login. See module docstring.
                "requires_web_session": True,
                # Whether this installation already holds a key of its own.
                # The app uses it to stop offering a native passkey ceremony to
                # a handset that has a working second factor already -- that
                # ceremony needs the OS vendor to validate an app-to-domain
                # association, and when it fails it fails as [50152] with
                # nothing the user can act on.
                "paired_devices": sum(
                    1 for c in credentials if c.mechanism == "bound_device"
                ),
                "devices": [
                    {
                        "id": str(credential.id),
                        "label": credential.device_label,
                        "enrolled_at": credential.enrolled_at,
                        # Which kind of proof this is. Without it the list is
                        # three identical key icons and a user cannot tell the
                        # phone in their hand from a passkey in a cloud
                        # keychain -- which is the difference that decides
                        # whether "Add this device" can possibly work.
                        "mechanism": credential.mechanism or "webauthn",
                        # Surfaced because a synced passkey is not bound to one
                        # piece of hardware, which matters for the Tier 3 role.
                        "backed_up": bool(
                            getattr(credential, "backed_up", False)
                        ),
                    }
                    for credential in credentials
                ],
            }
        )

    # ------------------------------------------------------------------
    # Native enrolment
    # ------------------------------------------------------------------
    @http.route(
        "/api/mobile/v1/me/authenticators/step-up",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def step_up(self, **kwargs):
        """Challenge for the device the user already has.

        Only meaningful when they hold one: adding a second device requires
        proving control of the first, and the app posts that assertion back
        together with the new credential in a single request.
        """
        user = request.env.user
        Credential = request.env["sec.webauthn.credential"]
        if not Credential.sudo().enrolled_for(user):
            # Not an error. A first enrolment needs no step-up, and the app
            # reads this to decide whether to raise one prompt or two.
            return ok({"required": False})

        try:
            options = Credential.issue_authentication_challenge(
                context_ref=ADD_CREDENTIAL_CONTEXT
            )
        except Exception as error:  # noqa: BLE001 - message is user-facing
            return fail(
                422,
                str(error),
                code="step_up_unavailable",
                log="step-up challenge failed for %s: %s" % (user.login, error),
            )
        return ok({"required": True, "options": options})

    @http.route(
        "/api/mobile/v1/me/authenticators/options",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def registration_options(self, **kwargs):
        """Creation options for a new credential.

        Includes excludeCredentials, which is what stops one device holding two
        passkeys and satisfying a two-device requirement on its own.
        """
        user = request.env.user
        env = request.env
        config = env["sec.webauthn.config"].sudo()
        if not config.rp_id():
            return fail(
                503,
                "Security devices are not configured on this server yet. "
                "Please contact your IT team.",
                code="webauthn_not_configured",
                log="enrolment attempted with no rp_id set",
            )

        challenge = env["sec.webauthn.challenge"].sudo().issue(user, "registration")
        existing = env["sec.webauthn.credential"].sudo().enrolled_for(user)
        return ok(
            {
                "challenge": challenge.challenge,
                "rp": {"id": config.rp_id(), "name": config.rp_name()},
                "user": {
                    # A stable, non-reassignable handle. Logins can be changed
                    # and reused, and a reused handle would let a new holder
                    # inherit an old credential.
                    "id": "odoo-user-%s" % user.id,
                    "name": user.login,
                    "displayName": user.name,
                },
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},
                    {"type": "public-key", "alg": -257},
                ],
                "timeout": 300000,
                "attestation": "none",
                "authenticatorSelection": {
                    # "platform" because this endpoint enrols the phone in the
                    # user's hand. Without it Android offers the whole menu --
                    # a USB key, a QR code to some other device -- for a button
                    # that said "Add this device", which is both confusing and
                    # likely to produce a credential on the wrong hardware.
                    #
                    # The browser route deliberately does NOT set this: enrolling
                    # a security key or a second phone from a desktop is exactly
                    # what it is for.
                    "authenticatorAttachment": "platform",
                    "residentKey": "preferred",
                    # The device checks a fingerprint, face or PIN. Which of the
                    # three is the platform's business, not ours; requiring
                    # verification is what makes the credential evidence of a
                    # person rather than of a handset.
                    "userVerification": "required",
                },
                "excludeCredentials": [
                    {"type": "public-key", "id": c.credential_id} for c in existing
                ],
            }
        )

    @http.route(
        "/api/mobile/v1/me/authenticators/verify",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    @authenticated
    def registration_verify(self, **kwargs):
        """Verify the new credential and store it.

        ``assertion``, when present, is the step-up proving control of an
        existing device. It is verified *in this request* on purpose: the marker
        it sets lives on the request object, because an assertion authorises one
        action once rather than everything the user does for the rest of the day.
        """
        data = _payload() or kwargs
        user = request.env.user
        Credential = request.env["sec.webauthn.credential"]

        if not Credential.sudo()._verification_ready():
            return fail(
                503,
                "This server cannot verify security devices yet. "
                "Please contact your IT team.",
                code="verification_unavailable",
                log="py_webauthn missing; enrolment refused",
            )

        assertion = data.get("assertion")
        marked = False
        try:
            if assertion:
                Credential.verify_authentication(
                    assertion, context_ref=ADD_CREDENTIAL_CONTEXT
                )
                request.sec_webauthn_verified_for = ADD_CREDENTIAL_CONTEXT
                marked = True
            stored = Credential.verify_and_store_registration(
                data.get("credential"),
                data.get("device_label") or "Mobile device",
            )
        except Exception as error:  # noqa: BLE001 - message is user-facing
            return fail(
                422,
                str(error),
                code="enrolment_rejected",
                log="enrolment rejected for %s: %s" % (user.login, error),
            )
        finally:
            # Never leave the marker behind: anything later in this request must
            # not inherit a confirmation it did not ask for.
            if marked:
                request.sec_webauthn_verified_for = None

        status = Credential.sudo().check_enrolment_sufficient(user)
        _logger.info(
            "Mobile enrolment: %s registered %s", user.login, stored.device_label
        )
        return ok(
            {
                "id": str(stored.id),
                "label": stored.device_label,
                "enrolled": status.get("enrolled", 0),
                "required": status.get("required", 0),
                "sufficient": status.get("sufficient", False),
            }
        )
