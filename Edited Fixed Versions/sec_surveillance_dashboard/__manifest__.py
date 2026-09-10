# Copyright 2026 Internal Security Programme
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Security Suite - Surveillance Dashboard",
    "summary": "Live anomaly feed with out-of-hours detection and triage, "
    "linking each finding to its Locker entries and override request.",
    "version": "18.0.1.2.0",
    "category": "Security",
    "license": "AGPL-3",
    "author": "Internal Security Programme",
    "website": "https://example.internal/security-suite",
    "development_status": "Alpha",
    "depends": [
        "sec_core",
        "sec_audit_locker",
        "sec_override_engine",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/dashboard_views.xml",
        "views/business_hours_views.xml",
        "views/value_threshold_views.xml",
        "views/review_wizard_views.xml",
        "data/config_parameters.xml",
    ],
    "installable": True,
    "application": False,
}
