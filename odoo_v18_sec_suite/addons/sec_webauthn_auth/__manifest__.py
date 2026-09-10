# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - WebAuthn Authentication",
    "summary": "FIDO2/WebAuthn credential enrolment and storage for approval "
    "authentication.",
    "version": "18.0.1.2.0",
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
