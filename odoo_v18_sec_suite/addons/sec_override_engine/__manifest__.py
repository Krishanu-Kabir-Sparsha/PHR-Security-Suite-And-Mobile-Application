# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Override Engine",
    "summary": "Nuclear Key protocol: three-tier sequential override approval "
    "for frozen records, built on OCA base_tier_validation.",
    "version": "18.0.1.0.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    # base_tier_validation is OCA/server-ux @ 18.0 (18.0.3.4.1 verified in P0-4)
    "depends": [
        "sec_core",
        "sec_record_freeze",
        "sec_declaration_gateway",
        "sec_webauthn_auth",
        "base_tier_validation",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/override_request_views.xml",
        "views/approval_templates.xml",
        "data/reason_category_data.xml",
        "data/tier_definition_data.xml",
    ],
    "installable": True,
    "application": False,
}
