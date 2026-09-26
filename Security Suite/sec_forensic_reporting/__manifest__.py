# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Forensic Reporting",
    "summary": "Monthly forensic and compliance report covering overrides, "
    "declarations, anomalies, segregation of duties and control health.",
    "version": "18.0.1.1.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    "depends": [
        "sec_core",
        "sec_plaza_rbac",
        "sec_declaration_gateway",
        "sec_record_freeze",
        "sec_audit_locker",
        "sec_webauthn_auth",
        "sec_override_engine",
        "sec_surveillance_dashboard",
    ],
    "data": [
        "security/ir.model.access.csv",
        "report/forensic_report_templates.xml",
        "report/forensic_report_action.xml",
        "views/forensic_report_views.xml",
        "data/cron.xml",
    ],
    "installable": True,
    "application": False,
}
