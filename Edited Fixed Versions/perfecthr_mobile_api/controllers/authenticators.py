# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Bridge between the mobile app and WebAuthn enrolment.

The app does **not** run the WebAuthn ceremony itself, and this is a design
decision rather than a shortcut.

Android's WebView has no FIDO2 support, so a `/webauthn/enroll` page embedded in
one would render its button and then never show a fingerprint prompt -- the API
simply is not there. The ceremony has to happen in a real browser (a Chrome
Custom Tab or the external browser), and that turns out to be the better answer
anyway:

* The credential is created against the origin `dev.perfecthr.net`, exactly like
  one enrolled from a desktop browser. A phone enrolled from the app is
  therefore the *same* credential the web client sees -- one authenticator, both
  surfaces, one `rp_id`.
* Nothing needs Digital Asset Links (`assetlinks.json`) or an Android signing
  fingerprint, because we are not using native passkey APIs. That also means an
  app re-signing cannot orphan everybody's credentials.
* All the verification, anomaly-raising and enrolment-route logic already built
  and fixed in sec_webauthn_auth is reused untouched.

So this module's job is only to report status and hand back a URL. The status
comes from `check_enrolment_sufficient`, which already knows that a Tier 3
Nuclear Key holder needs two devices, so that rule is not restated here where it
could drift.

One honest caveat, surfaced to the client as `requires_web_session`: the
enrolment page is session-authenticated, and a bearer token is not a session.
The user will be asked to sign in once in the browser. That is acceptable --
enrolment is a rare, deliberate act, and the alternative (minting a
single-use browser session from a mobile token) is a new authentication path
around the declaration gate for the sake of saving one login.
"""

import logging

from odoo import http
from odoo.http import request

from .common import authenticated, ok

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
                "devices": [
                    {
                        "id": str(credential.id),
                        "label": credential.device_label,
                        "enrolled_at": credential.enrolled_at,
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
