# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Perfect HR - Mobile API",
    "summary": "Bearer-token REST endpoints shaped for the Perfect HR mobile app.",
    "version": "18.0.1.5.0",
    "category": "Human Resources",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/perfect-hr",
    "development_status": "Alpha",
    # hr_holidays brings hr; hr_attendance is what the home screen's TODAY
    # section reads. sec_declaration_gateway is a real dependency, not a
    # courtesy: its ir.http override has to learn about /api paths or every
    # mobile request from a user who has not signed the declaration is answered
    # with an HTML redirect a JSON client cannot parse.
    "depends": [
        "hr",
        "hr_attendance",
        "hr_holidays",
        "sec_declaration_gateway",
        # authenticators.py reads sec.webauthn.credential/config to report
        # enrolment status and hand the app the enrolment URL.
        "sec_webauthn_auth",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mobile_token_rules.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
}
