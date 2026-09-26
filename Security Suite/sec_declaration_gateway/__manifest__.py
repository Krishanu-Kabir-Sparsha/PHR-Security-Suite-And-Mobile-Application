# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Declaration Gateway",
    "summary": "Blocking Unified Declaration / NDA+ sign-off gateway, and "
    "Written/Oral instruction classification with mandatory documentation.",
    "version": "18.0.1.0.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    "depends": ["sec_core", "mail", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/declaration_templates.xml",
        "views/declaration_views.xml",
        "views/edit_request_views.xml",
        "data/declaration_placeholder.xml",
    ],
    "installable": True,
    "application": False,
}
