# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - WebAuthn Authentication",
    "summary": "FIDO2/WebAuthn credential enrolment and storage for approval "
    "authentication.",
    # 18.0.1.3.0 - enrolling a SECOND device now works. Route 2 of
    # _check_enrolment_permitted requires proof of an existing authenticator in
    # the same request that stores the new one, and nothing in the UI ever
    # supplied it, so adding a second device was impossible -- blocking the
    # final-approval role, which requires two.
    # 18.0.1.5.0 - serves /.well-known/assetlinks.json, so a native mobile app
    # can hold passkeys for this domain once its package and signing fingerprint
    # are set in system parameters.
    # 18.0.1.4.0 - the enrolment page now says HOW to add a second device. It
    # stated the rule ("it must be a different device") without the three routes
    # that satisfy it, so the browser offered to save the new passkey beside the
    # first, that store refused because the existing credential is excluded, and
    # the ceremony died with a browser message rather than ours.
    "version": "18.0.1.5.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    "depends": ["sec_core", "web"],
    "external_dependencies": {"python": ["webauthn"]},
    "data": [
        "security/ir.model.access.csv",
        "views/webauthn_views.xml",
        "views/recovery_views.xml",
        "views/enrolment_templates.xml",
        "data/config_parameters.xml",
        "data/cron.xml",
    ],
    "installable": True,
    "application": False,
}
