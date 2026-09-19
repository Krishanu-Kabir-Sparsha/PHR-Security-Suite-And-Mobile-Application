# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serve /.well-known/assetlinks.json so the mobile app can hold passkeys.

Android will not let a native app create or use a passkey for a domain unless
the domain publishes, at this exact path, the signing certificate of the app it
is willing to trust. That is the whole protection: without it, any app on the
phone could claim to be Perfect HR and ask the user to approve an override.

**The fingerprint is configuration, not code.** It is read from system
parameters, so a new signing key -- a second app, a Play-signed build, a
re-key -- is added by an administrator rather than by a release. Hard-coding it
would mean the server had to be redeployed in step with the app, and the two are
released by different people on different days.

Parameters (Settings > Technical > System Parameters):

    sec_webauthn.android_package     com.perfecthr.perfect_hr_mobile
    sec_webauthn.android_sha256      AB:CD:...  (comma-separated for several)

With neither set this returns an empty list rather than a 404. An empty list is
the accurate answer -- "this domain trusts no app" -- and it means the path is
already live and testable before the app exists, where a 404 is indistinguishable
from a misconfigured proxy.
"""

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

PACKAGE_PARAM = "sec_webauthn.android_package"
FINGERPRINT_PARAM = "sec_webauthn.android_sha256"

# What passkeys need. `handle_all_urls` is a different permission, for opening
# links in the app, and is deliberately not granted here: this file exists to
# authorise credentials, and quietly bundling deep-link handling into it would
# be a second decision nobody made.
PASSKEY_RELATION = "delegate_permission/common.get_login_creds"


class WebauthnAssetLinks(http.Controller):
    @http.route(
        "/.well-known/assetlinks.json",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def asset_links(self, **kwargs):
        params = request.env["ir.config_parameter"].sudo()
        package = (params.get_param(PACKAGE_PARAM) or "").strip()
        raw_fingerprints = params.get_param(FINGERPRINT_PARAM) or ""

        fingerprints = [
            # Android wants uppercase, colon-separated. Normalised here so a
            # value pasted from keytool, from Play Console, or typed by hand all
            # work -- a fingerprint that differs only in case fails silently,
            # with the app simply finding no passkeys and no error anywhere.
            part.strip().upper().replace(" ", "")
            for part in raw_fingerprints.replace("\n", ",").split(",")
            if part.strip()
        ]

        statements = []
        if package and fingerprints:
            statements.append(
                {
                    "relation": [PASSKEY_RELATION],
                    "target": {
                        "namespace": "android_app",
                        "package_name": package,
                        "sha256_cert_fingerprints": fingerprints,
                    },
                }
            )
        else:
            _logger.info(
                "assetlinks.json requested but %s / %s are not both set; "
                "returning an empty list",
                PACKAGE_PARAM,
                FINGERPRINT_PARAM,
            )

        return request.make_response(
            json.dumps(statements, indent=2),
            headers=[
                # Android fetches this itself and requires JSON. Served without
                # a cache header on purpose: it changes when a signing key is
                # added, and a stale copy on a CDN would lock the new build out
                # of passkeys with nothing to show for it.
                ("Content-Type", "application/json"),
                ("Cache-Control", "no-store"),
            ],
        )
