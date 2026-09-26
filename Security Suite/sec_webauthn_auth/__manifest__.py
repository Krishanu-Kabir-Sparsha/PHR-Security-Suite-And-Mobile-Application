# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - WebAuthn Authentication",
    "summary": "FIDO2/WebAuthn credential enrolment and storage for approval "
    "authentication.",
    # 18.0.1.9.0 - device binding. A native app cannot reach a passkey unless
    # the OS vendor validates the app-to-domain association on the handset, and
    # when that fails it fails closed and unactionably ("RP ID cannot be
    # validated") with no server-side fault to find. Mobile sign-in therefore
    # no longer depends on it: Pair a Device issues a one-time code, the app
    # generates its own Ed25519 keypair behind the phone's biometric lock, and
    # this server stores the public half beside the passkeys. mechanism on
    # sec.webauthn.credential records which proof answered, so approval
    # evidence never implies a stronger one than was given. Passkeys are
    # unchanged and remain preferred in the browser.
    # 18.0.1.3.0 - enrolling a SECOND device now works. Route 2 of
    # _check_enrolment_permitted requires proof of an existing authenticator in
    # the same request that stores the new one, and nothing in the UI ever
    # supplied it, so adding a second device was impossible -- blocking the
    # final-approval role, which requires two.
    # 18.0.1.8.0 - unlink() gained its one sanctioned exception. The reset
    # wizard could not actually delete anything: unlink refused absolutely, so
    # the only route out of a fully-revoked account was still break-glass. The
    # exception re-checks administrator rights itself rather than trusting the
    # caller's context.
    # 18.0.1.7.0 - Reset Enrolment wizard under Security Suite > Authenticators.
    # The list-view action alone was not discoverable: an administrator looking
    # for it went to Settings > Technical, where this module has no menu.
    # 18.0.1.6.0 - allowCredentials now carries the stored transports. Without
    # them the platform cannot tell where a credential lives, so Windows asked
    # for a USB key to use a Windows Hello credential on the same machine.
    # Also: a security administrator can reset a user's enrolment history, so
    # a replaced handset does not need break-glass recovery.
    # 18.0.1.5.0 - serves /.well-known/assetlinks.json, so a native mobile app
    # can hold passkeys for this domain once its package and signing fingerprint
    # are set in system parameters.
    # 18.0.1.4.0 - the enrolment page now says HOW to add a second device. It
    # stated the rule ("it must be a different device") without the three routes
    # that satisfy it, so the browser offered to save the new passkey beside the
    # first, that store refused because the existing credential is excluded, and
    # the ceremony died with a browser message rather than ours.
    "version": "18.0.1.9.0",
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
        "wizard/webauthn_reset_wizard_views.xml",
        "wizard/device_pair_wizard_views.xml",
        "views/enrolment_templates.xml",
        "data/config_parameters.xml",
        "data/cron.xml",
    ],
    "installable": True,
    "application": False,
}
